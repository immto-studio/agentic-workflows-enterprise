# Two customer-managed keys. The workflow's key encrypts its Confidential stores whose encryption is
# fixed when they are created (the corpus bucket and the vector bucket) and its log groups. The tool
# gateway's signing key is the client credential it shows Entra: AgentCore Identity signs a JWT
# client assertion with it through kms:Sign, and the private key never leaves KMS.

data "aws_iam_policy_document" "workflow_key" {
  statement {
    sid       = "TheAccountAdministersIt"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${var.account_id}:root"]
    }
  }

  # CloudWatch Logs, for this account's log groups only.
  statement {
    sid = "CloudWatchLogs"
    actions = [
      "kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*",
    ]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.region}.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:*"]
    }
  }

  # S3 Vectors maintains an index in the background and needs to decrypt it (AWS's key policy).
  statement {
    sid       = "S3VectorsIndexing"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["indexing.s3vectors.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:s3vectors:${var.region}:${var.account_id}:bucket/*"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "ForAnyValue:StringEquals"
      variable = "kms:EncryptionContextKeys"
      values   = ["aws:s3vectors:arn", "aws:s3vectors:resource-id"]
    }
  }
}

resource "aws_kms_key" "workflow" {
  description         = "${local.workflow}: Confidential stores and logs"
  enable_key_rotation = true
  policy              = data.aws_iam_policy_document.workflow_key.json
  depends_on          = [aws_budgets_budget.account]
}

resource "aws_kms_alias" "workflow" {
  name          = "alias/${local.workflow}"
  target_key_id = aws_kms_key.workflow.key_id
}

# AWS's key policy for Private Key JWT: identities in this account may sign, through AgentCore
# Identity only. The tool gateway's role is the one whose policy names this key.
data "aws_iam_policy_document" "tool_gateway_signing" {
  statement {
    sid       = "TheAccountAdministersIt"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${var.account_id}:root"]
    }
  }
}

resource "aws_kms_key" "tool_gateway_signing" {
  description              = "${local.workflow}: the tool gateway's client credential for Entra"
  customer_master_key_spec = "RSA_2048"
  key_usage                = "SIGN_VERIFY"
  policy                   = data.aws_iam_policy_document.tool_gateway_signing.json
  depends_on               = [aws_budgets_budget.account]
}
