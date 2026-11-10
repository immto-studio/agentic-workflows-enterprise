locals {
  manifest      = yamldecode(file("${path.module}/${var.manifest_path}"))
  catalog       = yamldecode(file("${path.module}/${var.catalog_path}"))
  workspace_map = yamldecode(file("${path.module}/${var.workspace_map_path}"))
  workflow      = local.manifest.workflow
  default_tags  = { workflow = local.workflow, owner = local.manifest.owner, sponsor = local.manifest.sponsor }
  cluster_arn   = "arn:aws:eks:${var.region}:${var.account_id}:cluster/${var.cluster_name}"

  # The identities in the ops account, from the catalog: the four readers, the harness, and the cost
  # reader's export identity, each with its team and namespace. The cloud and cost readers have one service
  # account per workload account (the bindings below); every other identity has one.
  servers    = local.catalog.servers
  export     = local.servers["cost-mcp"].export
  identities = merge(local.servers, { harness = local.catalog.harness, cost-export = local.export })

  # Every ops role's ARN, built from its name so the target roles' trusts and the bucket's deny can name the
  # roles before they exist.
  role_arns = { for name, id in local.identities : name => "arn:aws:iam::${var.account_id}:role/${id.identity}" }

  # The state reader's resources: the state key of each workspace the agent's group may read, and no
  # other. payments-cde has a key in the bucket and is in no grant. An object ARN names one key exactly,
  # so the lock file `<key>.tflock` beside it is never covered (fact sheet B.2).
  state            = local.servers["state-mcp"].aws.resources
  state_bucket_arn = "arn:aws:s3:::${local.state.bucket}"
  workspaces       = local.workspace_map.teams[local.catalog.membership.group]
  state_keys       = [for workspace in local.workspaces : replace(local.state.prefix, "*", workspace)]
  state_objects    = [for key in local.state_keys : "${local.state_bucket_arn}/${key}"]

  # The export identity's resources: one bucket the ops account owns, one prefix, where the management
  # account's CUR 2.0 export of every account lands daily (C.11).
  export_bucket_arn = "arn:aws:s3:::${var.cost_export_bucket}"

  # Each reader's catalog actions by what they act on: S3 objects, S3 listings, the state's key, and the
  # account-wide reads (the describes, the tagging read, the trail, the metric, Cost Explorer, Budgets, and
  # the anomalies), which this plan grants on "*" and does not narrow by resource. The account-wide reads go
  # to the target roles in the workload accounts, as section E decides (the event history is one account's,
  # C.9, and so are the cost data, the budgets, and the anomaly monitors, C.10); the bucket and key reads stay
  # in the ops account, where the buckets and the key are.
  actions       = { for name, server in local.servers : name => server.aws.role_actions }
  object_reads  = { for name, a in local.actions : name => [for x in a : x if startswith(x, "s3:GetObject")] }
  listing_reads = { for name, a in local.actions : name => [for x in a : x if startswith(x, "s3:List")] }
  key_reads     = { for name, a in local.actions : name => [for x in a : x if startswith(x, "kms:")] }
  account_reads = { for name, a in local.actions : name => [for x in a : x if !startswith(x, "s3:") && !startswith(x, "kms:")] }

  # --- across accounts: the target roles (C.7, C.8, and the fact sheet's section E, continued) ----------

  # The accounts the agent's group may read. None is the ops account, since the map puts no workspace
  # there, so no account-wide read stays on an ops role.
  mapped_accounts = local.workspace_map.accounts[local.catalog.membership.group]

  # The readers that read those accounts are those the catalog gives a target role: the cloud and cost
  # readers. Each ops role holds the chain's two actions on its own target roles and nothing else (C.7.3).
  chained       = sort([for name, server in local.servers : name if can(server.aws.target_role)])
  chain_actions = ["sts:AssumeRole", "sts:TagSession"]

  # What each one's target role is in every workload account, for workload-account/.
  target_readers = { for name in local.chained : name => {
    role             = local.servers[name].aws.target_role
    ops_role_arn     = local.role_arns[name]
    namespace        = local.servers[name].namespace
    service_accounts = try(local.servers[name].service_accounts, {})
    actions          = local.account_reads[name]
    sid              = replace(title(trimsuffix(name, "-mcp")), "-", "")
    team             = local.servers[name].team
  } }

  # reader -> account -> its target role's ARN, built from the account's ID and the role's name, so the
  # chains, the bindings, and the bucket's deny show in the plan before the roles exist. The module calls
  # in accounts.tf give the accounts, so each target role exists before an association names it.
  target_role_arns = { for name in local.chained : name => {
    for account, roles in local.target_accounts : account => "arn:aws:iam::${var.workload_account_ids[account]}:role/${roles[name]}"
  } }
  target_arns = sort(flatten([for name, arns in local.target_role_arns : values(arns)]))

  # The map holds at IAM (section E): every account it names has a module call in accounts.tf and a service
  # account for each of the two readers, and no account outside it has either. The precondition refuses the
  # plan with each disagreement, and the bindings take only the accounts that have both.
  accounts_without_targets = [for account in local.mapped_accounts : account
  if !alltrue([for name in local.chained : can(local.target_accounts[account][name])])]
  accounts_without_service_accounts = [for account in local.mapped_accounts : account
  if !alltrue([for name in local.chained : can(local.servers[name].service_accounts[account])])]
  accounts_outside_the_map = sort(setsubtract(concat(keys(local.target_accounts),
  flatten([for name in local.chained : keys(try(local.servers[name].service_accounts, {}))])), local.mapped_accounts))
  account_disagreements = concat(
    [for account in local.accounts_without_targets : "${account} has no target roles"],
    [for account in local.accounts_without_service_accounts : "${account} has no service accounts"],
    [for account in local.accounts_outside_the_map : "${account} has target roles or service accounts and is not in the map"],
  )
  read_accounts = [for account in local.mapped_accounts : account
  if !contains(concat(local.accounts_without_targets, local.accounts_without_service_accounts), account)]

  # service account -> the identity whose ops role it is bound to, and the target role chained to it. One
  # binding for each identity without a target; one per account for the cloud and cost readers, since a
  # service account takes one association and so one target (C.7.7).
  bindings = merge(
    { for name, id in local.identities : id.service_account => {
      identity        = name
      namespace       = id.namespace
      account         = tostring(null)
      target_role_arn = tostring(null)
    } if !contains(local.chained, name) },
    { for pair in setproduct(local.chained, local.read_accounts) : local.servers[pair[0]].service_accounts[pair[1]] => {
      identity        = pair[0]
      namespace       = local.servers[pair[0]].namespace
      account         = pair[1]
      target_role_arn = local.target_role_arns[pair[0]][pair[1]]
    } },
  )

  # The ops roles' policies: the state reader's and the export identity's reads, and the two readers'
  # chains. The policy reader and the harness have none. `granted` says where each reader's catalog actions
  # are granted, so the plan can refuse a catalog action no statement grants: the account-wide reads by the
  # target roles, the state reader's by its own policy, the cost reader's two S3 reads by the export identity.
  read_documents = {
    state-mcp   = data.aws_iam_policy_document.state_reader.json
    cost-export = data.aws_iam_policy_document.export_reader.json
  }
  chain_documents = { for name in local.chained : name => data.aws_iam_policy_document.chain[name].json }
  granted = {
    state-mcp = concat(local.object_reads["state-mcp"], local.listing_reads["state-mcp"], local.key_reads["state-mcp"])
    cloud-mcp = try(local.target_readers["cloud-mcp"].actions, [])
    cost-mcp  = concat(try(local.target_readers["cost-mcp"].actions, []), local.object_reads["cost-mcp"], local.listing_reads["cost-mcp"])
  }
  servers_with_actions = sort([for name, server in local.servers : name if length(server.aws.role_actions) > 0])

  # A read by its verb; kms:Decrypt is the one other action, the state reader's alone (the catalog says why).
  every_action = sort(distinct(flatten(values(local.actions))))
  not_reads = [for a in local.every_action : a
  if !can(regex("^[a-z0-9-]+:(Get|List|Describe|Lookup|View)", a)) && a != "kms:Decrypt"]

  # The state's writes: what an apply does to the state and its lock (fact sheet B.2), and the version
  # delete that would remove the history a restore relies on (C.5). The bucket's own policy denies them
  # to every role (state_bucket_deny below), and the boundaries' never-list carries them too.
  state_writes = ["s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"]

  # The never-list as AWS actions: no W5 identity may ever hold these, so the boundaries deny them on every
  # role. Chapter 4's list as W2, W3, and W4 wrote it, then W5's own; each group names the manifest entries
  # it serves. The nineteen named actions the fact sheet looked up, and sts:AssumeRole, are "Write" in the
  # Service Authorization Reference (C.13). W4 denied ec2:* outright, and W5 cannot, because the cloud reader
  # describes, so the EC2 writes are denied by verb. The merge and the approving review are GitHub's: see
  # the precondition.
  never_actions = [
    # modify_iam, read_vault_secret, run_command, delete_namespace, and the evidence: chapter 4's list
    "iam:*",
    "secretsmanager:*",
    "ssm:*",
    "eks:*",
    "logs:DeleteLogGroup",
    "logs:PutLogEvents",
    "cloudwatch:PutMetricData",
    # apply_plan: no role can reach the pipeline's apply role, none writes the state or encrypts with its
    # key (an apply needs kms:Encrypt and kms:GenerateDataKey there, B.2), and none touches the services
    # whose resources in the workspaces' state only an apply changes. The ops boundary denies
    # sts:AssumeRole on every role but the named targets; the target roles' boundary on every role.
    "sts:AssumeRole",
    "s3:PutObject",
    "s3:DeleteObject",
    "s3:DeleteObjectVersion",
    "kms:Encrypt",
    "kms:GenerateDataKey",
    "cloudformation:*",
    "lambda:*",
    "rds:*",
    # delete_resource and stop_instance, the waste W5 finds included, and the resize W5-D7 names with them
    "ec2:Delete*",
    "ec2:Terminate*",
    "ec2:Stop*",
    "ec2:Modify*",
    "elasticloadbalancing:Delete*",
    # modify_security_group (chapter 2's PCI sentence), and the routes the postmortem's apply removed
    "ec2:Authorize*",
    "ec2:Revoke*",
    "ec2:UpdateSecurityGroupRuleDescriptions*",
    "ec2:CreateSecurityGroup",
    "ec2:CreateRoute",
    "ec2:ReplaceRoute",
    # the budgets and the anomaly monitor the alarm path rides on (W5-D11, C.4), resources of the
    # workspaces' state (the aws-budget-alarm module); a budget action can apply an IAM policy or an SCP,
    # or stop instances, in the account it runs in (C.14)
    "budgets:ModifyBudget",
    "budgets:CreateBudgetAction",
    "budgets:UpdateBudgetAction",
    "budgets:DeleteBudgetAction",
    "budgets:ExecuteBudgetAction",
    "ce:UpdateAnomalyMonitor",
    "ce:DeleteAnomalyMonitor",
    "ce:UpdateAnomalySubscription",
    "ce:DeleteAnomalySubscription",
  ]
  ops_never_actions = [for action in local.never_actions : action if action != "sts:AssumeRole"]

  # The GitHub half, as the catalog records it: these preconditions check the catalog, not GitHub, which the
  # harness checks before every night's writes (harness/github_check.py). On the upstream a merge is a
  # "Contents" write and a workflow file a "Workflows" write (fact sheet A.1); "Administration" write edits the
  # rulesets and branch protection W5 relies on and could put an App on the bypass list (A.6.1, A.6.4). A bypass
  # actor skips the ruleset, and an App can be one (A.4). An App's permissions hold on every repository it is
  # installed on (A.1), so the fork App installed on the upstream would carry its Contents write there.
  github        = local.catalog.github
  merge_capable = ["contents", "workflows", "administration"]
  installs      = { for name, app in local.github.apps : name => flatten([app.installed_on]) }
  upstream_apps = [for name, places in local.installs : name if contains(places, local.github.upstream)]
  offending_permissions = flatten([
    for name in local.upstream_apps : [
      for permission, level in local.github.apps[name].permissions : "${name}: ${permission}: ${level}"
      if contains(local.merge_capable, permission) && contains(["write", "admin"], level)
    ]
  ])
  # The fork App on the upstream: an App installed on the fork with a merge-capable write and installed upstream as
  # well. The upstream App installed on the fork too, the fallback should GitHub refuse a pull request from a private
  # fork its opener cannot see (README, fact sheet A.11), holds no such write and passes.
  fork_apps_upstream = [for name, places in local.installs : name
    if contains(places, local.github.fork) && contains(places, local.github.upstream) && anytrue([
      for permission, level in local.github.apps[name].permissions :
      contains(local.merge_capable, permission) && contains(["write", "admin"], level)
  ])]

  # The bypass list in GitHub's shape ({actor_id, actor_type, bypass_mode}): any actor is refused, and a W5 App is
  # named by its registration's id under the actor type Integration, never by a name found inside the JSON
  # (A.6.4: actor_id "Required for Integration ..."). A ruleset's bypass list is returned only to a caller with
  # write access to the ruleset (A.13.3), which no W5 App holds, so this record is where the check can be made.
  bypass_actors = try(local.github.ruleset.bypass_actors, [])
  app_ids       = { for name, app in local.github.apps : tostring(app.id) => name }
  bypassing_apps = sort([for actor in local.bypass_actors : "${local.app_ids[tostring(actor.actor_id)]} (Integration ${actor.actor_id})"
  if try(actor.actor_type, "") == "Integration" && contains(keys(local.app_ids), tostring(try(actor.actor_id, "")))])
  bypass_list = [for actor in local.bypass_actors :
  "${try(actor.actor_type, "an actor of no type")} ${try(actor.actor_id, "with no id")} (${try(actor.bypass_mode, "always")})"]
  code_owner_review = try(local.github.ruleset.require_pull_request.code_owner_review, false) == true

  w5_never = ["apply_plan", "merge_pull_request", "approve_pull_request", "delete_resource", "stop_instance",
  "modify_security_group"]
}

# The plan stops here, with the reason, when the catalog, the map, or the manifest breaks the rung-2 line. Each
# precondition checks a record W5 keeps, not the live systems: the harness checks GitHub before every night.
resource "terraform_data" "catalog_checks" {
  input = local.workflow

  lifecycle {
    precondition {
      condition     = length(local.offending_permissions) == 0
      error_message = "The catalog gives a GitHub App installed on ${local.github.upstream} a merge-capable permission: ${join(", ", local.offending_permissions)}. W5 never merges, approves, or writes a workflow file (W5-D6, W5-D7)."
    }
    precondition {
      condition     = length(local.fork_apps_upstream) == 0
      error_message = "The catalog installs the fork App on the upstream: ${join(", ", local.fork_apps_upstream)} on ${local.github.upstream}. It may hold no permission there, where its Contents write would merge (W5-D6)."
    }
    precondition {
      condition     = length(local.bypassing_apps) == 0
      error_message = "The catalog's ruleset names an App of W5 as a bypass actor: ${join(", ", local.bypassing_apps)}. A bypass actor skips the code owner's review and the required check (W5-D6)."
    }
    precondition {
      condition     = length(local.bypass_actors) == 0
      error_message = "The catalog's ruleset names bypass actors: ${join(", ", local.bypass_list)}. No actor may skip the code owner's review and the required check on the upstream's main (W5-D6)."
    }
    precondition {
      condition     = local.code_owner_review
      error_message = "The catalog's ruleset does not require a code owner's review on the upstream's main; the review of a person who owns the code is the control the merge rests on (W5-D6)."
    }
    precondition {
      condition     = length(setsubtract(local.w5_never, local.manifest.never)) == 0
      error_message = "The manifest's never-list must name W5's six: ${join(", ", local.w5_never)} (W5-D7)."
    }
    precondition {
      condition     = length(local.not_reads) == 0 && alltrue([for name, a in local.actions : name == "state-mcp" || !contains(a, "kms:Decrypt")])
      error_message = "An identity of ${local.workflow} holds an AWS action that is not a read, or a decrypt outside the state reader: ${join(", ", local.not_reads)}."
    }
    precondition {
      condition     = length(local.servers["policy-mcp"].aws.role_actions) == 0 && length(local.catalog.harness.aws.role_actions) == 0
      error_message = "The policy reader and the harness hold no AWS action (W5-D15)."
    }
    precondition {
      condition = local.servers_with_actions == sort(keys(local.granted)) && alltrue([
      for name in local.servers_with_actions : length(setsubtract(local.actions[name], local.granted[name])) == 0])
      error_message = "Every reader with an AWS action needs a statement for each: the account-wide reads in its target roles, the bucket and key reads in the ops account."
    }
    precondition {
      condition     = length(local.account_disagreements) == 0
      error_message = "The workspace map and W5's identities disagree on the accounts: ${join("; ", local.account_disagreements)}. Each account the map names needs a provider and a module call in accounts.tf and a service account per reader in the catalog, and no other account may have either (C.7.7, section E)."
    }
  }
}

# --- the ops roles' policies: what each one's fake mirrors in the ops account, or the chain ---------------

data "aws_iam_policy_document" "state_reader" {
  statement {
    sid       = "StateObjects"
    effect    = "Allow"
    actions   = local.object_reads["state-mcp"]
    resources = local.state_objects
  }

  # A listing names the mapped state keys only: the reader lists a key's versions, never the prefix. Both
  # listings take s3:prefix, and a versioned bucket's version list is ListBucketVersions (C.12.1, C.12.2).
  statement {
    sid       = "StateKeysListed"
    effect    = "Allow"
    actions   = local.listing_reads["state-mcp"]
    resources = [local.state_bucket_arn]

    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values   = local.state_keys
    }
  }

  # The state objects are encrypted with the bucket's key (SSE-KMS); reading one decrypts its data key.
  statement {
    sid       = "StateKeyDecrypt"
    effect    = "Allow"
    actions   = local.key_reads["state-mcp"]
    resources = [var.state_kms_key_arn]
  }
}

# The organization's CUR 2.0 export, read in the ops account by the cost reader's export identity: the
# management account delivers every account's rows to a bucket the ops account owns (C.11.1, C.11.2), with
# ACLs disabled, so the ops account owns the objects. They arrive under SSE-S3 (C.11.3), and the reader
# reads them with s3:GetObject like any other object (C.3, C.11).
data "aws_iam_policy_document" "export_reader" {
  statement {
    sid       = "ExportObjects"
    effect    = "Allow"
    actions   = local.object_reads["cost-mcp"]
    resources = ["${local.export_bucket_arn}/${local.export.prefix}"]
  }

  statement {
    sid       = "ExportListed"
    effect    = "Allow"
    actions   = local.listing_reads["cost-mcp"]
    resources = [local.export_bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [local.export.prefix]
    }
  }
}

# The cloud and cost readers' ops roles: the chain's second assumption, on that reader's target role in each
# workload account and no other role (C.7.3). sts:TagSession passes the Pod's session tags on to the
# targets' trusts. AWS files both actions under "Write" (C.13.6): they are the only actions of any W5 role
# that are not reads, and they reach no further than the named targets.
data "aws_iam_policy_document" "chain" {
  for_each = local.target_readers

  statement {
    sid       = "${each.value.sid}Targets"
    effect    = "Allow"
    actions   = local.chain_actions
    resources = values(local.target_role_arns[each.key])
  }
}

# --- the ops boundary: the most any W5 identity in the ops account may ever do ----------------------------

data "aws_iam_policy_document" "boundary" {
  # The ceiling is the ops roles' own statements, the chains included, so a policy attached to a W5 role by
  # mistake can reach no further; the policy reader and the harness hold none of them.
  source_policy_documents = concat(values(local.read_documents), values(local.chain_documents))

  statement {
    sid       = "LockFiles"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = ["${local.state_bucket_arn}/*.tflock"]
  }

  statement {
    sid       = "NeverList"
    effect    = "Deny"
    actions   = local.ops_never_actions
    resources = ["*"]
  }

  # sts:AssumeRole on every role but the readers' named targets. A deny of the targets themselves would stop
  # Pod Identity's own chain, since an explicit deny in any policy ends a request (C.8.2); every other role,
  # the pipeline's apply role among them, stays out of reach (section E).
  statement {
    sid           = "AssumeRoleOutsideTargets"
    effect        = "Deny"
    actions       = ["sts:AssumeRole"]
    not_resources = local.target_arns
  }
}

resource "aws_iam_policy" "boundary" {
  name        = "${local.workflow}-boundary"
  description = "Permission boundary for W5's roles in the ops account: their statements as the ceiling, sts:AssumeRole denied on every role but the readers' target roles, the lock files and the rest of the never-list denied."
  policy      = data.aws_iam_policy_document.boundary.json
}

# --- one role per identity in the ops account, bound to its service accounts through Pod Identity ---------

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

resource "aws_iam_role" "identity" {
  for_each = local.identities

  name                 = each.value.identity
  description          = "W5 ${each.key}: ${contains(local.chained, each.key) ? "sts:AssumeRole and sts:TagSession on its target roles, and nothing else" : contains(keys(local.read_documents), each.key) ? "the reads its fake mirrors, and nothing else" : "no AWS action"}"
  assume_role_policy   = data.aws_iam_policy_document.pod_identity_trust.json
  permissions_boundary = aws_iam_policy.boundary.arn
  max_session_duration = 3600

  tags = merge({ identity = each.value.identity, team = each.value.team },
  can(each.value.service_account) ? { service_account = each.value.service_account } : {})
}

# A target role's trust matches the session tags, so they stay on (C.7.4, C.7.6); an association with a
# target hands the Pod only the target role's credentials, for 59 minutes at a time (C.7.8).
resource "aws_eks_pod_identity_association" "identity" {
  for_each = local.bindings

  cluster_name         = var.cluster_name
  namespace            = each.value.namespace
  service_account      = each.key
  role_arn             = aws_iam_role.identity[each.value.identity].arn
  target_role_arn      = each.value.target_role_arn
  disable_session_tags = false

  tags = { identity = local.identities[each.value.identity].identity }
}

# The state reader's and the export identity's reads, and the two readers' chains. The policy reader and
# the harness get none: a role with the boundary and a name, so the audit names them, as W4's analyst.
resource "aws_iam_policy" "reads" {
  for_each = local.read_documents

  name        = "${local.identities[each.key].identity}-reads"
  description = "W5 ${each.key}: the reads its fake mirrors, and nothing else"
  policy      = each.value
}

resource "aws_iam_role_policy_attachment" "reads" {
  for_each = local.read_documents

  role       = aws_iam_role.identity[each.key].name
  policy_arn = aws_iam_policy.reads[each.key].arn
}

resource "aws_iam_policy" "chain" {
  for_each = local.chain_documents

  name        = "${local.identities[each.key].identity}-chain"
  description = "W5 ${each.key}: sts:AssumeRole and sts:TagSession on its target role in each workload account, and nothing else"
  policy      = each.value
}

resource "aws_iam_role_policy_attachment" "chain" {
  for_each = local.chain_documents

  role       = aws_iam_role.identity[each.key].name
  policy_arn = aws_iam_policy.chain[each.key].arn
}

# --- the state bucket's deny, for the state stack to merge ---------------------------------------------
#
# The bucket and its one policy belong to the platform's state stack (C.12.3). A second aws_s3_bucket_policy
# here would replace that stack's policy on every apply and the stack's own apply would replace it back, so
# this configuration writes the statement and outputs it; the state stack adds it to the bucket's policy
# document through source_policy_documents, as W4 names the account's OIDC provider rather than creating
# it. An explicit deny beats any allow (C.5), so a mistaken grant to a W5 role still cannot write state.

data "aws_iam_policy_document" "state_bucket_deny" {
  statement {
    sid       = "W5DeniedStateWrites"
    effect    = "Deny"
    actions   = local.state_writes
    resources = ["${local.state_bucket_arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    # By aws:PrincipalArn, which is the role's ARN for a role's session (C.5); NotPrincipal is not used.
    # Every W5 role: the six in the ops account and the target roles in the workload accounts.
    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = sort(concat(values(local.role_arns), local.target_arns))
    }
  }
}
