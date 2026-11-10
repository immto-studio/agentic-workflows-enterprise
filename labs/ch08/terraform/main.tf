# The budget comes first (D-018): after the resource group it watches, every resource depends on it.

locals {
  tags = { workflow = var.workflow, owner = var.owner }
}

resource "azurerm_resource_group" "workflow" {
  name     = "rg-${var.workflow}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_consumption_budget_resource_group" "workflow" {
  name              = "${var.workflow}-monthly"
  resource_group_id = azurerm_resource_group.workflow.id
  amount            = var.monthly_budget
  time_grain        = "Monthly"

  time_period {
    start_date = var.budget_start
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Actual"
    contact_emails = var.budget_alert_emails
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Forecasted"
    contact_emails = var.budget_alert_emails
  }
}
