output "budget_id" {
  description = "Resource ID of the subscription consumption budget."
  value       = azurerm_consumption_budget_subscription.monthly.id
}

output "action_group_id" {
  description = "Resource ID of the action group that emails alert_email."
  value       = azurerm_monitor_action_group.billing.id
}

output "resource_group_name" {
  description = "Resource group holding the action group."
  value       = azurerm_resource_group.billing.name
}
