locals {
  manifest = yamldecode(file("${path.module}/${var.manifest_path}"))
  catalog  = yamldecode(file("${path.module}/${var.catalog_path}"))
  workflow = local.manifest.workflow

  # The writer server's two write identities, from the catalog: the tool -> the role name it assumes.
  writer       = local.catalog.servers["writer-mcp"]
  identities   = local.writer.identities # { restart_deployment = "larkspur-ops-restarter", scale_deployment = "larkspur-ops-scaler" }
  runtime_name = "${local.workflow}-writer-runtime"

  cluster_arn = "arn:aws:eks:${var.region}:${var.account_id}:cluster/${var.cluster_name}"

  # The write roles' ARNs, named so the trust and the assume policy can refer to them before they exist.
  write_role_arns = { for tool, name in local.identities : tool => "arn:aws:iam::${var.account_id}:role/${name}" }

  # The one IAM action a write role holds: eks:DescribeCluster, to reach the API endpoint. The write
  # itself is a Kubernetes PATCH, authorized by the access entry's group and the custom Role, not by an
  # IAM action (fact sheet B.3, B.4). role_actions in the catalog is [eks:DescribeCluster].
  write_actions = local.writer.aws.role_actions

  # The never-list, as actions: no identity in W3's chain may ever hold these, so every write role's
  # boundary denies them. sts:AssumeRole is denied so a write role can assume nothing further; the runtime
  # role, which must assume the write roles, is not under this boundary.
  never_actions = [
    "iam:*",
    "sts:AssumeRole",
    "secretsmanager:*",
    "ssm:*",
    "eks:AccessKubernetesApi",
    "eks:CreateAccessEntry",
    "eks:UpdateAccessEntry",
    "eks:AssociateAccessPolicy",
    "logs:DeleteLogGroup",
    "logs:PutLogEvents",
    "cloudwatch:PutMetricData",
    "ec2:AuthorizeSecurityGroupIngress",
    "ec2:AuthorizeSecurityGroupEgress",
    "ec2:RevokeSecurityGroupIngress",
    "ec2:RevokeSecurityGroupEgress",
    "ec2:ModifySecurityGroupRules",
    "ec2:CreateSecurityGroup",
    "ec2:DeleteSecurityGroup",
  ]
}

# --- the write boundary: the most any write role may ever do --------------------------------------

data "aws_iam_policy_document" "write_boundary" {
  statement {
    sid       = "WriteCeiling"
    effect    = "Allow"
    actions   = local.write_actions
    resources = ["*"]
  }

  statement {
    sid       = "NeverList"
    effect    = "Deny"
    actions   = local.never_actions
    resources = ["*"]
  }
}

resource "aws_iam_policy" "write_boundary" {
  name        = "${local.workflow}-write-boundary"
  description = "Permission boundary for W3's write roles: eks:DescribeCluster, and the never-list denied, sts:AssumeRole included."
  policy      = data.aws_iam_policy_document.write_boundary.json
}

# --- the runtime role: the writer server's pod identity, which assumes a write role per request --------

data "aws_iam_policy_document" "runtime_trust" {
  statement {
    sid     = "EKSPodIdentity"
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    # Only pods of this account's clusters: Pod Identity tags the session with the cluster's ARN.
    condition {
      test     = "StringLike"
      variable = "aws:RequestTag/eks-cluster-arn"
      values   = ["arn:aws:eks:${var.region}:${var.account_id}:cluster/*"]
    }
  }
}

resource "aws_iam_role" "runtime" {
  name                 = local.runtime_name
  description          = "W3 writer runtime: assumes a write role per request, with the engineer as source identity"
  assume_role_policy   = data.aws_iam_policy_document.runtime_trust.json
  max_session_duration = 3600

  tags = { role = "writer-runtime" }
}

# The runtime may assume the two write roles and read the cluster endpoint; the per-request assume sets
# the source identity to the engineer and a workflow session tag (chapters 4 and 6).
data "aws_iam_policy_document" "runtime" {
  statement {
    sid       = "AssumeWriteRoles"
    effect    = "Allow"
    actions   = ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"]
    resources = values(local.write_role_arns)
  }

  statement {
    sid       = "DescribeCluster"
    effect    = "Allow"
    actions   = ["eks:DescribeCluster"]
    resources = [local.cluster_arn]
  }
}

resource "aws_iam_policy" "runtime" {
  name        = "${local.runtime_name}-assume"
  description = "W3 writer runtime: assume the two write roles, describe the cluster"
  policy      = data.aws_iam_policy_document.runtime.json
}

resource "aws_iam_role_policy_attachment" "runtime" {
  role       = aws_iam_role.runtime.name
  policy_arn = aws_iam_policy.runtime.arn
}

resource "aws_eks_pod_identity_association" "runtime" {
  cluster_name    = var.cluster_name
  namespace       = var.servers_namespace
  service_account = var.writer_service_account
  role_arn        = aws_iam_role.runtime.arn

  tags = { role = "writer-runtime" }
}

# --- one write role per write tool, assumed by the runtime for one request -----------------------------

data "aws_iam_policy_document" "write_trust" {
  for_each = local.identities

  statement {
    sid    = "RuntimeAssumesPerRequest"
    effect = "Allow"
    actions = [
      "sts:AssumeRole",
      "sts:TagSession",
      "sts:SetSourceIdentity",
    ]

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.runtime.arn]
    }

    # Only for this workflow: the runtime sets the session tag
    # when it assumes the role.
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/workflow"
      values   = [local.workflow]
    }
  }
}

resource "aws_iam_role" "write" {
  for_each = local.identities

  name                 = each.value
  description          = "W3 ${each.key}: eks:DescribeCluster and one namespaced Kubernetes write, assumed per request"
  assume_role_policy   = data.aws_iam_policy_document.write_trust[each.key].json
  permissions_boundary = aws_iam_policy.write_boundary.arn
  max_session_duration = 3600

  tags = {
    tool     = each.key
    identity = each.value
  }
}

data "aws_iam_policy_document" "write" {
  for_each = local.identities

  statement {
    sid       = "DescribeCluster"
    effect    = "Allow"
    actions   = local.write_actions
    resources = [local.cluster_arn]
  }
}

resource "aws_iam_policy" "write" {
  for_each = local.identities

  name        = "${each.value}-eks"
  description = "W3 ${each.key}: eks:DescribeCluster only; the write itself is the custom Kubernetes Role's"
  policy      = data.aws_iam_policy_document.write[each.key].json
}

resource "aws_iam_role_policy_attachment" "write" {
  for_each = local.identities

  role       = aws_iam_role.write[each.key].name
  policy_arn = aws_iam_policy.write[each.key].arn
}

# --- each write role's EKS access entry, mapped to the writers' Kubernetes group -----------------------
#
# The access entry maps each write role to the one group var.writer_k8s_group; a custom Kubernetes Role
# bound to that group in var.write_namespaces grants only the verbs the two writes need (patch on
# deployments for the restart, get and patch on deployments/scale for the scale, fact sheet B.1 to B.4).
# No AmazonEKS access policy is associated: the built-in edit policy is too broad (it reads Secrets and
# runs pods as any service account). The Role and RoleBinding are Kubernetes manifests, in the README,
# applied in the cluster.

resource "aws_eks_access_entry" "write" {
  for_each = local.identities

  cluster_name      = var.cluster_name
  principal_arn     = aws_iam_role.write[each.key].arn
  type              = "STANDARD"
  kubernetes_groups = [var.writer_k8s_group]

  tags = {
    tool = each.key
  }
}
