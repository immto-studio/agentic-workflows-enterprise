# The two APIs the budget alarm itself needs come first; every other API, and every other
# resource, waits for the budget (D-018: a budget alarm is the first resource in an account).

resource "google_project_service" "budget_apis" {
  for_each           = toset(["billingbudgets.googleapis.com", "monitoring.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

resource "google_project_service" "platform" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "agentregistry.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudkms.googleapis.com",
    "iap.googleapis.com",
    "networksecurity.googleapis.com",
    "networkservices.googleapis.com",
    "secretmanager.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
  depends_on         = [google_billing_budget.workflow]
}
