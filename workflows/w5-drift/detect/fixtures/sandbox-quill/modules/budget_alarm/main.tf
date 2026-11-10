# module.budget_alarm of the sandbox-quill fixture: the corpus's aws-budget-alarm module (v1.2.4) as the
# state describes its one resource, a monthly budget with 50, 80, and 100 percent alerts.

resource "aws_budgets_budget" "monthly" {
  name              = "lm-sandbox-monthly"
  budget_type       = "COST"
  limit_amount      = "1500.0"
  limit_unit        = "LCU"
  time_unit         = "MONTHLY"
  time_period_start = "2026-01-01_00:00"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["finops@larkspur-mutual.example"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["finops@larkspur-mutual.example"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = ["finops@larkspur-mutual.example"]
  }

  tags = {
    owner_team          = "quill-data"
    cost_center         = "CC-9901"
    env                 = "sandbox"
    service             = "quill-batch"
    data_classification = "internal"
  }
}

output "budget_id" {
  value = aws_budgets_budget.monthly.id
}
