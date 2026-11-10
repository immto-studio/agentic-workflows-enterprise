locals {
  labels = {
    project = "agentic-workflows-enterprise"
    owner   = var.owner
  }

  # Fractions of the monthly limit; spend_basis selects actual or forecasted spend.
  threshold_rules = [
    { percent = 0.5, basis = "CURRENT_SPEND" },
    { percent = 0.8, basis = "CURRENT_SPEND" },
    { percent = 1.0, basis = "CURRENT_SPEND" },
    { percent = 1.0, basis = "FORECASTED_SPEND" },
  ]
}

# Kept enabled on destroy: other labs in the project may rely on them.
resource "google_project_service" "required" {
  for_each = toset([
    "billingbudgets.googleapis.com",
    "monitoring.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

data "google_project" "lab" {
  project_id = var.project_id
}

resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "${var.name_prefix}-email"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
  user_labels = local.labels

  depends_on = [google_project_service.required]
}

resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account
  display_name    = "${var.name_prefix}-monthly"

  budget_filter {
    projects = ["projects/${data.google_project.lab.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(floor(var.monthly_limit_usd))
      nanos         = floor((var.monthly_limit_usd - floor(var.monthly_limit_usd)) * 1e9)
    }
  }

  dynamic "threshold_rules" {
    for_each = local.threshold_rules
    content {
      threshold_percent = threshold_rules.value.percent
      spend_basis       = threshold_rules.value.basis
    }
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.email.id]
    # Billing account admins keep receiving the default emails as well.
    disable_default_iam_recipients = false
  }

  depends_on = [google_project_service.required]
}
