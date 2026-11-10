locals {
  manifest = yamldecode(file("${path.module}/${var.manifest_path}"))
  catalog  = yamldecode(file("${path.module}/${var.catalog_path}"))
  workflow = local.manifest.workflow

  # The three agents, from the catalog: name -> its identity, team, namespace, service account, and the
  # AWS actions it may hold (none for the analyst and the risk scorer; the trigger queue's reads for the
  # scribe). The trigger is the fourth identity, GitHub Actions' through OIDC.
  agents  = local.catalog.agents
  trigger = local.catalog.trigger

  cluster_arn = "arn:aws:eks:${var.region}:${var.account_id}:cluster/${var.cluster_name}"

  # The trigger queue's ARN, built from its name so the policies can refer to it before it exists.
  queue_name = "${local.workflow}-trigger"
  queue_arn  = "arn:aws:sqs:${var.region}:${var.account_id}:${local.queue_name}"

  # The GitHub Actions OIDC provider: one per account, created under ADR-0049; the trust names it.
  oidc_provider_arn = coalesce(var.github_oidc_provider_arn,
  "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com")
  oidc_subject = "repo:${local.trigger.github.organization}/${local.trigger.github.repository}:environment:${local.trigger.github.environment}"

  # The ceiling: every action any identity of the workflow may hold, from the catalog; the boundary allows
  # these on the trigger queue and nothing else. Each role's own policy then narrows to its own actions.
  ceiling_actions = sort(distinct(concat(flatten([for a in local.agents : a.aws.role_actions]),
  local.trigger.aws.role_actions)))
  queue_actions = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes",
  "sqs:ChangeMessageVisibility"]

  # The agents that hold an action at all; the others get a role and no policy.
  agents_with_actions = { for name, agent in local.agents : name => agent if length(agent.aws.role_actions) > 0 }

  # The never-list, as actions: no identity in W4 may ever hold these, so every role's boundary denies
  # them. Chapter 4's list as W2 and W3 wrote it, then the apply: sts:AssumeRole so no role can reach the
  # apply role, and the apply's own actions (compute, the cluster, the state bucket's writes and its
  # lock) so the deny holds even if a policy were ever attached by mistake.
  never_actions = [
    "iam:*",
    "sts:AssumeRole",
    "secretsmanager:*",
    "ssm:*",
    "eks:*",
    "ec2:*",
    "lambda:*",
    "cloudformation:*",
    "s3:PutObject",
    "s3:DeleteObject",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "logs:DeleteLogGroup",
    "logs:PutLogEvents",
    "cloudwatch:PutMetricData",
  ]

  # The GitHub side of the never-list. A merge needs contents: write and an approving review needs
  # pull_requests: write; administration: write and workflows: write would let an App change the rules
  # it is subject to. No App of the workflow may hold any of them.
  merge_capable   = { contents = "write", pull_requests = "write", administration = "write", workflows = "write" }
  app_permissions = { for name, agent in local.agents : name => try(agent.github_app.permissions, {}) }
  offending_permissions = flatten([
    for name, permissions in local.app_permissions : [
      for permission, level in permissions : "${name}: ${permission}: ${level}"
      if lookup(local.merge_capable, permission, "") == level
    ]
  ])
}

# The plan stops here, with the reason, when the catalog or the manifest breaks the rung-2 line.
resource "terraform_data" "catalog_checks" {
  input = local.workflow

  lifecycle {
    precondition {
      condition     = length(local.offending_permissions) == 0
      error_message = "A GitHub App of ${local.workflow} holds a merge-capable permission: ${join(", ", local.offending_permissions)}. W4 never merges or approves (W4-D6)."
    }
    precondition {
      condition     = contains(local.manifest.never, "merge_pull_request") && contains(local.manifest.never, "approve_pull_request")
      error_message = "The manifest's never-list must name merge_pull_request and approve_pull_request."
    }
    precondition {
      condition     = !can(local.agents.risk_scorer.github_app) && !can(local.agents.risk_scorer.servicenow)
      error_message = "The risk scorer reaches no source (W4-D3): it holds no GitHub App and no ServiceNow role."
    }
    precondition {
      condition     = length(setsubtract(local.ceiling_actions, local.queue_actions)) == 0
      error_message = "An identity of ${local.workflow} holds an AWS action beyond the trigger queue's: ${join(", ", setsubtract(local.ceiling_actions, local.queue_actions))}."
    }
  }
}

# --- the boundary: the most any identity of the workflow may ever do --------------------------------

data "aws_iam_policy_document" "boundary" {
  statement {
    sid       = "Ceiling"
    effect    = "Allow"
    actions   = local.ceiling_actions
    resources = [local.queue_arn]
  }

  statement {
    sid       = "NeverList"
    effect    = "Deny"
    actions   = local.never_actions
    resources = ["*"]
  }
}

resource "aws_iam_policy" "boundary" {
  name        = "${local.workflow}-boundary"
  description = "Permission boundary for W4's identities: the trigger queue's actions, and the never-list denied, sts:AssumeRole and the apply included."
  policy      = data.aws_iam_policy_document.boundary.json
}

# --- the trigger queue: one message per pull request, from GitHub Actions to the scribe ---------------

resource "aws_sqs_queue" "trigger" {
  name                       = local.queue_name
  message_retention_seconds  = 86400
  visibility_timeout_seconds = 300
  sqs_managed_sse_enabled    = true

  tags = { role = "trigger" }
}

# --- the three agents: one role each, bound to its service account through Pod Identity -------------

data "aws_iam_policy_document" "pod_identity_trust" {
  statement {
    sid     = "EKSPodIdentity"
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    # Only pods of this account's clusters: the service principal carries the cluster ARN as the source.
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:eks:${var.region}:${var.account_id}:cluster/*"]
    }
  }
}

resource "aws_iam_role" "agent" {
  for_each = local.agents

  name                 = each.value.identity
  description          = "W4 ${each.key}: ${each.value.role}"
  assume_role_policy   = data.aws_iam_policy_document.pod_identity_trust.json
  permissions_boundary = aws_iam_policy.boundary.arn
  max_session_duration = 3600

  tags = {
    agent    = each.key
    identity = each.value.identity
    team     = each.value.team
  }
}

resource "aws_eks_pod_identity_association" "agent" {
  for_each = local.agents

  cluster_name    = var.cluster_name
  namespace       = each.value.namespace
  service_account = each.value.service_account
  role_arn        = aws_iam_role.agent[each.key].arn

  tags = { agent = each.key }
}

# The scribe's one policy: the trigger queue's reads. The analyst and the risk scorer list no action in
# the catalog and get no policy: a role with a boundary and a name, so the audit names them.
data "aws_iam_policy_document" "agent" {
  for_each = local.agents_with_actions

  statement {
    sid       = "TriggerQueue"
    effect    = "Allow"
    actions   = each.value.aws.role_actions
    resources = [local.queue_arn]
  }
}

resource "aws_iam_policy" "agent" {
  for_each = local.agents_with_actions

  name        = "${each.value.identity}-queue"
  description = "W4 ${each.key}: the trigger queue's reads, and nothing else"
  policy      = data.aws_iam_policy_document.agent[each.key].json
}

resource "aws_iam_role_policy_attachment" "agent" {
  for_each = local.agents_with_actions

  role       = aws_iam_role.agent[each.key].name
  policy_arn = aws_iam_policy.agent[each.key].arn
}

# --- the trigger: GitHub Actions through OIDC, one repository and one environment, one send -----------

data "aws_iam_policy_document" "trigger_trust" {
  statement {
    sid     = "GitHubActionsOIDC"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # ADR-0049: the subject is one repository and one environment, so only that job may send a trigger.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.oidc_subject]
    }
  }
}

resource "aws_iam_role" "trigger" {
  name                 = local.trigger.identity
  description          = "W4 trigger: the pull-request job sends one message to the trigger queue, through OIDC"
  assume_role_policy   = data.aws_iam_policy_document.trigger_trust.json
  permissions_boundary = aws_iam_policy.boundary.arn
  max_session_duration = 3600

  tags = {
    agent    = "trigger"
    identity = local.trigger.identity
    team     = "platform-engineering"
  }
}

data "aws_iam_policy_document" "trigger" {
  statement {
    sid       = "SendTrigger"
    effect    = "Allow"
    actions   = local.trigger.aws.role_actions
    resources = [local.queue_arn]
  }
}

resource "aws_iam_policy" "trigger" {
  name        = "${local.trigger.identity}-send"
  description = "W4 trigger: sqs:SendMessage on the trigger queue, and nothing else"
  policy      = data.aws_iam_policy_document.trigger.json
}

resource "aws_iam_role_policy_attachment" "trigger" {
  role       = aws_iam_role.trigger.name
  policy_arn = aws_iam_policy.trigger.arn
}
