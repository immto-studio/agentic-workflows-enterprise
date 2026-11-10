variable "region" {
  description = "The Region of the cluster, the log groups, and the metrics. Canadian, as chapter 6's lab."
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
  description = "The EKS cluster the servers run in and the Kubernetes server reads."
  type        = string
  default     = "ops"
}

variable "servers_namespace" {
  description = "The Kubernetes namespace the three servers run in; each has a service account named after its server."
  type        = string
  default     = "larkspur-ops"
}

variable "read_namespaces" {
  description = "The namespaces the Kubernetes server may read (the EKS access policy's scope)."
  type        = list(string)
  default     = ["larkspur-prod"]
}

variable "log_group_prefix" {
  description = "The log groups the logs server may read, by prefix; one per service under it."
  type        = string
  default     = "/larkspur/prod/"
}

variable "catalog_path" {
  description = "catalog/tools.yaml: the identities and the actions each may hold."
  type        = string
  default     = "../catalog/tools.yaml"
}

variable "manifest_path" {
  description = "manifest/w2-ops-assistant.yaml: the workflow's name, owner, and sponsor for the tags."
  type        = string
  default     = "../manifest/w2-ops-assistant.yaml"
}
