output "account" {
  description = "The account's name in the workspace map, so the root can check the map against the module calls."
  value       = var.account
}

output "target_roles" {
  description = "reader -> the name of its target role in this account."
  value       = { for name, reader in var.readers : name => reader.role }
}

output "role_arns" {
  description = "reader -> the ARN of its target role in this account."
  value       = { for name, role in aws_iam_role.target : name => role.arn }
}

output "boundary_arn" {
  description = "The permission boundary the target roles in this account carry."
  value       = aws_iam_policy.boundary.arn
}
