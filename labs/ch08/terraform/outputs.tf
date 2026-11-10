output "project_id" {
  description = "The Foundry project the pipeline deploys agent versions into."
  value       = azurerm_cognitive_account_project.workflow.id
}

output "project_identity" {
  description = "The project's managed identity: it pulls images; Foundry gives each agent an identity of its own."
  value       = azurerm_user_assigned_identity.project.principal_id
}

output "registry_id" {
  description = "The registry the pipeline pushes the harness image to."
  value       = azurerm_container_registry.agents.id
}

output "models_endpoint" {
  description = "The model gateway's backend for the Canadian alias."
  value       = azurerm_cognitive_account.models.endpoint
}
