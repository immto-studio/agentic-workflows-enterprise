variable "region" {
  description = "The Region of the cluster the writer reaches. Canadian, as chapter 6's lab and W2's aws/."
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
  description = "The EKS cluster the writer server runs in and writes to."
  type        = string
  default     = "ops"
}

variable "servers_namespace" {
  description = "The namespace the writer server runs in; its service account gets the runtime role through Pod Identity."
  type        = string
  default     = "larkspur-ops"
}

variable "writer_service_account" {
  description = "The writer server's Kubernetes service account, bound to the runtime role."
  type        = string
  default     = "writer-mcp"
}

variable "write_namespaces" {
  description = "The namespaces the writer may change (the custom Kubernetes Role's scope, bound in the cluster)."
  type        = list(string)
  default     = ["larkspur-prod"]
}

variable "writer_k8s_group" {
  description = "The Kubernetes group the write roles' access entries map to; the custom Role is bound to it in the namespace."
  type        = string
  default     = "larkspur-ops-writers"
}

variable "catalog_path" {
  description = "catalog/tools.yaml: the write identities and the actions each may hold."
  type        = string
  default     = "../catalog/tools.yaml"
}

variable "manifest_path" {
  description = "manifest/w3-incident.yaml: the workflow's name, owner, and sponsor for the tags."
  type        = string
  default     = "../manifest/w3-incident.yaml"
}
