output "agent" {
  description = "The agent's resource name; its principal changes whenever the agent is replaced."
  value       = google_vertex_ai_reasoning_engine.harness.id
}

output "agent_identity" {
  description = "The identity Google reports for the agent; the pipeline lists its roles after every apply."
  value       = google_vertex_ai_reasoning_engine.harness.spec[0].effective_identity
}

output "egress_gateway" {
  description = "The gateway whose CA certificate goes into the harness image."
  value       = google_network_services_agent_gateway.egress.id
}

output "essential_endpoints" {
  description = "Registered and granted to the agent's principal beside the manifest's destinations."
  value       = local.essential_endpoints
}
