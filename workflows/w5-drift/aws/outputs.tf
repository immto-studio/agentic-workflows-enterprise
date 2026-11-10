output "role_arns" {
  description = "identity -> the ARN of its role in the ops account, bound to its service accounts through Pod Identity."
  value       = { for name, role in aws_iam_role.identity : name => role.arn }
}

output "target_role_arns" {
  description = "reader -> workload account -> the ARN of its target role there, the second link of the chain."
  value       = local.target_role_arns
}

output "service_accounts" {
  description = "namespace/service account -> the role in the ops account it is bound to, and the target role chained to it (null for none)."
  value = { for sa, binding in local.bindings : "${binding.namespace}/${sa}" => {
    role_arn        = local.role_arns[binding.identity]
    target_role_arn = binding.target_role_arn
  } }
}

output "boundary_arn" {
  description = "The permission boundary every W5 role in the ops account carries."
  value       = aws_iam_policy.boundary.arn
}

output "target_boundary_arns" {
  description = "workload account -> the permission boundary its target roles carry."
  value       = { for m in local.account_modules : m.account => m.boundary_arn }
}

output "state_bucket_deny_policy" {
  description = "The state bucket's deny of the object writes and deletes to every W5 role, by aws:PrincipalArn: a policy document the platform's state stack merges into the bucket's one policy."
  value       = data.aws_iam_policy_document.state_bucket_deny.json
}
