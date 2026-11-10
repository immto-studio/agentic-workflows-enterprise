output "budget_id" {
  description = "Resource name of the billing budget (billingAccounts/.../budgets/...)."
  value       = google_billing_budget.monthly.id
}

output "notification_channel_id" {
  description = "Resource name of the email notification channel."
  value       = google_monitoring_notification_channel.email.id
}
