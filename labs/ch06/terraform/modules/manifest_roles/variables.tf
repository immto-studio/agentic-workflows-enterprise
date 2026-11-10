variable "manifest" {
  description = "A workflow manifest, decoded (labs/ch05/manifest/schema.json)."
  type        = any
}

variable "catalog" {
  description = "The platform's tool catalog, decoded (labs/ch06/catalog/tools.yaml)."
  type        = any
}

variable "template_vars" {
  description = "Values for the catalog's $${...} placeholders: account_id, region, the ARNs it names."
  type        = map(string)
}

variable "permissions_boundary_arn" {
  description = "The boundary every role this module creates carries."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:policy/", var.permissions_boundary_arn))
    error_message = "Every tool role carries a permission boundary; give the boundary policy's ARN."
  }
}

variable "workflow_role_arn" {
  description = "The workflow identity: the harness's role, which calls the tool gateway."
  type        = string
}

variable "gateway_arn" {
  description = "The tool gateway the Cedar permits apply to."
  type        = string
}

variable "eks_cluster_name" {
  description = "The cluster the catalog's eks_access entries apply to."
  type        = string
}

variable "person_domain" {
  description = "A tool role's source identity must be a person in this domain, such as sam.okafor@larkspur.example."
  type        = string
}

variable "max_session_seconds" {
  description = "The longest a tool server may hold a tool's role. One hour is IAM's floor for a role; the server asks for fifteen minutes."
  type        = number
  default     = 3600
}
