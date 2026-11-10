output "tool_role_arns" {
  description = "Each tool's role, which its server assumes for one request at a time."
  value       = { for tool, role in aws_iam_role.tool : tool => role.arn }
}

output "cedar_permits" {
  description = "The workflow identity's invoke scopes: one Cedar permit per tool, for the tool gateway's policy engine."
  value       = local.cedar_permits
}

output "never_actions" {
  description = "The AWS actions denied on every tool role, from the manifest's never-list."
  value       = local.never_actions
}
