# The budget first (book D-018, D-029; chapter 6's budget.tf): a monthly cost budget with an SNS topic in
# us-east-2 as its subscriber, and no email address anywhere. Every other resource in this configuration
# depends on it, so the guard exists before anything that can spend. AWS Budgets publishes to the topic
# only when the topic's policy lets the service publish.

resource "aws_sns_topic" "budget" {
  name = "${var.name}-budget"
}

data "aws_iam_policy_document" "budget_topic" {
  statement {
    sid       = "BudgetsPublish"
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.budget.arn]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "budget" {
  arn    = aws_sns_topic.budget.arn
  policy = data.aws_iam_policy_document.budget_topic.json
}

locals {
  budget_alarms = [80, 100]
}

resource "aws_budgets_budget" "session" {
  name         = "${var.name}-session"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = local.budget_alarms
    content {
      comparison_operator       = "GREATER_THAN"
      threshold                 = notification.value
      threshold_type            = "PERCENTAGE"
      notification_type         = "ACTUAL"
      subscriber_sns_topic_arns = [aws_sns_topic.budget.arn]
    }
  }

  depends_on = [aws_sns_topic_policy.budget]
}
