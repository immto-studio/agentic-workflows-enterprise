# The agents' Foundry account and the workflow's project. The account holds no model
# deployments: a hosted agent may call models through its project endpoint without any role
# assignment, so the account it lives in gets nothing to call (policy.tf keeps it that way).

resource "azurerm_user_assigned_identity" "project" {
  name                = "id-${var.workflow}-project"
  location            = var.location
  resource_group_name = azurerm_resource_group.workflow.name
  tags                = local.tags
  depends_on          = [azurerm_consumption_budget_resource_group.workflow]
}

resource "azurerm_cognitive_account" "agents" {
  name                          = "fdy-${var.workflow}-${var.name_suffix}"
  location                      = var.location
  resource_group_name           = azurerm_resource_group.workflow.name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = "fdy-${var.workflow}-${var.name_suffix}"
  project_management_enabled    = true
  local_auth_enabled            = false # Entra only; no keys
  public_network_access_enabled = false
  tags                          = local.tags

  # Chosen at creation: it can't be added to an existing account, and hosted agents need it.
  network_injection {
    scenario  = "agent"
    subnet_id = var.agent_subnet_id
  }

  identity {
    type = "SystemAssigned"
  }

  depends_on = [azurerm_consumption_budget_resource_group.workflow]

  # Replacing the account takes every project, agent and identity in it, and a new name, location,
  # kind or subdomain would plan exactly that, so Terraform refuses any plan that destroys it. A
  # sandbox teardown lifts the guard first (README, Part 1).
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_cognitive_account_project" "workflow" {
  name                 = var.workflow
  cognitive_account_id = azurerm_cognitive_account.agents.id
  location             = var.location
  display_name         = var.workflow
  tags                 = local.tags

  # User-assigned, and only at creation: the identity type can't be changed afterwards.
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.project.id]
  }

  depends_on = [azurerm_consumption_budget_resource_group.workflow]

  # Replacing the project takes every agent in it, and a new name, location or account would plan
  # that; the same guard as the account's.
  lifecycle {
    prevent_destroy = true
  }
}

# Images come from a private registry, which hosted agents support for projects created after
# 25 June 2026; the project's identity pulls them.
resource "azurerm_container_registry" "agents" {
  name                          = "acr${replace(var.workflow, "-", "")}${var.name_suffix}"
  location                      = var.location
  resource_group_name           = azurerm_resource_group.workflow.name
  sku                           = "Premium"
  admin_enabled                 = false
  public_network_access_enabled = false
  tags                          = local.tags

  # Foundry pulls with Entra tokens scoped to Azure Resource Manager: "The registry's
  # azureADAuthenticationAsArmPolicy policy status must be set to enabled" (Hosted agent permissions
  # reference, 2026-04-21). azurerm 5.11.0 defaults to true; the file states it and a test checks
  # it, so the requirement shows where the registry is defined. Microsoft's built-in policy
  # "Container registries should have ARM audience token authentication disabled" asks for the
  # opposite, so a registry for hosted agents needs an exemption from that policy wherever it is
  # assigned.
  azuread_authentication_as_arm_policy_enabled = true

  # Microsoft's roles reference for the registry lists Container Registry Repository Reader, the
  # pull role below, for registries in this mode, and AcrPull for the default one (Azure Container
  # Registry roles directory reference, 2025-04-24), so the mode goes with the role.
  role_assignment_mode = "AbacRepositoryPermissions"

  depends_on = [azurerm_consumption_budget_resource_group.workflow]
}

# Roles by ID, which a rename can't break, scoped to the subscription as azurerm 5.11.0's acceptance
# test for a built-in role writes them (a change to the ID replaces the assignment).
# b93aa761-3e63-49ed-ac28-beffa264f7ac is Container Registry Repository Reader (Azure built-in roles
# for Containers, learn.microsoft.com, 2026-07-01), the pull role Microsoft's hosted agent
# permissions reference recommends for the project's identity.
resource "azurerm_role_assignment" "project_pulls_images" {
  scope              = azurerm_container_registry.agents.id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/b93aa761-3e63-49ed-ac28-beffa264f7ac"
  principal_id       = azurerm_user_assigned_identity.project.principal_id
  depends_on         = [azurerm_consumption_budget_resource_group.workflow]
}
