# W5's identities on AWS, planned offline (W5-D1, W5-D15): six roles in the ops account, two target roles in
# each workload account the map names, a boundary in every account, the state bucket's deny for the state
# stack to merge, and the plan's refusals of a merge-capable GitHub App and of a map that IAM does not hold.
#
# Each reader, the harness, and the cost reader's export identity run as Kubernetes service accounts in the
# platform team's namespace of the ops cluster and get their roles through EKS Pod Identity, the direct
# binding W2 and W4 took: W5 is rung 2, its one write is a pull request on GitHub, and it writes nothing on
# AWS, so W3's per-request chain has nothing to carry. The state reader holds the bucket's reads on the state
# keys of the mapped workspaces, and the decrypt of the bucket's key; the export identity the organization's
# CUR 2.0 export in a bucket the ops account owns (fact sheet C.11). The policy reader and the harness hold no
# AWS action: each gets a role with no policy, so the boundary binds it and CloudTrail names it if it ever
# calls AWS (W4's analyst).
#
# The cloud and cost readers read the three workload accounts of catalog/workspace-map.yaml through Pod
# Identity target roles (C.7, section E): one service account per account, whose association names the
# reader's ops role and that account's target role, so EKS makes both assumptions and no W5 code calls STS.
# The ops role holds sts:AssumeRole and sts:TagSession on its target roles and nothing else (C.7.3); each
# target role holds the reads the reader's fake mirrors, in its own account: the describes, the tagging
# read, the event history (one account and one Region, C.9), and the metric; or the account's Cost Explorer,
# budget, and anomaly reads (C.10). The map names no workspace in the ops account, so no account read stays
# on an ops role, and no W5 role exists in the management account (C.10.5).
#
# The ops boundary's ceiling is the ops roles' own statements, the chain's included. It denies sts:AssumeRole
# on every role but the named targets, every action on the state's lock files, and the rest of the
# never-list: the state's writes and its key's encrypt, the deletes, stops, and modifications on EC2, the
# security-group and route writes, and the changes to the budgets and the anomaly monitor the alarm path
# rides on. Each workload account's boundary has its target roles' reads as the ceiling and denies the
# never-list with sts:AssumeRole on every role, so every chain is two links and lasts an hour at most (C.8).
# The state bucket belongs to the platform's state stack, which owns its one bucket policy (C.12.3), so this
# configuration outputs the deny (writes and deletes by aws:PrincipalArn, C.5) for that stack to merge. The
# merge and the approving review are not IAM actions: they are what W5's GitHub Apps lack, and the plan stops
# with the reason if the catalog ever gives an App on the upstream a merge-capable permission.
#
# The identities, the actions, the Apps, and the ruleset come from catalog/tools.yaml and the workspaces and
# accounts from catalog/workspace-map.yaml, read with yamldecode, so the catalog is the one place that says
# what an identity may do; the tests read the same files. Validated with `terraform validate` and planned
# with placeholder credentials and account IDs through plan_offline.py (no request reaches AWS); never applied.

terraform {
  required_version = ">= 1.13.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0"
    }
  }
}

# The ops account: its roles, its boundary, and the Pod Identity associations of its cluster. The workload
# accounts' providers are in accounts.tf.
provider "aws" {
  region = var.region

  default_tags {
    tags = local.default_tags
  }
}
