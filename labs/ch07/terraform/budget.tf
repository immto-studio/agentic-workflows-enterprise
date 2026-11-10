# The budget comes first (D-018): after the two APIs it needs, every resource depends on it.

resource "google_monitoring_notification_channel" "budget" {
  display_name = "${var.workflow} budget alarm"
  type         = "email"
  labels = {
    email_address = var.budget_alert_email
  }
  depends_on = [google_project_service.budget_apis]
}

resource "google_billing_budget" "workflow" {
  billing_account = var.billing_account
  display_name    = "${var.workflow} on Agent Runtime"

  budget_filter {
    projects = ["projects/${var.project_number}"]
  }

  amount {
    specified_amount {
      units = tostring(var.monthly_budget)
    }
  }

  threshold_rules {
    threshold_percent = 0.8
  }

  threshold_rules {
    threshold_percent = 1.0
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.budget.id]
  }

  depends_on = [google_project_service.budget_apis]
}
