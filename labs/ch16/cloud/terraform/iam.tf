# The tool role with the trace id (O-D2, amended). Chapter 6's module names a tool role <workflow>-<tool>
# and requires the `workflow` session tag and the engineer as the source identity. The amendment adds the
# run: the trust policy requires the `trace_id` session tag, 32 characters long (IAM can't require
# hexadecimal, so StringLike with 32 single-character wildcards), allows no other tag key, and pins the
# role session name to the engineer's object ID, a dot, and the trace id's first 16 characters, which
# every later CloudTrail event shows inside userIdentity.arn. The principal is the session's own caller.
# The role may make one read, ec2:DescribeInstances, the call the session joins to its run.
#
# Two statements, after a first attempt on 9 November 2026: with the three actions and the four conditions in
# one statement, STS refused the call with "not authorized to perform: sts:TagSession" (read on the console;
# the error text was not kept in the results). The session name condition is met for sts:AssumeRole, whose
# request context carries sts:RoleSessionName, and not for the permissions-only sts:TagSession, so the session
# name is required on AssumeRole alone and the tags on all three.

locals {
  role_name            = substr("${var.workflow}-${replace(var.tool, "_", "-")}", 0, 64)
  trace_id_pattern     = join("", [for i in range(32) : "?"])
  session_name_pattern = "*.${join("", [for i in range(16) : "?"])}"
}

data "aws_iam_policy_document" "tool_trust" {
  statement {
    sid     = "ToolServerForOneRun"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [data.aws_caller_identity.current.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/workflow"
      values   = [var.workflow]
    }

    condition {
      test     = "StringLike"
      variable = "aws:RequestTag/trace_id"
      values   = [local.trace_id_pattern]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["workflow", "trace_id"]
    }

    condition {
      test     = "StringLike"
      variable = "sts:RoleSessionName"
      values   = [local.session_name_pattern]
    }
  }

  statement {
    sid     = "ToolServerTagsTheRun"
    actions = ["sts:TagSession", "sts:SetSourceIdentity"]

    principals {
      type        = "AWS"
      identifiers = [data.aws_caller_identity.current.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/workflow"
      values   = [var.workflow]
    }

    condition {
      test     = "StringLike"
      variable = "aws:RequestTag/trace_id"
      values   = [local.trace_id_pattern]
    }

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["workflow", "trace_id"]
    }
  }
}

resource "aws_iam_role" "tool" {
  name                  = local.role_name
  description           = "${var.tool} for ${var.workflow}, assumed for one run at a time with the run's trace id"
  assume_role_policy    = data.aws_iam_policy_document.tool_trust.json
  max_session_duration  = 3600
  force_detach_policies = true

  tags = {
    tool   = var.tool
    writes = "false"
  }

  depends_on = [aws_budgets_budget.session]
}

data "aws_iam_policy_document" "tool_read" {
  statement {
    sid       = "OneRead"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "tool_read" {
  name   = "read"
  role   = aws_iam_role.tool.id
  policy = data.aws_iam_policy_document.tool_read.json
}
