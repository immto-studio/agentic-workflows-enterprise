variable "region" {
  description = "Where the workflow runs. Its Confidential data stays in Canada, so Larkspur's deployment is ca-central-1 only; a lab run on synthetic data may use the Region its account allows."
  type        = string
  default     = "ca-central-1"

  validation {
    condition     = var.region == "ca-central-1" || var.synthetic_data
    error_message = "The incident workflow carries Confidential data and runs in ca-central-1 only. A lab run on synthetic data elsewhere sets synthetic_data = true."
  }
}

variable "synthetic_data" {
  description = "True only for a lab run that holds no real data, which may then run outside Canada. An account from AWS's newer sign-up may create resources only in the Region AWS assigned it: us-east-2 for a Canadian address."
  type        = bool
  default     = false
}

variable "account_id" {
  description = "The workflow's AWS account. Given rather than looked up, so a plan needs no AWS call."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "An AWS account ID is twelve digits."
  }
}

variable "manifest_path" {
  description = "The workflow manifest this deployment is built from."
  type        = string
  default     = "../manifests/w3-incident.yaml"
}

variable "tool_catalog_path" {
  description = "The platform's tool catalog: which server runs each tool and the AWS access it gets."
  type        = string
  default     = "../catalog/tools.yaml"
}

variable "budget_alert_email" {
  description = "Who the budget alarm emails. The budget is the first resource (D-018); with no address it tracks the spend and emails nobody, for an account whose free plan caps the spend (book D-029)."
  type        = string
  default     = ""

  validation {
    condition     = var.budget_alert_email == "" || can(regex("^[^@ ]+@[^@ ]+$", var.budget_alert_email))
    error_message = "An email address, or empty."
  }
}

variable "monthly_budget_usd" {
  description = "The account's monthly budget; alarms at 80 and 100 percent, and on a forecast over it."
  type        = number
  default     = 150
}

variable "vpc_id" {
  description = "The VPC the runtime's network interfaces, the endpoints and the tool servers share."
  type        = string
}

variable "vpc_cidr" {
  description = "The VPC's CIDR block. The endpoints accept HTTPS from it: the runtime, the bot, the tool servers and the model gateway share them."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets, at least two, in AZ IDs AgentCore supports in the Region (ca-central-1: cac1-az1, cac1-az2, cac1-az4; us-east-2: use2-az1, use2-az2, use2-az3)."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "AWS recommends at least two private subnets in different Availability Zones."
  }
}

variable "route_table_ids" {
  description = "The private subnets' route tables, for the S3 gateway endpoint that serves ECR's layers."
  type        = list(string)
}

variable "image_uri" {
  description = "The harness image in ECR, built for linux/arm64 and named by digest."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image_uri))
    error_message = "Name the image by its digest (...@sha256:...), so a version means one image."
  }
}

variable "ecr_repository_arn" {
  description = "The repository the runtime may pull from, and no other."
  type        = string
}

variable "entra_tenant_id" {
  description = "Larkspur's Entra tenant, whose tokens the runtime accepts."
  type        = string
}

variable "entra_runtime_client_id" {
  description = "The runtime's app registration in Entra. Its client ID is the audience of a v2.0 access token for the runtime (accessTokenAcceptedVersion = 2)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$", var.entra_runtime_client_id))
    error_message = "A v2.0 token's audience is the app's client ID, a GUID, not its api:// URI."
  }
}

variable "entra_bot_client_id" {
  description = "The Teams bot's app registration: the one application whose tokens the runtime accepts (the azp claim)."
  type        = string
}

variable "entra_tool_gateway_client_id" {
  description = "The tool gateway's own app registration, which authenticates it to the MCP servers with a private key JWT."
  type        = string
}

variable "entra_tool_gateway_cert_thumbprint" {
  description = "The SHA-256 thumbprint (base64url) of the certificate made from the signing key's public key and uploaded to that app."
  type        = string
}

variable "mcp_servers_scope" {
  description = "What the tool gateway asks Entra for: the MCP servers' application ID URI with /.default."
  type        = string
}

variable "private_ca_s3_uri" {
  description = "Larkspur's root CA certificate (PEM) in S3. The pipeline registers it on each gateway target, which the provider can't yet."
  type        = string

  validation {
    condition     = can(regex("^s3://[a-z0-9.-]+/.+\\.pem$", var.private_ca_s3_uri))
    error_message = "An s3:// URI of a .pem object."
  }
}

variable "model_gateway_url" {
  description = "Chapter 5's LiteLLM gateway, OpenAI-compatible, ending in /v1."
  type        = string
}

variable "model_gateway_role_arn" {
  description = "The model gateway's role: the only principal the Bedrock runtime endpoint admits."
  type        = string
}

variable "gateway_key_secret_arn" {
  description = "The Secrets Manager secret holding the workflow's virtual key for the model gateway."
  type        = string
}

variable "otel_collector_endpoint" {
  description = "Larkspur's OpenTelemetry Collector inside the VPC, over HTTPS with a certificate from Larkspur's private CA."
  type        = string

  validation {
    condition     = startswith(var.otel_collector_endpoint, "https://")
    error_message = "Spans carry Confidential fields; send them over TLS."
  }
}

variable "model_gateway_security_group_id" {
  description = "The model gateway's load balancer: the runtime reaches it and nothing else on HTTPS outside the endpoints."
  type        = string
}

variable "collector_security_group_id" {
  description = "The OpenTelemetry Collector's security group."
  type        = string
}

variable "mcp_servers_security_group_id" {
  description = "The MCP servers' security group, which admits the tool gateway's interfaces and nothing else."
  type        = string
}

variable "force_destroy_stores" {
  description = "Let a destroy delete the corpus and vector buckets with what they hold. For a sandbox's teardown only."
  type        = bool
  default     = false
}

variable "k8s_mcp_endpoint" {
  description = "The Kubernetes MCP server's Streamable HTTP URL, private to the VPC."
  type        = string
}

variable "knowledge_mcp_endpoint" {
  description = "The knowledge MCP server's Streamable HTTP URL, private to the VPC."
  type        = string
}

variable "tool_server_role_arns" {
  description = "The base roles the tool servers run under, by catalog server name."
  type        = map(string)
}

variable "eks_cluster_name" {
  description = "The EKS cluster the Kubernetes tools act on."
  type        = string
}

variable "person_domain" {
  description = "A tool role's source identity must be a person in this domain."
  type        = string
  default     = "larkspur.example"
}

variable "guardrail_mode" {
  description = "detect for a workflow's first month (chapter 4); block once it errs on fewer than one request in two hundred."
  type        = string
  default     = "detect"

  validation {
    condition     = contains(["detect", "block"], var.guardrail_mode)
    error_message = "guardrail_mode is detect or block."
  }
}
