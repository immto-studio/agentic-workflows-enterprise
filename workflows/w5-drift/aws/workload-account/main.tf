# The target roles of W5's cloud and cost readers in one workload account, with their reads and their
# boundary (fact sheet C.7, C.8, and section E, continued). The root calls this module once per account the
# workspace map names, under that account's provider (accounts.tf).
#
# A reader's Pod runs in the ops cluster under its service account for this account. EKS Pod Identity
# assumes the reader's role in the ops account and then, with those credentials, this target role, and
# injects only the target role's credentials into the Pod (C.7.1, C.7.2). The trust below admits that second
# assumption and no other: the ops account as principal, the reader's ops role by aws:PrincipalArn, the
# organization by aws:PrincipalOrgID, and the session tags Pod Identity passes on for the cluster, the
# namespace, and the service account (C.7.4, C.7.6, C.8.3, C.8.5). The association's external ID stays
# out: its format is not documented (fact sheet F) and it is known only after apply (C.7.9, section E).
#
# The boundary's ceiling is the target roles' reads, and it denies the never-list with sts:AssumeRole on
# every role, so a target role chains no further and every chain stays at two links (C.8.2, section E).

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  # Each reader's service account for this account, from the catalog; the root's precondition refuses the
  # plan for an account the catalog gives no service account.
  service_accounts = { for name, reader in var.readers : name => lookup(reader.service_accounts, var.account, "") }
}

# --- the reads: what each reader's fake mirrors for one account ---------------------------------------------

data "aws_iam_policy_document" "reads" {
  for_each = var.readers

  statement {
    sid       = "${each.value.sid}Reads"
    effect    = "Allow"
    actions   = each.value.actions
    resources = ["*"]
  }
}

# --- the boundary: the most a target role in this account may ever do -------------------------------------

data "aws_iam_policy_document" "boundary" {
  source_policy_documents = [for name in sort(keys(var.readers)) : data.aws_iam_policy_document.reads[name].json]

  # The never-list as the root writes it, sts:AssumeRole on every role included: the chain ends here.
  statement {
    sid       = "NeverList"
    effect    = "Deny"
    actions   = var.never_actions
    resources = ["*"]
  }
}

resource "aws_iam_policy" "boundary" {
  name        = "${var.workflow}-target-boundary"
  description = "Permission boundary for W5's target roles in ${var.account}: their reads as the ceiling, the never-list denied, sts:AssumeRole on every role included."
  policy      = data.aws_iam_policy_document.boundary.json
}

# --- one target role per reader, assumed by the reader's ops role through Pod Identity ---------------------

data "aws_iam_policy_document" "trust" {
  for_each = var.readers

  statement {
    sid     = "OpsReaderThroughPodIdentity"
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]

    # The ops account as principal (C.8.3), narrowed to the reader's role by a condition, which AWS does
    # not convert to the role's ID, so the trust survives the role's re-creation.
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${var.ops_account_id}:root"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = [each.value.ops_role_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:PrincipalOrgID"
      values   = [var.organization_id]
    }

    # The tags Pod Identity sets on the first session, transitive, so they reach this assumption (C.7.6).
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/eks-cluster-arn"
      values   = [var.cluster_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/kubernetes-namespace"
      values   = [each.value.namespace]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/kubernetes-service-account"
      values   = [local.service_accounts[each.key]]
    }
  }
}

resource "aws_iam_role" "target" {
  for_each = var.readers

  name                 = each.value.role
  description          = "W5 ${each.key} in ${var.account}: the reads its fake mirrors, and nothing else, reached from the ops account through EKS Pod Identity"
  assume_role_policy   = data.aws_iam_policy_document.trust[each.key].json
  permissions_boundary = aws_iam_policy.boundary.arn
  max_session_duration = 3600 # a chained session lasts an hour at most whatever this says (C.8.1)

  tags = {
    identity        = each.value.role
    team            = each.value.team
    service_account = local.service_accounts[each.key]
  }
}

resource "aws_iam_policy" "reads" {
  for_each = var.readers

  name        = "${each.value.role}-reads"
  description = "W5 ${each.key} in ${var.account}: the reads its fake mirrors, and nothing else"
  policy      = data.aws_iam_policy_document.reads[each.key].json
}

resource "aws_iam_role_policy_attachment" "reads" {
  for_each = var.readers

  role       = aws_iam_role.target[each.key].name
  policy_arn = aws_iam_policy.reads[each.key].arn
}
