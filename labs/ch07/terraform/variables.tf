variable "project_id" {
  description = "The Quill project the workflow runs in, one project per workflow."
  type        = string
}

variable "project_number" {
  description = "That project's number; service agents and principals are named by it."
  type        = string
}

variable "billing_account" {
  description = "The billing account the budget watches."
  type        = string
}

variable "budget_alert_email" {
  description = "Where the budget alarm goes: the workflow owner and FinOps."
  type        = string
}

variable "monthly_budget" {
  description = "The workflow's monthly budget from its manifest, in the billing account's currency."
  type        = number
}

variable "region" {
  description = "Montréal: Agent Runtime, Memory Bank and Agent Gateway all run there."
  type        = string
  default     = "northamerica-northeast1"
}

variable "workflow" {
  description = "The workflow's name in its manifest; the harness sends it to the gateway."
  type        = string
  default     = "ops-assistant"
}

variable "owner" {
  description = "The workflow owner's team, as the tagging policy names it."
  type        = string
  default     = "quill-sre"
}

variable "model_alias" {
  description = "The gateway alias the workflow calls; on Google the Confidential alias is served in Montréal."
  type        = string
  default     = "larkspur-chat"
}

variable "data_class" {
  description = "The highest data class the workflow sends. Quill's logs carry policy numbers, so Confidential."
  type        = string
  default     = "confidential"
}

variable "harness_image" {
  description = "The harness container in Artifact Registry (labs/ch07/image), pinned by digest."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.harness_image))
    error_message = "Pin the image by digest, not by tag."
  }
}

variable "image_repository" {
  description = "The Artifact Registry repository that holds the harness image."
  type        = string
  default     = "agent-harness"
}

variable "gateway_url" {
  description = "The model gateway's internal address, resolved through the Agent Gateway's DNS peering."
  type        = string
  default     = "https://llm-gateway.quill.larkspur.internal/v1"
}

variable "mcp_url" {
  description = "The Kubernetes MCP server's internal address."
  type        = string
  default     = "https://mcp-k8s.quill.larkspur.internal/mcp"
}

variable "otel_endpoint" {
  description = "The OpenTelemetry Collector the observability team runs on GKE."
  type        = string
  default     = "https://otel.quill.larkspur.internal"
}

variable "gateway_key_secret" {
  description = "The Secret Manager secret holding this workflow's gateway key, written there from Vault."
  type        = string
  default     = "ops-assistant-gateway-key"
}

variable "gateway_key_version" {
  description = "The secret version to read; pinned, so a rotation is a deployment."
  type        = string
}

variable "network_attachment" {
  description = "The network attachment through which the Agent Gateway reaches Quill's VPC."
  type        = string
}

variable "vpc_network" {
  description = "Quill's VPC, as projects/PROJECT/global/networks/NAME, for the gateway's DNS peering."
  type        = string
}

variable "internal_domain" {
  description = "The private DNS zone the gateway resolves internal names in."
  type        = string
  default     = "quill.larkspur.internal."
}

variable "trust_config" {
  description = "The Certificate Manager trust config holding Larkspur's private CA, for the gateway's TLS."
  type        = string
}

variable "gateway_dry_run" {
  description = "Audit-only enforcement for a new workflow's gateway: logs what it would refuse. Applies to every agent on the gateway."
  type        = bool
  default     = true
}

variable "kms_key" {
  description = "The customer-managed key for the agent's code, images and instances, in the same region."
  type        = string
}

variable "model_gateway_service_account" {
  description = "The service account the LiteLLM pods run as, the only principal allowed to send a prompt."
  type        = string
}

variable "deny_folder_number" {
  description = "The folder that holds only agent projects (the gateway pair's project outside it); null in a sandbox without an organization, where the deny sits on the project."
  type        = string
  default     = null
}

variable "memory_retention_days" {
  description = "How long Memory Bank keeps a memory and its revisions: the manifest's retention, not Google's default."
  type        = number
  default     = 30
}

variable "deletion_policy" {
  description = "PREVENT in production, so a plan that would replace the agent (and mint a new principal) fails; FORCE in a sandbox, so destroy removes the agent with its sessions."
  type        = string
  default     = "PREVENT"

  validation {
    condition     = contains(["PREVENT", "FORCE", "DELETE"], var.deletion_policy)
    error_message = "One of PREVENT, FORCE, DELETE."
  }
}
