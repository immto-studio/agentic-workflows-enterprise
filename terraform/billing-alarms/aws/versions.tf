terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.71.0"
    }
  }
}

# Billing metrics are published only in us-east-1, so the CloudWatch alarm and
# its SNS topic live there. AWS Budgets is a global service and ignores the region.
provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = local.tags
  }
}
