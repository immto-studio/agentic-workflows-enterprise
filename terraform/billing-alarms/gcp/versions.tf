terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 7.46.2"
    }
  }
}

# The Billing Budgets API needs a quota project when called with user
# credentials (gcloud auth application-default login); bill those calls to
# the lab project.
provider "google" {
  project               = var.project_id
  billing_project       = var.project_id
  user_project_override = true
}
