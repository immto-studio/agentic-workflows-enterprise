output "runtime_role_arn" {
  description = "The writer server's base role, bound to its service account through Pod Identity."
  value       = aws_iam_role.runtime.arn
}

output "write_role_arns" {
  description = "tool -> the ARN of the role the runtime assumes for that write."
  value       = { for tool, role in aws_iam_role.write : tool => role.arn }
}

output "boundary_arn" {
  description = "The permission boundary every write role carries."
  value       = aws_iam_policy.write_boundary.arn
}

output "access_entries" {
  description = "tool -> the Kubernetes group its access entry maps to; the custom Role is bound to it in the namespace."
  value       = { for tool, entry in aws_eks_access_entry.write : tool => entry.kubernetes_groups }
}
