# Tags reach every resource through default_tags in versions.tf.
locals {
  tags = {
    project = "agentic-workflows-enterprise"
    owner   = var.owner
  }

  # Percent of the monthly limit at which AWS Budgets emails alert_email.
  actual_thresholds     = [50, 80, 100]
  forecasted_thresholds = [100]
}

resource "aws_budgets_budget" "monthly" {
  name         = "${var.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = local.actual_thresholds
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }

  dynamic "notification" {
    for_each = local.forecasted_thresholds
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "FORECASTED"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}

resource "aws_sns_topic" "billing_alarm" {
  name = "${var.name_prefix}-alarm"
}

resource "aws_sns_topic_subscription" "billing_alarm_email" {
  topic_arn = aws_sns_topic.billing_alarm.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Requires "Receive Billing Alerts" to be enabled once in the account's
# Billing preferences; until then the metric has no data.
resource "aws_cloudwatch_metric_alarm" "estimated_charges" {
  alarm_name          = "${var.name_prefix}-estimated-charges"
  alarm_description   = "Estimated month-to-date charges exceeded ${var.monthly_limit_usd} USD."
  namespace           = "AWS/Billing"
  metric_name         = "EstimatedCharges"
  dimensions          = { Currency = "USD" }
  statistic           = "Maximum"
  period              = 21600
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.monthly_limit_usd
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.billing_alarm.arn]
}
