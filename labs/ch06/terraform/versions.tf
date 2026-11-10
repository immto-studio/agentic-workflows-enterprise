# Chapter 6 lab: the skeleton's harness on Amazon Bedrock AgentCore, for the incident workflow, in
# ca-central-1. Validated with `terraform validate` and planned with placeholder credentials; applied
# once on synthetic data in a sandbox limited to us-east-2 (../sandbox, results/2026-10-30).

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

  # Cost allocation reads these (chapter 16); the owner is the person the budget alarm names.
  default_tags {
    tags = {
      workflow = local.workflow
      owner    = local.manifest.owner
      sponsor  = local.manifest.sponsor
    }
  }
}
