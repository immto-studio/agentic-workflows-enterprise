variable "account" {
  description = "The account's name in the workspace map (catalog/workspace-map.yaml)."
  type        = string
}

variable "readers" {
  description = "reader -> its target role here: the role's name, the reader's role in the ops account (the chain's first link), its namespace and its service account per account, the reads its fake mirrors, a statement id, and its team."
  type = map(object({
    role             = string
    ops_role_arn     = string
    namespace        = string
    service_accounts = map(string)
    actions          = list(string)
    sid              = string
    team             = string
  }))
}

variable "ops_account_id" {
  description = "The ops account, where the cluster and the readers' first roles are: the target roles' trusted principal."
  type        = string
}

variable "organization_id" {
  description = "The organization every caller must belong to (aws:PrincipalOrgID, C.8.5)."
  type        = string
}

variable "cluster_arn" {
  description = "The ops cluster's ARN, which Pod Identity passes as the eks-cluster-arn session tag (C.7.6)."
  type        = string
}

variable "never_actions" {
  description = "The never-list as AWS actions, sts:AssumeRole included, which the target roles' boundary denies on every resource."
  type        = list(string)
}

variable "workflow" {
  description = "The workflow's name, for the boundary's name."
  type        = string
}
