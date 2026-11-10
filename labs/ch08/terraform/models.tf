# The models: a separate Foundry account in Canada East, called only by the model gateway.

resource "azurerm_cognitive_account" "models" {
  name                          = "fdy-models-${var.name_suffix}"
  location                      = var.model_location
  resource_group_name           = azurerm_resource_group.workflow.name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = "fdy-models-${var.name_suffix}"
  local_auth_enabled            = false
  public_network_access_enabled = false
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }

  depends_on = [azurerm_consumption_budget_resource_group.workflow]
}

# A Standard deployment processes data in the region's geography; Global and Data Zone
# deployments don't, and no data zone includes Canada. policy.tf refuses any other deployment type
# in this account.
resource "azurerm_cognitive_deployment" "chat" {
  name                 = "larkspur-chat"
  cognitive_account_id = azurerm_cognitive_account.models.id
  rai_policy_name      = "Microsoft.DefaultV2"

  # A model change goes through the golden set first, so the deployment never upgrades itself.
  # NoAutoUpgrade means "never auto-upgrade—deployment stops working at retirement" (Foundry
  # Models lifecycle and support policy, 2026-07-24): on the retirement date in ../models.yaml the
  # alias returns errors unless it has moved, and a test fails 90 days before that. The alternative,
  # OnceCurrentVersionExpired, swaps in Microsoft's replacement at retirement, before any golden set
  # has run against it.
  version_upgrade_option = "NoAutoUpgrade"

  model {
    format  = "OpenAI"
    name    = var.chat_model.name
    version = var.chat_model.version
  }

  sku {
    name     = "Standard"
    capacity = var.chat_capacity
  }

  depends_on = [azurerm_consumption_budget_resource_group.workflow]
}

# By ID, in the form foundry.tf explains. 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd is Cognitive Services
# OpenAI User (Azure built-in roles for AI + machine learning, learn.microsoft.com, 2026-07-01).
resource "azurerm_role_assignment" "gateway_calls_models" {
  scope              = azurerm_cognitive_account.models.id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
  principal_id       = var.gateway_principal_id
  depends_on         = [azurerm_consumption_budget_resource_group.workflow]
}
