variable "region" {
  description = "The Region of the ops cluster the readers run in. Canadian, as chapter 6's lab and W2's to W4's aws/."
  type        = string
  default     = "ca-central-1"
}

variable "account_id" {
  description = "The ops account, the cluster's, where the readers' own roles live; the plan runs offline, so the account comes from a variable."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id is the twelve-digit account number."
  }
}

variable "workload_account_ids" {
  description = "The workspace map's account names -> their twelve-digit IDs: the workload accounts whose target roles the cloud and cost readers assume (fact sheet C.7). The plan runs offline, so the IDs come from a variable."
  type        = map(string)
  validation {
    condition     = alltrue([for id in values(var.workload_account_ids) : can(regex("^[0-9]{12}$", id))])
    error_message = "Each workload account ID is the twelve-digit account number."
  }
}

variable "organization_id" {
  description = "The organization the ops account and the workload accounts belong to; every target role's trust matches it in aws:PrincipalOrgID (C.8.5)."
  type        = string
  validation {
    condition     = length(trimspace(var.organization_id)) > 0
    error_message = "organization_id is the organization's ID in AWS Organizations."
  }
}

variable "cluster_name" {
  description = "The EKS cluster the readers and the harness run in."
  type        = string
  default     = "ops"
}

variable "state_kms_key_arn" {
  description = "The ARN of the state bucket's KMS key. The state stack owns the bucket and the key and gives this ARN; the catalog names the key by its alias."
  type        = string
  validation {
    condition     = can(regex("^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/", var.state_kms_key_arn))
    error_message = "state_kms_key_arn is a KMS key's ARN, arn:aws:kms:<region>:<account>:key/<id>."
  }
}

variable "cost_export_bucket" {
  description = "The bucket the management account delivers the organization's CUR 2.0 export to: the ops account owns it, with ACLs disabled, and it is a bucket of its own, because creating an export over a bucket overwrites the bucket's one policy (C.11.2, C.12.3)."
  type        = string
  default     = "larkspur-cost-exports"
  validation {
    condition     = var.cost_export_bucket != local.state.bucket
    error_message = "The export's bucket is never the state bucket: an export created over it would overwrite the state stack's bucket policy (C.11.2)."
  }
}

variable "catalog_path" {
  description = "catalog/tools.yaml: the identities, their service accounts, target roles, and actions, the GitHub Apps, the ruleset, and the never-list."
  type        = string
  default     = "../catalog/tools.yaml"
}

variable "workspace_map_path" {
  description = "catalog/workspace-map.yaml: the workspaces the agent's group may read, whose state keys the state reader gets, and the accounts the cloud and cost readers read."
  type        = string
  default     = "../catalog/workspace-map.yaml"
}

variable "manifest_path" {
  description = "manifest/w5-drift.yaml: the workflow's name, owner, sponsor, and never-list."
  type        = string
  default     = "../manifest/w5-drift.yaml"
}
