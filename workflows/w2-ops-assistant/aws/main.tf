locals {
  manifest = yamldecode(file("${path.module}/${var.manifest_path}"))
  catalog  = yamldecode(file("${path.module}/${var.catalog_path}"))
  workflow = local.manifest.workflow

  # server name -> its catalog entry; the role, the policy, and the service account are named after
  # the identity the catalog gives the server.
  servers = local.catalog.servers

  cluster_arn = "arn:aws:eks:${var.region}:${var.account_id}:cluster/${var.cluster_name}"

  # The trust policy, by a short name: the role block prints in the book.
  pod_identity_trust = data.aws_iam_policy_document.pod_identity_trust.json
  log_group_arn      = "arn:aws:logs:${var.region}:${var.account_id}:log-group:${var.log_group_prefix}*"

  # The actions each server's identity may hold, from the catalog. Every one of them is a read; a test
  # and the vetting script check the verbs, since the catalog is the only place they are written.
  actions = { for name, server in local.servers : name => server.aws.role_actions }

  # Where each action set applies. CloudWatch's metric reads and Describe* calls take no resource ARN,
  # so those statements say "*"; the log reads are bounded to the production log groups and the
  # cluster read to the one cluster.
  resources = {
    kubernetes-mcp = [local.cluster_arn]
    metrics-mcp    = ["*"]
    logs-mcp       = [local.log_group_arn, "arn:aws:logs:${var.region}:${var.account_id}:log-group:${var.log_group_prefix}*:log-stream:*"]
  }

  # The never-list, as actions: no identity may ever hold these, so the boundary denies them outright.
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

# --- the boundary: the most any of the three roles may ever do ------------------------------------

data "aws_iam_policy_document" "read_boundary" {
  statement {
    sid       = "ReadCeiling"
    effect    = "Allow"
    actions   = distinct(flatten(values(local.actions)))
    resources = ["*"]
  }

  statement {
    sid       = "NeverList"
    effect    = "Deny"
    actions   = local.never_actions
    resources = ["*"]
  }
}

resource "aws_iam_policy" "read_boundary" {
  name        = "${local.workflow}-read-boundary"
  description = "Permission boundary for W2's three MCP server roles: the union of their read actions, and the never-list denied."
  policy      = data.aws_iam_policy_document.read_boundary.json
}

# --- one role per server, trusted by EKS Pod Identity ---------------------------------------------

data "aws_iam_policy_document" "pod_identity_trust" {
  statement {
    sid     = "EKSPodIdentity"
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"] # <1>
    }

    # Only pods of this account's clusters: the service principal
    # carries the cluster ARN as the source.
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:eks:${var.region}:${var.account_id}:cluster/*"]
    }
  }
}

resource "aws_iam_role" "server" {
  for_each = local.servers

  name                 = each.value.identity # <2>
  description          = "W2 ${each.key}: the catalog's reads only"
  assume_role_policy   = local.pod_identity_trust
  permissions_boundary = aws_iam_policy.read_boundary.arn # <3>
  max_session_duration = 3600

  tags = {
    server   = each.key
    identity = each.value.identity
  }
}

data "aws_iam_policy_document" "server_reads" {
  for_each = local.servers

  statement {
    sid       = "Reads"
    effect    = "Allow"
    actions   = each.value.aws.role_actions
    resources = local.resources[each.key]
  }
}

resource "aws_iam_policy" "server_reads" {
  for_each = local.servers

  name        = "${each.value.identity}-reads"
  description = "W2 ${each.key}: read actions from the catalog"
  policy      = data.aws_iam_policy_document.server_reads[each.key].json
}

resource "aws_iam_role_policy_attachment" "server_reads" {
  for_each = local.servers

  role       = aws_iam_role.server[each.key].name
  policy_arn = aws_iam_policy.server_reads[each.key].arn
}

# Each server's pods run as a service account named after the server, in the operations namespace;
# the association is what hands the role to those pods and to nothing else.
resource "aws_eks_pod_identity_association" "server" {
  for_each = local.servers

  cluster_name    = var.cluster_name
  namespace       = var.servers_namespace
  service_account = each.key
  role_arn        = aws_iam_role.server[each.key].arn

  tags = {
    server = each.key
  }
}

# --- the Kubernetes server's view of the production namespace --------------------------------------
#
# eks:DescribeCluster gets the server to the API endpoint; what it may read there is the access
# policy's business. AmazonEKSViewPolicy "includes permissions that allow an IAM principal to view most
# Kubernetes resources", scoped here to the production namespace by name (fact sheet B.1). Whether the
# policy's table has a row for Secrets is unconfirmed (section F); the lab's server never asks for one.

resource "aws_eks_access_entry" "kubernetes_reader" {
  cluster_name  = var.cluster_name
  principal_arn = aws_iam_role.server["kubernetes-mcp"].arn
  type          = "STANDARD"

  tags = {
    server = "kubernetes-mcp"
  }
}

resource "aws_eks_access_policy_association" "kubernetes_view" {
  cluster_name  = var.cluster_name
  principal_arn = aws_iam_role.server["kubernetes-mcp"].arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"

  access_scope {
    type       = "namespace"
    namespaces = var.read_namespaces
  }

  depends_on = [aws_eks_access_entry.kubernetes_reader]
}
