# Model invocation logging in us-east-2, to CloudWatch Logs, as chapter 6's logging.tf has it: one setting
# per account and Region, text delivery off to start. The session turns text delivery on by API for its
# second logged call and records both shapes (O-D2, amended); the destroy deletes the configuration either
# way. The group keeps its records one day, the shortest retention CloudWatch offers.

resource "aws_cloudwatch_log_group" "invocations" {
  name              = "/aws/bedrock/model-invocations-ch16"
  retention_in_days = 1

  depends_on = [aws_budgets_budget.session]
}

data "aws_iam_policy_document" "invocation_logging_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "invocation_logging" {
  name               = "${var.name}-invocation-logging"
  description        = "Bedrock writes model invocation records to one log group"
  assume_role_policy = data.aws_iam_policy_document.invocation_logging_trust.json

  depends_on = [aws_budgets_budget.session]
}

data "aws_iam_policy_document" "invocation_logging" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.invocations.arn}:log-stream:*"]
  }
}

resource "aws_iam_role_policy" "invocation_logging" {
  name   = "write"
  role   = aws_iam_role.invocation_logging.id
  policy = data.aws_iam_policy_document.invocation_logging.json
}

resource "aws_bedrock_model_invocation_logging_configuration" "account" {
  logging_config {
    text_data_delivery_enabled      = false
    image_data_delivery_enabled     = false
    embedding_data_delivery_enabled = false
    video_data_delivery_enabled     = false

    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.invocations.name
      role_arn       = aws_iam_role.invocation_logging.arn
    }
  }

  depends_on = [aws_iam_role_policy.invocation_logging]
}
