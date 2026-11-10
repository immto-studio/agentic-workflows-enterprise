variable "billing_account" {
  description = "Billing account ID the budget is created on, in the form 012345-6789AB-CDEF01."
  type        = string

  validation {
    condition     = can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", var.billing_account))
    error_message = "billing_account must look like 012345-6789AB-CDEF01."
  }
}

variable "project_id" {
  description = "ID of the lab project the budget is scoped to. The notification channel is created in this project."
  type        = string
}

variable "monthly_limit_usd" {
  description = "Monthly spending limit. The billing account must be billed in USD, because the budget amount is in USD."
  type        = number
  default     = 150

  validation {
    condition     = var.monthly_limit_usd > 0
    error_message = "monthly_limit_usd must be a positive number."
  }
}

variable "alert_email" {
  description = "Email address of the Cloud Monitoring notification channel that receives budget alerts."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "owner" {
  description = "Person or team responsible for the lab project. Written to the owner label; Google Cloud labels allow lowercase letters, digits, underscores and hyphens only."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9_-]{1,63}$", var.owner))
    error_message = "owner must be 1 to 63 lowercase letters, digits, underscores or hyphens."
  }
}

variable "name_prefix" {
  description = "Prefix for display names (budget, notification channel)."
  type        = string
  default     = "lab-billing"
}
