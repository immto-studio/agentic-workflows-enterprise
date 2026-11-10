output "role_arns" {
  description = "server name -> the ARN of the role its pods assume."
  value       = { for name, role in aws_iam_role.server : name => role.arn }
}

output "actions" {
  description = "server name -> the read actions its role holds, from the catalog."
  value       = local.actions
}

output "boundary_arn" {
  description = "The permission boundary every server role carries."
  value       = aws_iam_policy.read_boundary.arn
}

output "service_accounts" {
  description = "server name -> namespace/service-account the role is associated with."
  value       = { for name, assoc in aws_eks_pod_identity_association.server : name => "${assoc.namespace}/${assoc.service_account}" }
}
