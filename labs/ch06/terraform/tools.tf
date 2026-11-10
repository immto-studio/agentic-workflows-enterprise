# The manifest becomes identities: a role for each tool the manifest lists, and the workflow
# identity's invoke scopes as Cedar permits for the tool gateway (gateway.tf creates them).

module "workflow_identities" {
  source = "./modules/manifest_roles"

  manifest                 = local.manifest
  catalog                  = local.catalog
  permissions_boundary_arn = aws_iam_policy.agent_boundary.arn
  workflow_role_arn        = aws_iam_role.runtime.arn
  gateway_arn              = aws_bedrockagentcore_gateway.tools.gateway_arn
  eks_cluster_name         = var.eks_cluster_name
  person_domain            = var.person_domain

  template_vars = {
    account_id             = var.account_id
    region                 = var.region
    cluster_arn            = local.cluster_arn
    knowledge_base_arn     = aws_bedrockagent_knowledge_base.runbooks.arn
    k8s_mcp_role_arn       = var.tool_server_role_arns["k8s-mcp"]
    knowledge_mcp_role_arn = var.tool_server_role_arns["knowledge-mcp"]
  }

  depends_on = [aws_budgets_budget.account]
}
