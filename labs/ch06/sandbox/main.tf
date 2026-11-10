# Stand-ins for what chapter 6's lab takes from Larkspur's platform, for a sandbox account's first
# apply on synthetic data (book D-036). None of this is Larkspur's design: a VPC with two private
# subnets and no route to the internet; the security groups the lab's rules name; an ECR repository
# and a CodeBuild project that builds the harness image for linux/arm64, since AgentCore Runtime runs
# ARM64 containers only; the base roles of the tool servers and the model gateway; the gateway key's
# secret, which holds no key; and a root CA made for the sandbox, valid for two days.
#
# `terraform destroy` removes all of it. The VPC goes last: AgentCore removes the runtime's network
# interfaces up to eight hours after the runtime is deleted, and the subnets wait for them.

terraform {
  required_version = ">= 1.13.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "4.4.2"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "2.8.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = { purpose = "ch06-lab-sandbox", data = "synthetic" }
  }
}

variable "region" {
  description = "The Region the sandbox account may create resources in; the lab runs there too."
  type        = string
}

variable "az_ids" {
  description = "AZ IDs that AgentCore Runtime and the tool gateway's private targets both support in the Region (us-east-2: use2-az1, use2-az2, use2-az3)."
  type        = list(string)

  validation {
    condition     = length(var.az_ids) >= 2
    error_message = "Two AZ IDs at least, as the lab's subnet_ids require."
  }
}

variable "name" {
  description = "The prefix of every name here."
  type        = string
  default     = "ch06-sandbox"
}

locals {
  cidr = "10.42.0.0/16"
}

# --- network -------------------------------------------------------------------------------------

resource "aws_vpc" "lab" {
  cidr_block           = local.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # the interface endpoints' private DNS needs both
  tags                 = { Name = var.name }
}

resource "aws_subnet" "private" {
  count                = length(var.az_ids)
  vpc_id               = aws_vpc.lab.id
  availability_zone_id = var.az_ids[count.index]
  cidr_block           = cidrsubnet(local.cidr, 8, count.index + 1)
  tags                 = { Name = "${var.name}-${var.az_ids[count.index]}" }
}

# The local route and nothing else: no internet gateway, no NAT.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = "${var.name}-private" }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# The groups the lab's rules refer to. In Larkspur's VPC they belong to the model gateway's load
# balancer, the OpenTelemetry Collector and the MCP servers; here nothing runs behind them.
resource "aws_security_group" "stand_in" {
  for_each    = toset(["model-gateway", "collector", "mcp-servers"])
  name        = "${var.name}-${each.key}"
  description = "Stand-in for the ${each.key} security group"
  vpc_id      = aws_vpc.lab.id
}

# --- the cluster the Kubernetes tools act on -----------------------------------------------------

# A control plane and no nodes: the lab's tool roles get access entries and access policies on it,
# and nothing runs there. Its endpoint is private, like the rest of the VPC.
data "aws_iam_policy_document" "eks_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks" {
  name               = "${var.name}-eks-cluster"
  description        = "Stand-in cluster's role"
  assume_role_policy = data.aws_iam_policy_document.eks_trust.json
}

resource "aws_iam_role_policy_attachment" "eks" {
  role       = aws_iam_role.eks.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "ops" {
  name     = "${var.name}-ops"
  role_arn = aws_iam_role.eks.arn

  vpc_config {
    subnet_ids              = aws_subnet.private[*].id
    endpoint_private_access = true
    endpoint_public_access  = false
  }

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }

  depends_on = [aws_iam_role_policy_attachment.eks]
}

# --- identities and the key ----------------------------------------------------------------------

data "aws_iam_policy_document" "pod_identity" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

# The base roles the lab's tool roles trust, and the model gateway's role, which the Bedrock
# endpoint's policy names. Nothing assumes them in the sandbox.
resource "aws_iam_role" "stand_in" {
  for_each           = toset(["k8s-mcp-server", "knowledge-mcp-server", "llm-gateway"])
  name               = "${var.name}-${each.key}"
  description        = "Stand-in for Larkspur's ${each.key} role"
  assume_role_policy = data.aws_iam_policy_document.pod_identity.json
}

resource "aws_secretsmanager_secret" "gateway_key" {
  name_prefix             = "${var.name}-gateway-key-"
  description             = "Stand-in for the workflow's model gateway key; it holds no key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "gateway_key" {
  secret_id     = aws_secretsmanager_secret.gateway_key.id
  secret_string = jsonencode({ key = "sandbox-placeholder-not-a-key" })
}

# --- a private root CA for the sandbox -----------------------------------------------------------

resource "tls_private_key" "root" {
  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "tls_self_signed_cert" "root" {
  private_key_pem       = tls_private_key.root.private_key_pem
  is_ca_certificate     = true
  validity_period_hours = 48
  allowed_uses          = ["cert_signing", "crl_signing"]

  subject {
    common_name  = "Larkspur sandbox root (synthetic)"
    organization = "Larkspur Mutual (fictional)"
  }
}

resource "aws_s3_bucket" "trust" {
  bucket_prefix = "${var.name}-trust-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "trust" {
  bucket                  = aws_s3_bucket.trust.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "root" {
  bucket  = aws_s3_bucket.trust.id
  key     = "larkspur-root.pem"
  content = tls_self_signed_cert.root.cert_pem
}

# --- the harness image ---------------------------------------------------------------------------

resource "aws_ecr_repository" "harness" {
  name                 = "${var.name}-harness"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
}

resource "aws_s3_bucket" "build" {
  bucket_prefix = "${var.name}-build-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "build" {
  bucket                  = aws_s3_bucket.build.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudwatch_log_group" "build" {
  name              = "/aws/codebuild/${var.name}-harness"
  retention_in_days = 1
}

data "aws_iam_policy_document" "codebuild_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codebuild" {
  name               = "${var.name}-codebuild"
  description        = "Builds the harness image from the build bucket and pushes it to the sandbox repository"
  assume_role_policy = data.aws_iam_policy_document.codebuild_trust.json
}

data "aws_iam_policy_document" "codebuild" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.build.arn}:*"]
  }
  statement {
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.build.arn}/*"]
  }
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:CompleteLayerUpload",
      "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.harness.arn]
  }
}

resource "aws_iam_role_policy" "codebuild" {
  name   = "build-and-push"
  role   = aws_iam_role.codebuild.id
  policy = data.aws_iam_policy_document.codebuild.json
}

resource "aws_codebuild_project" "harness" {
  name          = "${var.name}-harness"
  description   = "Chapter 6's harness image for linux/arm64, pushed to the sandbox repository"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 30

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    type            = "ARM_CONTAINER"
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
    privileged_mode = true # docker build needs the daemon

    environment_variable {
      name  = "REPOSITORY_URI"
      value = aws_ecr_repository.harness.repository_url
    }
  }

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.build.id}/context.zip"
    buildspec = file("${path.module}/buildspec.yml")
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.build.name
    }
  }

  depends_on = [aws_iam_role_policy.codebuild]
}

# --- what the lab's lab.tfvars takes from here (sandbox.py writes it) ----------------------------

output "lab" {
  description = "The stand-ins' identifiers, for the lab's variables."
  value = {
    vpc_id                          = aws_vpc.lab.id
    vpc_cidr                        = aws_vpc.lab.cidr_block
    subnet_ids                      = aws_subnet.private[*].id
    route_table_ids                 = [aws_route_table.private.id]
    ecr_repository_arn              = aws_ecr_repository.harness.arn
    repository_url                  = aws_ecr_repository.harness.repository_url
    model_gateway_role_arn          = aws_iam_role.stand_in["llm-gateway"].arn
    gateway_key_secret_arn          = aws_secretsmanager_secret.gateway_key.arn
    private_ca_s3_uri               = "s3://${aws_s3_bucket.trust.id}/${aws_s3_object.root.key}"
    model_gateway_security_group_id = aws_security_group.stand_in["model-gateway"].id
    collector_security_group_id     = aws_security_group.stand_in["collector"].id
    mcp_servers_security_group_id   = aws_security_group.stand_in["mcp-servers"].id
    tool_server_role_arns = {
      "k8s-mcp"       = aws_iam_role.stand_in["k8s-mcp-server"].arn
      "knowledge-mcp" = aws_iam_role.stand_in["knowledge-mcp-server"].arn
    }
    eks_cluster_name = aws_eks_cluster.ops.name
    build_bucket     = aws_s3_bucket.build.id
    build_project    = aws_codebuild_project.harness.name
  }
}

output "root_ca_pem" {
  description = "The sandbox root's certificate (public), which the image build bakes in."
  value       = tls_self_signed_cert.root.cert_pem
}
