locals {
  manifest = yamldecode(file(var.manifest_path))
  catalog  = yamldecode(file(var.tool_catalog_path))
  workflow = local.manifest.workflow

  # AgentCore runtime, policy-engine and policy names take letters, digits and underscores only.
  agentcore_name = replace(local.workflow, "-", "_")
  runtime_name   = "${local.agentcore_name}_harness"

  arn_prefix  = "arn:aws:bedrock-agentcore:${var.region}:${var.account_id}"
  entra_oidc  = "https://login.microsoftonline.com/${var.entra_tenant_id}/v2.0/.well-known/openid-configuration"
  cluster_arn = "arn:aws:eks:${var.region}:${var.account_id}:cluster/${var.eks_cluster_name}"

  # The data class and alias the harness sends with every model call; the gateway checks both
  # against the manifest. Until the harness classifies each call (chapter 12), every call carries
  # the manifest's highest class: Restricted for the incident workflow, which the gateway sends to
  # the self-hosted model alone.
  data_class = local.manifest.data_class_max
  model_alias = {
    restricted   = "larkspur-chat-restricted"
    confidential = "larkspur-chat"
    internal     = "larkspur-chat"
    public       = "larkspur-chat"
  }[local.data_class]
}
