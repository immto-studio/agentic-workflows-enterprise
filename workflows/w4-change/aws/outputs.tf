output "agent_role_arns" {
  description = "agent -> the ARN of its role, bound to its service account through Pod Identity."
  value       = { for agent, role in aws_iam_role.agent : agent => role.arn }
}

output "trigger_role_arn" {
  description = "The role the pull-request job assumes through OIDC to send the trigger."
  value       = aws_iam_role.trigger.arn
}

output "trigger_queue_arn" {
  description = "The queue the trigger lands on; the scribe reads it."
  value       = aws_sqs_queue.trigger.arn
}

output "boundary_arn" {
  description = "The permission boundary every identity of the workflow carries."
  value       = aws_iam_policy.boundary.arn
}
