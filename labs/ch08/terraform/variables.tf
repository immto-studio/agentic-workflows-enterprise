variable "subscription_id" {
  description = "The workflow's subscription."
  type        = string
}

variable "location" {
  description = "Canada Central: the agents' Foundry account, the network, the registry."
  type        = string
  default     = "canadacentral"
}

variable "model_location" {
  description = "Canada East: the only Canadian region with Standard deployments of chat models in October 2026 (gpt-4o 2024-11-20 and gpt-4.1-mini 2025-04-14; see ../models.yaml)."
  type        = string
  default     = "canadaeast"
}

variable "workflow" {
  description = "The workflow's name in its manifest."
  type        = string
  default     = "ops-assistant"
}

variable "owner" {
  description = "The workflow owner's team, as the tagging policy names it."
  type        = string
  default     = "commercial-lines-sre"
}

variable "name_suffix" {
  description = "A short suffix that makes the accounts' subdomains and the registry's name unique."
  type        = string
}

variable "monthly_budget" {
  description = "The workflow's monthly budget from its manifest, in the subscription's currency."
  type        = number
}

variable "budget_start" {
  description = "The first day of the budget's first month, as YYYY-MM-01T00:00:00Z."
  type        = string
}

variable "budget_alert_emails" {
  description = "Where the budget alarm goes: the workflow owner and FinOps. At least one address: Azure refuses a budget without a notification (the sandbox apply of 2026-11-02), unlike AWS's."
  type        = list(string)

  validation {
    condition     = length(var.budget_alert_emails) >= 1
    error_message = "An Azure budget needs at least one notification, so at least one address."
  }
}

# Chosen once, for every project in the account. "By default, concurrent sessions and usable subnet
# IPs map 1:1" and "All projects in the account share the same subnet configuration" (Deep dive into
# Foundry Agent Service networking, 2026-09-07); "you cannot change the delegated subnet to a new
# one" (How to configure network isolation for Microsoft Foundry, 2026-09-29).
variable "agent_subnet_id" {
  description = "The subnet the hosted agents are injected into: delegated to Microsoft.App/environments, RFC 1918, used by no other Foundry account, and fixed for the account's life. Every project in the account shares it, and each concurrent session takes one usable address: about 20 sessions on a /27, 250 on a /24, 2,000 on a /21, and up to ten times that if Azure support raises the mapping to 1:10. Size it for the peak across all projects plus the 20 percent headroom Microsoft recommends; Microsoft says not to use a /27 for production."
  type        = string
}

variable "private_endpoint_subnet_id" {
  description = "The subnet for the private endpoints."
  type        = string
}

variable "private_dns_zone_ids" {
  description = "privatelink.cognitiveservices.azure.com, privatelink.openai.azure.com and privatelink.services.ai.azure.com, owned by network security."
  type        = list(string)
}

variable "registry_dns_zone_id" {
  description = "privatelink.azurecr.io."
  type        = string
}

variable "gateway_principal_id" {
  description = "The object ID of the managed identity the LiteLLM pods on AKS run as: the only principal allowed to call the models."
  type        = string
}

variable "chat_model" {
  description = "A chat model Microsoft serves as a Standard deployment in the model location and that a new subscription can still deploy (GA or Legacy); see ../models.yaml."
  type        = object({ name = string, version = string })
  default     = { name = "gpt-4o", version = "2024-11-20" }
}

variable "chat_capacity" {
  description = "The deployment's capacity in thousands of tokens a minute."
  type        = number
  default     = 50
}
