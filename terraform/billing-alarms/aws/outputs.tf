output "budget_name" {
  description = "Name of the AWS Budgets cost budget."
  value       = aws_budgets_budget.monthly.name
}

output "sns_topic_arn" {
  description = "ARN of the SNS topic the billing alarm publishes to."
  value       = aws_sns_topic.billing_alarm.arn
}

output "billing_alarm_name" {
  description = "Name of the CloudWatch alarm on AWS/Billing EstimatedCharges."
  value       = aws_cloudwatch_metric_alarm.estimated_charges.alarm_name
}
