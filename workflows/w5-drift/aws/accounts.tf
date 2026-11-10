# The workload accounts the cloud and cost readers read (catalog/workspace-map.yaml): a provider and a module
# call for each, the module making that account's two target roles, their reads, and their boundary
# (workload-account/). Terraform has no provider per map entry, so each account is written out here, and
# the precondition in main.tf refuses the plan when the map names an account with no module call here or no
# service accounts in the catalog, or when a module call or a service account serves an account the map
# does not name.
#
# The offline plan gives every provider placeholder credentials and no assume_role block (plan_offline.py).
# A real apply gives each of these providers its own account's deployment credentials, which create the
# target roles there, and the default provider the ops account's, which create the ops roles and the Pod
# Identity associations.

provider "aws" {
  alias  = "lm_network_prod"
  region = var.region

  default_tags {
    tags = local.default_tags
  }
}

provider "aws" {
  alias  = "lm_claims_prod"
  region = var.region

  default_tags {
    tags = local.default_tags
  }
}

provider "aws" {
  alias  = "lm_sandbox"
  region = var.region

  default_tags {
    tags = local.default_tags
  }
}

module "lm_network_prod" {
  source    = "./workload-account"
  providers = { aws = aws.lm_network_prod }

  account         = "lm-network-prod"
  readers         = local.target_readers
  ops_account_id  = var.account_id
  organization_id = var.organization_id
  cluster_arn     = local.cluster_arn
  never_actions   = local.never_actions
  workflow        = local.workflow
}

module "lm_claims_prod" {
  source    = "./workload-account"
  providers = { aws = aws.lm_claims_prod }

  account         = "lm-claims-prod"
  readers         = local.target_readers
  ops_account_id  = var.account_id
  organization_id = var.organization_id
  cluster_arn     = local.cluster_arn
  never_actions   = local.never_actions
  workflow        = local.workflow
}

module "lm_sandbox" {
  source    = "./workload-account"
  providers = { aws = aws.lm_sandbox }

  account         = "lm-sandbox"
  readers         = local.target_readers
  ops_account_id  = var.account_id
  organization_id = var.organization_id
  cluster_arn     = local.cluster_arn
  never_actions   = local.never_actions
  workflow        = local.workflow
}

locals {
  # The module calls above, one per workload account; main.tf reads the accounts and their target roles
  # from here, so an account written out above and not in the map, or in the map and not above, stops the plan.
  account_modules = [module.lm_network_prod, module.lm_claims_prod, module.lm_sandbox]
  target_accounts = { for m in local.account_modules : m.account => m.target_roles }
}
