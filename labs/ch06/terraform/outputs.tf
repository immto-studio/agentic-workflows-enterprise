output "runtime_arn" {
  description = "What the Teams bot invokes, with the endpoint named below as its qualifier and an engineer's Entra token."
  value       = aws_bedrockagentcore_agent_runtime.harness.agent_runtime_arn
}

output "runtime_endpoint" {
  description = "The named endpoint the bot calls; the pipeline moves it to a new version."
  value       = aws_bedrockagentcore_agent_runtime_endpoint.live.name
}

output "tool_gateway_signing_key_arn" {
  description = "Make the certificate the tool gateway's Entra app holds from this key's public key."
  value       = aws_kms_key.tool_gateway_signing.arn
}

output "tool_gateway_targets" {
  description = "The targets the pipeline registers Larkspur's root CA on after an apply."
  value       = { for name, target in aws_bedrockagentcore_gateway_target.mcp : name => target.target_id }
}

output "tool_gateway_url" {
  description = "The MCP endpoint the harness calls, signed with its execution role."
  value       = aws_bedrockagentcore_gateway.tools.gateway_url
}

output "tool_role_arns" {
  description = "The roles the tool servers assume for one request at a time."
  value       = module.workflow_identities.tool_role_arns
}

output "knowledge_base_id" {
  description = "The runbook knowledge base; ingestion starts with StartIngestionJob after the corpus is in S3."
  value       = aws_bedrockagent_knowledge_base.runbooks.id
}

output "guardrail" {
  description = "What the model gateway's guardrail entry names: guardrailIdentifier and guardrailVersion."
  value = {
    identifier = aws_bedrock_guardrail.workflow.guardrail_id
    version    = aws_bedrock_guardrail_version.workflow.version
  }
}
