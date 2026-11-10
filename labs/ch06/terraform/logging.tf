# Model invocation logging, which AWS leaves off by default. It is one setting per account and
# Region, so in a shared account the platform's baseline owns it; the lab account has one workflow.
# Text delivery follows the manifest's trace_content: the incident workflow's is false, so the
# records hold who called which model with how many tokens, and no prompts or answers.

resource "aws_cloudwatch_log_group" "invocations" {
  name              = "/aws/bedrock/model-invocations"
  retention_in_days = 400
  kms_key_id        = aws_kms_key.workflow.arn
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
      values   = [var.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock:${var.region}:${var.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "invocation_logging" {
  name               = "${local.workflow}-invocation-logging"
  description        = "Bedrock writes model invocation records to one log group"
  assume_role_policy = data.aws_iam_policy_document.invocation_logging_trust.json
  depends_on         = [aws_budgets_budget.account]
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
    text_data_delivery_enabled      = local.manifest.trace_content
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
