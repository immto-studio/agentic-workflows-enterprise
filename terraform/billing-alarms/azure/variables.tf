variable "subscription_id" {
  description = "ID (GUID) of the lab subscription the budget is created on."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}

variable "monthly_limit_usd" {
  description = "Monthly spending limit. Azure evaluates it in the subscription's billing currency, so it means USD only on a USD-billed subscription."
  type        = number
  default     = 150

  validation {
    condition     = var.monthly_limit_usd > 0
    error_message = "monthly_limit_usd must be a positive number."
  }
}

variable "alert_email" {
  description = "Email address of the action group email receiver that the budget notifies."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "owner" {
  description = "Person or team responsible for the lab subscription. Written to the owner tag on every resource."
  type        = string

  validation {
    condition     = length(trimspace(var.owner)) > 0
    error_message = "owner must not be empty."
  }
}

variable "location" {
  description = "Azure region for the resource group that holds the action group. The action group itself is global."
  type        = string
  default     = "westeurope"
}

variable "name_prefix" {
  description = "Prefix for resource names (resource group, action group, budget)."
  type        = string
  default     = "lab-billing"
}

variable "budget_start_date" {
  description = "First day of the first budget month, RFC 3339 (e.g. 2026-11-01T00:00:00Z). Null uses the first day of the current month at apply time."
  type        = string
  default     = null

  validation {
    condition     = var.budget_start_date == null || can(regex("^[0-9]{4}-[0-9]{2}-01T00:00:00Z$", var.budget_start_date))
    error_message = "budget_start_date must be the first day of a month, formatted YYYY-MM-01T00:00:00Z."
  }
}
