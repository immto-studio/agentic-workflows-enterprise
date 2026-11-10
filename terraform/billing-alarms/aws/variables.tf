variable "monthly_limit_usd" {
  description = "Monthly spending limit in USD. The budget and the CloudWatch billing alarm both use it."
  type        = number
  default     = 150

  validation {
    condition     = var.monthly_limit_usd > 0
    error_message = "monthly_limit_usd must be a positive number."
  }
}

variable "alert_email" {
  description = "Email address that receives budget notifications and the billing alarm. Must be confirmed via the SNS subscription email."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "owner" {
  description = "Person or team responsible for the lab account. Written to the owner tag on every resource."
  type        = string

  validation {
    condition     = length(trimspace(var.owner)) > 0
    error_message = "owner must not be empty."
  }
}

variable "name_prefix" {
  description = "Prefix for resource names (budget, alarm, SNS topic)."
  type        = string
  default     = "lab-billing"
}
