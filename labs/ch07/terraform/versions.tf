# Chapter 7 lab: the skeleton's harness on Agent Runtime, in Quill's project.
# Validated with `terraform validate`; not applied, because the lab has no Google Cloud account yet.

terraform {
  required_version = ">= 1.13.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.9.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # The Billing Budgets API refuses user credentials without a quota project (403);
  # these two lines are what the provider's documentation asks for.
  billing_project       = var.project_id
  user_project_override = true
}
