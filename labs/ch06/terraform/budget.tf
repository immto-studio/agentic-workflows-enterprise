# The budget comes first (D-018): every other resource in this configuration depends on it, so the
# alarm exists before anything that can spend. Without an email address the budget still tracks the
# spend; a free-plan account's credits are its cap (book D-029).

locals {
  budget_alarms = [
    { threshold = 80, type = "ACTUAL" },
    { threshold = 100, type = "ACTUAL" },
    { threshold = 100, type = "FORECASTED" },
  ]
}

resource "aws_budgets_budget" "account" {
  name         = "${local.workflow}-account"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = var.budget_alert_email == "" ? [] : local.budget_alarms
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value.type
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }
}
