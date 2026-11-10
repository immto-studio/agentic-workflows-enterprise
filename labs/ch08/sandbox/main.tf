# Stand-ins for what chapter 8's lab takes from Larkspur's platform, for a sandbox subscription's first
# apply (book D-037). None of this is Larkspur's design: the network that network security owns (a
# virtual network with the agents' delegated subnet and the private endpoints' subnet, the four
# private DNS zones linked to it), the managed identity the LiteLLM pods would run as, and a root CA
# made for the sandbox, valid for two days, which the image build bakes in.
#
# `terraform destroy` removes all of it, after the lab's own destroy.

terraform {
  required_version = ">= 1.13.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "5.11.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "4.4.2"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id     = var.subscription_id
  storage_use_azuread = true
}

variable "subscription_id" {
  description = "The sandbox subscription."
  type        = string
}

variable "location" {
  description = "Where the network lives: the lab's agents' account region."
  type        = string
  default     = "canadacentral"
}

variable "name" {
  description = "The prefix of every name here."
  type        = string
  default     = "ch08-sandbox"
}

locals {
  tags = { purpose = "ch08-lab-sandbox", data = "synthetic" }
  zones = [
    "privatelink.cognitiveservices.azure.com",
    "privatelink.openai.azure.com",
    "privatelink.services.ai.azure.com",
    "privatelink.azurecr.io",
  ]
}

resource "azurerm_resource_group" "sandbox" {
  name     = "rg-${var.name}"
  location = var.location
  tags     = local.tags
}

# --- network -------------------------------------------------------------------------------------

resource "azurerm_virtual_network" "lab" {
  name                = "vnet-${var.name}"
  location            = var.location
  resource_group_name = azurerm_resource_group.sandbox.name
  address_space       = ["10.42.0.0/16"]
  tags                = local.tags
}

# The agents' subnet: delegated to Container Apps environments, as injection requires; a /27 holds
# about twenty sessions, enough for a sandbox and, in Microsoft's words, not for production.
resource "azurerm_subnet" "agents" {
  name                 = "snet-agents"
  resource_group_name  = azurerm_resource_group.sandbox.name
  virtual_network_name = azurerm_virtual_network.lab.name
  address_prefixes     = ["10.42.1.0/27"]

  delegation {
    name = "foundry-agents"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                 = "snet-private-endpoints"
  resource_group_name  = azurerm_resource_group.sandbox.name
  virtual_network_name = azurerm_virtual_network.lab.name
  address_prefixes     = ["10.42.2.0/27"]
}

resource "azurerm_private_dns_zone" "zone" {
  for_each            = toset(local.zones)
  name                = each.key
  resource_group_name = azurerm_resource_group.sandbox.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "zone" {
  for_each            = azurerm_private_dns_zone.zone
  name                = "link-${var.name}"
  private_dns_zone_id = each.value.id
  virtual_network_id  = azurerm_virtual_network.lab.id
  tags                = local.tags
}

# --- the model gateway's identity ----------------------------------------------------------------

# In Larkspur's platform the LiteLLM pods on AKS run as this identity; here nothing runs as it, and
# the lab's role assignment names it.
resource "azurerm_user_assigned_identity" "gateway" {
  name                = "id-${var.name}-gateway"
  location            = var.location
  resource_group_name = azurerm_resource_group.sandbox.name
  tags                = local.tags
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

# --- what the lab's lab.tfvars takes from here (sandbox.py writes it) ----------------------------

output "lab" {
  description = "The stand-ins' identifiers, for the lab's variables."
  value = {
    agent_subnet_id            = azurerm_subnet.agents.id
    private_endpoint_subnet_id = azurerm_subnet.private_endpoints.id
    private_dns_zone_ids       = [for z in local.zones : azurerm_private_dns_zone.zone[z].id if z != "privatelink.azurecr.io"]
    registry_dns_zone_id       = azurerm_private_dns_zone.zone["privatelink.azurecr.io"].id
    gateway_principal_id       = azurerm_user_assigned_identity.gateway.principal_id
    resource_group             = azurerm_resource_group.sandbox.name
    location                   = var.location
  }
}

output "root_ca_pem" {
  description = "The sandbox root's certificate (public), which the image build bakes in."
  value       = tls_self_signed_cert.root.cert_pem
}
