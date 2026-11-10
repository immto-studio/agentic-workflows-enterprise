variable "region" {
  description = "The Region of the ops cluster the agents run in. Canadian, as chapter 6's lab and W2's and W3's aws/."
  type        = string
  default     = "ca-central-1"
}

variable "account_id" {
  description = "The account the roles live in; the plan runs offline, so the account comes from a variable."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id is the twelve-digit account number."
  }
}

variable "cluster_name" {
  description = "The EKS cluster the agents run in."
  type        = string
  default     = "ops"
}

variable "github_oidc_provider_arn" {
  description = "The account's OIDC provider for GitHub Actions (ADR-0049 created it once per account); empty means the standard name in this account."
  type        = string
  default     = ""
}

variable "catalog_path" {
  description = "catalog/tools.yaml: the agents, their identities and GitHub Apps, the trigger, and the never-list."
  type        = string
  default     = "../catalog/tools.yaml"
}

variable "manifest_path" {
  description = "manifest/w4-change.yaml: the workflow's name, owner, sponsor, and never-list."
  type        = string
  default     = "../manifest/w4-change.yaml"
}
