# Private endpoints for both accounts and the registry; network security owns the subnets and
# the private DNS zones. Microsoft doesn't create the endpoints for you.

resource "azurerm_private_endpoint" "agents" {
  name                = "pe-${azurerm_cognitive_account.agents.name}"
  location            = var.location
  resource_group_name = azurerm_resource_group.workflow.name
  subnet_id           = var.private_endpoint_subnet_id
  tags                = local.tags

  private_service_connection {
    name                           = "account"
    private_connection_resource_id = azurerm_cognitive_account.agents.id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "foundry"
    private_dns_zone_ids = var.private_dns_zone_ids
  }

  depends_on = [azurerm_consumption_budget_resource_group.workflow]
}

resource "azurerm_private_endpoint" "models" {
  name                = "pe-${azurerm_cognitive_account.models.name}"
  location            = var.location
  resource_group_name = azurerm_resource_group.workflow.name
  subnet_id           = var.private_endpoint_subnet_id
  tags                = local.tags

  private_service_connection {
    name                           = "account"
    private_connection_resource_id = azurerm_cognitive_account.models.id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "foundry"
    private_dns_zone_ids = var.private_dns_zone_ids
  }

  depends_on = [azurerm_consumption_budget_resource_group.workflow]
}

resource "azurerm_private_endpoint" "registry" {
  name                = "pe-${azurerm_container_registry.agents.name}"
  location            = var.location
  resource_group_name = azurerm_resource_group.workflow.name
  subnet_id           = var.private_endpoint_subnet_id
  tags                = local.tags

  private_service_connection {
    name                           = "registry"
    private_connection_resource_id = azurerm_container_registry.agents.id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "registry"
    private_dns_zone_ids = [var.registry_dns_zone_id]
  }

  depends_on = [azurerm_consumption_budget_resource_group.workflow]
}
