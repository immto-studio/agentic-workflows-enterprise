# The guardrail the model gateway attaches to this workflow's calls. The Standard tier needs a
# guardrail profile; Larkspur's, the Canada profile, keeps its evaluation in ca-central-1 and
# ca-west-1. A lab run elsewhere takes its own Region's geography.
# Detect mode for the first month (chapter 4): every filter's action is NONE. The model gateway calls
# it with ApplyGuardrail before and after each model call on the managed aliases, never on the
# self-hosted one, and writes each verdict on its log line, which the collector carries to security
# engineering's queue. Invocation logging doesn't record ApplyGuardrail.

locals {
  guardrail_action = var.guardrail_mode == "block" ? "BLOCK" : "NONE"
  content_filters  = ["HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT"]

  # The guardrail profile for the Region's geography, by the Region's first part.
  guardrail_geography = { ca = "ca", us = "us", eu = "eu", ap = "apac" }
  guardrail_profile   = "${local.guardrail_geography[split("-", var.region)[0]]}.guardrail.v1:0"
}

resource "aws_bedrock_guardrail" "workflow" {
  name                      = "${local.workflow}-guardrail"
  description               = "Prompt attacks, harmful content and secrets in ${local.workflow}'s model calls"
  blocked_input_messaging   = "The platform's guardrail stopped this request. The reference is in the audit log."
  blocked_outputs_messaging = "The platform's guardrail stopped this answer. The reference is in the audit log."

  cross_region_config {
    guardrail_profile_identifier = "arn:aws:bedrock:${var.region}:${var.account_id}:guardrail-profile/${local.guardrail_profile}"
  }

  content_policy_config {
    tier_config {
      tier_name = "STANDARD"
    }

    # Input only. Through ApplyGuardrail the gateway sends the text of every message, so tool results
    # are screened too; AWS's note that they aren't is about the Converse API.
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
      input_action    = local.guardrail_action
    }

    dynamic "filters_config" {
      for_each = local.content_filters
      content {
        type            = filters_config.value
        input_strength  = "MEDIUM"
        output_strength = "MEDIUM"
        input_action    = local.guardrail_action
        output_action   = local.guardrail_action
      }
    }
  }

  sensitive_information_policy_config {
    pii_entities_config {
      type   = "AWS_SECRET_KEY"
      action = local.guardrail_action == "BLOCK" ? "BLOCK" : "NONE"
    }
    pii_entities_config {
      type   = "CA_SOCIAL_INSURANCE_NUMBER"
      action = local.guardrail_action == "BLOCK" ? "BLOCK" : "NONE"
    }
    pii_entities_config {
      type   = "CREDIT_DEBIT_CARD_NUMBER"
      action = local.guardrail_action == "BLOCK" ? "BLOCK" : "NONE"
    }
  }

  depends_on = [aws_budgets_budget.account]
}

# The gateway names a version, never DRAFT, so a change to the guardrail is a new version.
resource "aws_bedrock_guardrail_version" "workflow" {
  guardrail_arn = aws_bedrock_guardrail.workflow.guardrail_arn
  description   = "${var.guardrail_mode} mode"
  skip_destroy  = true
}
