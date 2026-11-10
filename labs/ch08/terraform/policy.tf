# Two deny policies, each assigned to one account. A change to either assignment is a change record.
#
# The agents' account: no model deployment at all, so the project endpoint's implicit model access
# stays empty.

resource "azurerm_policy_definition" "no_model_deployments" {
  name         = "deny-model-deployments-in-agent-accounts"
  policy_type  = "Custom"
  mode         = "All"
  display_name = "No model deployments in a Foundry account that hosts agents"

  policy_rule = jsonencode({
    if   = { field = "type", equals = "Microsoft.CognitiveServices/accounts/deployments" }
    then = { effect = "deny" }
  })

  depends_on = [azurerm_consumption_budget_resource_group.workflow]
}

resource "azurerm_resource_policy_assignment" "agents_account" {
  name                 = "no-model-deployments"
  resource_id          = azurerm_cognitive_account.agents.id
  policy_definition_id = azurerm_policy_definition.no_model_deployments.id
  display_name         = "No model deployments in ${azurerm_cognitive_account.agents.name}"
}

# The models account: the data-class grid as a structural control. The gateway refuses Global and
# Data Zone destinations; this policy refuses to create them, so no one with rights on the account
# can add one under a deployment name the gateway trusts. Standard and Regional Provisioned
# (ProvisionedManaged) are the types that process data in the region's geography. The rule is
# Microsoft's shape ("Restrict deployment types with Azure Policy" in Understanding deployment
# types in Microsoft Foundry Models, 2026-08-06), with notIn for the two allowed types and the deny
# effect, which Microsoft's sample leaves out.
resource "azurerm_policy_definition" "in_geography_deployments_only" {
  name         = "deny-deployments-outside-the-geography"
  policy_type  = "Custom"
  mode         = "All"
  display_name = "Only Standard and Regional Provisioned model deployments"

  policy_rule = jsonencode({
    if = {
      allOf = [
        { field = "type", equals = "Microsoft.CognitiveServices/accounts/deployments" },
        { field = "Microsoft.CognitiveServices/accounts/deployments/sku.name", notIn = ["Standard", "ProvisionedManaged"] },
      ]
    }
    then = { effect = "deny" }
  })

  depends_on = [azurerm_consumption_budget_resource_group.workflow]
}

resource "azurerm_resource_policy_assignment" "models_account" {
  name                 = "in-geography-deployments-only"
  resource_id          = azurerm_cognitive_account.models.id
  policy_definition_id = azurerm_policy_definition.in_geography_deployments_only.id
  display_name         = "Only Standard and Regional Provisioned deployments in ${azurerm_cognitive_account.models.name}"
}
