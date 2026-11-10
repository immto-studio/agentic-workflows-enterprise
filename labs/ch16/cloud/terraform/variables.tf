variable "region" {
  description = "The lab account creates resources only in us-east-2 (book D-034); the Bedrock profile calls are the one exception, and they are not resources."
  type        = string
  default     = "us-east-2"

  validation {
    condition     = var.region == "us-east-2"
    error_message = "The lab account may create resources only in us-east-2 (book D-034)."
  }
}

variable "az_id" {
  description = "The Availability Zone ID of the one subnet."
  type        = string
  default     = "use2-az1"
}

variable "name" {
  description = "The prefix of every name here."
  type        = string
  default     = "ch16-cloud"
}

variable "workflow" {
  description = "The workflow whose tool role the session assumes with the trace id (chapter 5's manifest)."
  type        = string
  default     = "w3-incident"
}

variable "tool" {
  description = "The tool whose role is made, named as chapter 6's module names it: <workflow>-<tool>."
  type        = string
  default     = "get_pod_status"
}

variable "monthly_budget_usd" {
  description = "The session's budget: a monthly cost budget with an SNS topic as its subscriber. The plan is under 5 USD at list price."
  type        = number
  default     = 5
}

variable "instance_type" {
  description = "The Langfuse VM. Langfuse asks for 4 cores and 16 GiB, a t3.xlarge (fact sheet 8.5). The free plan refused it on 9 November 2026 (not eligible for Free Tier), and the session applied again with m7i-flex.large, the largest eligible type, 2 vCPU and 8 GiB (fact sheet 8.6 and 8.8)."
  type        = string
  default     = "t3.xlarge"
}

variable "root_volume_gib" {
  description = "The VM's one gp3 disk: the images come to a few GiB, and nothing is kept."
  type        = number
  default     = 30
}

variable "langfuse_version" {
  description = "Langfuse's images, pinned by version where the Compose file's tags float (fact sheet 8.5: v4.74.0, published 2026-11-03)."
  type        = string
  default     = "4.74.0"
}

# Langfuse's headless initialization (fact sheet 8.5) and its stores' passwords. The session's driver makes
# them for the run and passes them in a tfvars file that git ignores; none is written to the results.
variable "langfuse_public_key" {
  type      = string
  sensitive = true
}

variable "langfuse_secret_key" {
  type      = string
  sensitive = true
}

variable "langfuse_nextauth_secret" {
  type      = string
  sensitive = true
}

variable "langfuse_salt" {
  type      = string
  sensitive = true
}

variable "langfuse_encryption_key" {
  description = "64 hex characters, as Langfuse's Compose file asks (openssl rand -hex 32)."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.langfuse_encryption_key))
    error_message = "64 lowercase hex characters."
  }
}

variable "langfuse_user_email" {
  description = "The headless init needs a user; the driver gives a fictional address under a reserved domain, and it is never committed or printed."
  type        = string
  sensitive   = true
}

variable "langfuse_user_password" {
  type      = string
  sensitive = true
}

variable "store_password" {
  description = "One password for PostgreSQL, ClickHouse, Redis and MinIO: one VM, one session, no inbound rule."
  type        = string
  sensitive   = true
}
