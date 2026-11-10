# Chapter 16, step 7: the cloud session's resources in the lab account (companion #14, O-D1), applied
# once in us-east-2 on synthetic data (book D-034, D-036) and destroyed in the same session. The budget
# comes first (budget.tf); everything else depends on it. The provider's default tags mark every resource
# as this session's, and cloud/leftovers.py looks for them after the destroy.

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
      purpose  = "ch16-cloud-session"
      data     = "synthetic"
      workflow = var.workflow
    }
  }
}

data "aws_caller_identity" "current" {}
