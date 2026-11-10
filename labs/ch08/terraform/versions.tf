# Chapter 8 lab: the skeleton's harness as a Foundry hosted agent, for the commercial-lines team.
# Validated with `terraform validate`; not applied, because the lab has no Azure subscription yet.

terraform {
  required_version = ">= 1.13.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "5.11.0"
    }
  }
}

provider "azurerm" {
  features {
    cognitive_account {
      purge_soft_delete_on_destroy = true # the provider's default, stated: destroy frees the names
    }
  }
  subscription_id     = var.subscription_id
  storage_use_azuread = true
}
