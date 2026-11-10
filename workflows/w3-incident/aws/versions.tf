# W3's write identities on AWS, planned offline (W3-D1), through the per-request chain of chapters 4
# and 6, not the direct Pod Identity binding W2 took.
#
# The writer server runs as one Kubernetes service account in the operations namespace and gets a base
# runtime role through EKS Pod Identity. For each write it assumes a narrow role per request, setting
# the source identity to the engineer and a workflow session tag, so CloudTrail and the cluster's audit
# log name the person (the trade W2 did not take, taken here because a write is where attribution is
# worth it). Each write role holds eks:DescribeCluster and gets an EKS access entry that maps it to a
# Kubernetes group; a custom Kubernetes Role bound to that group in the production namespace grants only
# the verbs the two writes need, patch on deployments for the restart and get and patch on deployments/scale
# for the scale (the fact sheet, B.1 to B.4). No built-in access policy is used: AmazonEKSEditPolicy
# reads Secrets and runs pods as any service account, which puts the never-list within a tool's reach.
# The Role and RoleBinding are Kubernetes manifests, applied in the cluster, not AWS resources, and are
# described in the README; this configuration is the AWS side.
#
# Every write role carries a permission boundary: eks:DescribeCluster allowed, and chapter 4's never-list
# denied outright, sts:AssumeRole among the denies so a write role can assume nothing further. The actions
# and the identities come from catalog/tools.yaml, read with yamldecode, so the catalog is the one place
# that says what an identity may do; the tests read the same file.
#
# Validated with `terraform validate` and planned with placeholder credentials through plan_offline.py
# (no request reaches AWS); never applied.

terraform {
  required_version = ">= 1.13.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      workflow = local.workflow
      owner    = local.manifest.owner
      sponsor  = local.manifest.sponsor
    }
  }
}
