# W2's three read-only identities on AWS, one per MCP server (W2-D2), planned offline (W2-D1).
#
# Each server runs as a Kubernetes service account in the operations namespace and gets an IAM role
# through EKS Pod Identity; each role holds the read actions the catalog names for its server and
# nothing else, under a permission boundary that is the union of the three and denies the never-list.
# The Kubernetes server's role also gets an EKS access entry with AmazonEKSViewPolicy scoped to the
# production namespace, which is how its reads of pods and events are authorized in the cluster.
# The actions come from catalog/tools.yaml, read here with yamldecode, so the catalog is the one place
# that says what an identity may do; the vetting script and the tests read the same file.
#
# Validated with `terraform validate` and planned with placeholder credentials through plan_offline.py
# (no request reaches AWS); never applied. The fact sheet (LINKS.md, chapter 11, section B.1)
# has the action names and the EKS quotes; the Service Authorization Reference's access levels were not
# read (its section F), so the read-only claim rests on the verbs and on the vetting script's check.

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
