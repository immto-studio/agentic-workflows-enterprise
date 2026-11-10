# Traces from the hosted agent land in Application Insights; both accounts' resource logs go to the
# same workspace. Larkspur's collector exports them to its own backend.

resource "azurerm_log_analytics_workspace" "workflow" {
  name                = "log-${var.workflow}"
  location            = var.location
  resource_group_name = azurerm_resource_group.workflow.name
  sku                 = "PerGB2018"
  retention_in_days   = 90
  tags                = local.tags
  depends_on          = [azurerm_consumption_budget_resource_group.workflow]
}

resource "azurerm_application_insights" "workflow" {
  name                = "appi-${var.workflow}"
  location            = var.location
  resource_group_name = azurerm_resource_group.workflow.name
  workspace_id        = azurerm_log_analytics_workspace.workflow.id
  application_type    = "other"
  tags                = local.tags
  depends_on          = [azurerm_consumption_budget_resource_group.workflow]
}

resource "azurerm_monitor_diagnostic_setting" "models" {
  name                       = "models-to-workspace"
  target_resource_id         = azurerm_cognitive_account.models.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.workflow.id

  enabled_log {
    category = "Audit"
  }

  enabled_log {
    category = "RequestResponse"
  }

  enabled_log {
    category = "AzureOpenAIRequestUsage"
  }
}

# The agents' account, in the two categories Microsoft's diagnostic logging guide selects (Enable
# diagnostic logging, Foundry Tools, 2025-10-02). Resource logs capture an account's data-plane
# operations, and creating an agent version is one ("Hosted agent deployment operations are data
# plane operations", Hosted agent permissions reference); Microsoft's monitoring reference lists the
# categories without saying what each records. Creating a connection or a guardrail (RAI) policy is
# a Resource Manager write, which the subscription's activity log records. This setting doesn't
# collect that log; a diagnostic setting on the subscription sends it to a workspace.
resource "azurerm_monitor_diagnostic_setting" "agents" {
  name                       = "agents-to-workspace"
  target_resource_id         = azurerm_cognitive_account.agents.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.workflow.id

  enabled_log {
    category = "Audit"
  }

  enabled_log {
    category = "RequestResponse"
  }
}
