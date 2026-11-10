locals {
  tags = {
    project = "agentic-workflows-enterprise"
    owner   = var.owner
  }

  start_date = coalesce(var.budget_start_date, formatdate("YYYY-MM-01'T'00:00:00Z", timestamp()))

  # Percent of the monthly limit; threshold_type selects actual or forecasted cost.
  notifications = [
    { threshold = 50, type = "Actual" },
    { threshold = 80, type = "Actual" },
    { threshold = 100, type = "Actual" },
    { threshold = 100, type = "Forecasted" },
  ]
}

resource "azurerm_resource_group" "billing" {
  name     = "${var.name_prefix}-rg"
  location = var.location
  tags     = local.tags
}

resource "azurerm_monitor_action_group" "billing" {
  name                = "${var.name_prefix}-ag"
  resource_group_name = azurerm_resource_group.billing.name
  short_name          = "labbilling"
  tags                = local.tags

  email_receiver {
    name                    = "alert-email"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }
}

resource "azurerm_consumption_budget_subscription" "monthly" {
  name            = "${var.name_prefix}-monthly"
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = var.monthly_limit_usd
  time_grain      = "Monthly"

  time_period {
    start_date = local.start_date
  }

  dynamic "notification" {
    for_each = local.notifications
    content {
      enabled        = true
      threshold      = notification.value.threshold
      threshold_type = notification.value.type
      operator       = "GreaterThan"
      contact_groups = [azurerm_monitor_action_group.billing.id]
    }
  }

  # timestamp() changes on every run; the start date only matters at creation.
  lifecycle {
    ignore_changes = [time_period]
  }
}
