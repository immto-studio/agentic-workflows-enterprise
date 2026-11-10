# W4's identities on AWS, planned offline (W4-D1): three pull-request-only identities and a permission
# boundary that denies merge, approve, and apply (W4-D11).
#
# Each agent runs as one Kubernetes service account in its team's namespace of the ops cluster and gets
# its own role through EKS Pod Identity, the direct binding W2 took: W4 is rung 2, its two writes are a
# change record and a pull-request comment keyed by the change and carrying the trace identifier, and the
# per-request chain of W3 (the engineer as source identity) is for writes to infrastructure, which W4
# never makes. The analyst and the risk scorer hold no AWS action at all; their work is on GitHub,
# ServiceNow, and the gateway, under credentials leased from Vault for the run (chapter 4). The scribe
# holds the reads of one SQS queue, the trigger: a GitHub Actions job on the pull request assumes a
# fourth role through OIDC (ADR-0049) and sends one message there.
#
# Every role, the trigger's included, carries the boundary: the queue's actions allowed, and the
# never-list denied as AWS actions, sts:AssumeRole among them so no role can reach the apply role, and
# the apply's own actions (ec2, eks, the state bucket's writes) so the deny holds even if a policy were
# ever attached by mistake. The two GitHub entries of the never-list, the merge and the approving review,
# are not IAM actions: they are what the workflow's GitHub Apps lack, and the plan stops with the reason
# if the catalog ever gives an App a merge-capable permission.
#
# The identities, the Apps' permissions, and the actions come from catalog/tools.yaml, read with
# yamldecode, so the catalog is the one place that says what an identity may do; the tests read the same
# file. Validated with `terraform validate` and planned with placeholder credentials through
# plan_offline.py (no request reaches AWS); never applied.

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
