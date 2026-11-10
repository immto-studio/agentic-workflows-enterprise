# Names and resource IDs the session's scripts read back; no ARN, since an ARN carries the account ID.

output "budget_name" {
  value = aws_budgets_budget.session.name
}

output "budget_topic_name" {
  value = aws_sns_topic.budget.name
}

output "vpc_id" {
  value = aws_vpc.lab.id
}

output "subnet_id" {
  value = aws_subnet.public.id
}

output "security_group_ids" {
  value = { vm = aws_security_group.vm.id, endpoint = aws_security_group.endpoint.id }
}

output "instance_connect_endpoint_id" {
  value = aws_ec2_instance_connect_endpoint.lab.id
}

output "instance_id" {
  value = aws_instance.langfuse.id
}

output "instance_type" {
  value = aws_instance.langfuse.instance_type
}

output "availability_zone" {
  value = aws_instance.langfuse.availability_zone
}

output "ami_id" {
  value = aws_instance.langfuse.ami
}

output "tool_role_name" {
  value = aws_iam_role.tool.name
}

output "invocation_log_group" {
  value = aws_cloudwatch_log_group.invocations.name
}

output "invocation_logging_role_name" {
  value = aws_iam_role.invocation_logging.name
}
