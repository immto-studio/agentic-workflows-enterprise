# The runtime runs in Larkspur's VPC with no route to the internet. These are the endpoints it, the
# tool servers and the model gateway reach AWS through, as a sandbox VPC needs them; in Larkspur's
# landing zone network security runs them for every workflow, and the tool servers' cluster adds
# its own (CloudWatch for alarms, EKS, EKS Pod Identity).

locals {
  interface_endpoints = {
    "bedrock-agentcore"         = "the token vault, for the model gateway's key"
    "bedrock-agentcore.gateway" = "the tool gateway's MCP endpoint"
    "ecr.api"                   = "image metadata"
    "ecr.dkr"                   = "image pulls"
    "logs"                      = "the runtime's log group"
    "sts"                       = "tool servers assuming a tool's role for each request"
    "bedrock-runtime"           = "the model gateway's calls to Bedrock, guardrails included"
    "bedrock-agent-runtime"     = "Retrieve on the knowledge base"
  }

  # Only the model gateway may call a model; chapter 3's organization policy says the same.
  endpoint_policies = {
    "bedrock-runtime" = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Sid       = "ModelGatewayOnly"
        Effect    = "Allow"
        Principal = "*"
        Action    = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:ApplyGuardrail"]
        Resource  = "*"
        Condition = { ArnEquals = { "aws:PrincipalArn" = var.model_gateway_role_arn } }
      }]
    })
  }
}

resource "aws_security_group" "runtime" {
  name        = "${local.workflow}-runtime"
  description = "Harness network interfaces: out to the endpoints, the model gateway, and the collector; nothing in"
  vpc_id      = var.vpc_id
  depends_on  = [aws_budgets_budget.account]
}

# Security groups, not the VPC's CIDR: the harness reaches these and no other service in the VPC,
# another workflow's MCP servers included.
locals {
  runtime_egress = {
    endpoints     = { group = aws_security_group.endpoints.id, port = 443 }
    model_gateway = { group = var.model_gateway_security_group_id, port = 443 }
    collector     = { group = var.collector_security_group_id, port = 4318 }
  }
}

resource "aws_vpc_security_group_egress_rule" "runtime" {
  for_each = local.runtime_egress

  security_group_id            = aws_security_group.runtime.id
  description                  = "to ${each.key}"
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
  referenced_security_group_id = each.value.group
}

resource "aws_security_group" "endpoints" {
  name        = "${local.workflow}-endpoints"
  description = "Interface endpoints: HTTPS from inside the VPC"
  vpc_id      = var.vpc_id
  depends_on  = [aws_budgets_budget.account]
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_https" {
  security_group_id = aws_security_group.endpoints.id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = var.vpc_cidr
}

resource "aws_security_group" "tool_gateway" {
  name        = "${local.workflow}-tool-gateway"
  description = "Tool gateway interfaces into the VPC: HTTPS to the MCP servers"
  vpc_id      = var.vpc_id
  depends_on  = [aws_budgets_budget.account]
}

resource "aws_vpc_security_group_egress_rule" "tool_gateway_https" {
  security_group_id            = aws_security_group.tool_gateway.id
  description                  = "to the MCP servers"
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  referenced_security_group_id = var.mcp_servers_security_group_id
}

resource "aws_vpc_endpoint" "interface" {
  for_each = local.interface_endpoints

  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = var.subnet_ids
  security_group_ids  = [aws_security_group.endpoints.id]
  policy              = lookup(local.endpoint_policies, each.key, null)
  tags                = { Name = "${local.workflow}-${each.key}", purpose = each.value }
  depends_on          = [aws_budgets_budget.account]
}

# ECR keeps image layers in S3. A gateway endpoint costs nothing and keeps those pulls off a NAT;
# its policy admits ECR's layer bucket for this Region and nothing else.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.route_table_ids
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "EcrLayersOnly"
      Effect    = "Allow"
      Principal = "*"
      Action    = ["s3:GetObject"]
      Resource  = ["arn:aws:s3:::prod-${var.region}-starport-layer-bucket/*"]
    }]
  })
  tags       = { Name = "${local.workflow}-s3" }
  depends_on = [aws_budgets_budget.account]
}

# A gateway endpoint has no security group of its own, so the runtime's egress has to name S3's
# prefix list as well as the interface endpoints' group; without this rule the layer pull dials S3
# and times out, and the runtime answers every invocation with a 502 (the first invocation, 2
# November 2026). The endpoint's policy above still admits ECR's layer bucket and nothing else.
resource "aws_vpc_security_group_egress_rule" "runtime_s3" {
  security_group_id = aws_security_group.runtime.id
  description       = "to the S3 gateway endpoint, for the image layers"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
}
