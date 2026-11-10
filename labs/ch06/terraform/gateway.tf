# The tool gateway: AgentCore Gateway in front of Larkspur's two MCP servers, with a policy engine
# in ENFORCE mode. The harness signs its MCP requests with its execution role (AWS_IAM), so the
# policy engine sees the workflow as AgentCore::IamEntity and permits only the manifest's tools.

resource "aws_bedrockagentcore_policy_engine" "tools" {
  name        = "${local.agentcore_name}_tools"
  description = "Which tools ${local.workflow} may call, and with which arguments"
  depends_on  = [aws_budgets_budget.account]
}

resource "aws_bedrockagentcore_gateway" "tools" {
  name            = "${local.workflow}-tools"
  description     = "MCP tools for ${local.workflow}"
  role_arn        = aws_iam_role.tool_gateway.arn
  protocol_type   = "MCP"
  authorizer_type = "AWS_IAM"

  # A policy engine with no policies denies everything, so the gateway is closed until the
  # policies below exist. LOG_ONLY would let every call through; the boundary denies UpdateGateway.
  policy_engine_configuration {
    arn  = aws_bedrockagentcore_policy_engine.tools.policy_engine_arn
    mode = "ENFORCE"
  }

  depends_on = [aws_budgets_budget.account, aws_iam_role_policy.tool_gateway_start]
}

# The tool gateway's client credential for Entra: a private key JWT signed in KMS, so no secret
# exists. Each workflow's gateway has an app registration of its own, and the MCP servers know the
# workflow from the token's azp.
resource "aws_bedrockagentcore_oauth2_credential_provider" "tool_gateway" {
  name                       = "${local.workflow}-tool-gateway"
  credential_provider_vendor = "CustomOauth2"

  oauth2_provider_config {
    custom_oauth2_provider_config {
      client_id                    = var.entra_tool_gateway_client_id
      client_authentication_method = "PRIVATE_KEY_JWT"

      oauth_discovery {
        discovery_url = local.entra_oidc
      }

      private_key_jwt_config {
        signing_algorithm        = "RS256"
        additional_header_claims = { "x5t#S256" = var.entra_tool_gateway_cert_thumbprint }
        private_key_source {
          kms_key_source {
            kms_key_arn = aws_kms_key.tool_gateway_signing.arn
          }
        }
      }
    }
  }

  depends_on = [aws_budgets_budget.account]
}

# One target per MCP server in the catalog that the manifest uses. The servers are private: the
# gateway reaches them through interfaces in the VPC, over TLS with Larkspur's private CA, which
# the pipeline registers on each target after an apply (hashicorp/aws 6.71.0 has no field for it).
# The person's token for the server travels in X-Larkspur-Actor, the only header the gateway
# passes on; the server validates it and assumes the tool's role for that one request.
locals {
  mcp_endpoints = {
    k8s       = var.k8s_mcp_endpoint
    knowledge = var.knowledge_mcp_endpoint
  }
  used_targets     = toset([for tool in keys(local.manifest.tools) : local.catalog.servers[local.catalog.tools[tool].server].gateway_target])
  gateway_endpoint = aws_vpc_endpoint.interface["bedrock-agentcore.gateway"].id
  private_ca_arn   = "arn:aws:s3:::${trimprefix(var.private_ca_s3_uri, "s3://")}"
}

resource "aws_bedrockagentcore_gateway_target" "mcp" {
  for_each = local.used_targets

  gateway_identifier = aws_bedrockagentcore_gateway.tools.gateway_id
  name               = each.key

  target_configuration {
    mcp {
      mcp_server {
        endpoint = local.mcp_endpoints[each.key]
      }
    }
  }

  private_endpoint {
    managed_vpc_resource {
      vpc_identifier           = var.vpc_id
      subnet_ids               = var.subnet_ids
      security_group_ids       = [aws_security_group.tool_gateway.id]
      endpoint_ip_address_type = "IPV4"
    }
  }

  credential_provider_configuration {
    oauth {
      provider_arn = aws_bedrockagentcore_oauth2_credential_provider.tool_gateway.credential_provider_arn
      grant_type   = "CLIENT_CREDENTIALS"
      scopes       = [var.mcp_servers_scope]
    }
  }

  metadata_configuration {
    allowed_request_headers = ["X-Larkspur-Actor"]
  }
}

# Only the harness may invoke the tool gateway, and only through Larkspur's endpoint for it, so
# credentials taken out of a microVM are no use outside the VPC.
resource "aws_bedrockagentcore_resource_policy" "tool_gateway" {
  resource_arn = aws_bedrockagentcore_gateway.tools.gateway_arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "TheHarness"
        Effect    = "Allow"
        Principal = { AWS = aws_iam_role.runtime.arn }
        Action    = "bedrock-agentcore:InvokeGateway"
        Resource  = aws_bedrockagentcore_gateway.tools.gateway_arn
      },
      {
        Sid       = "ThroughLarkspursEndpointOnly"
        Effect    = "Deny"
        Principal = "*"
        Action    = "bedrock-agentcore:InvokeGateway"
        Resource  = aws_bedrockagentcore_gateway.tools.gateway_arn
        Condition = { StringNotEquals = { "aws:SourceVpce" = local.gateway_endpoint } }
      },
    ]
  })
}

# The gateway's application logs, which can hold MCP request and response bodies: delivered to a
# log group with a retention and the workflow's key.
resource "aws_cloudwatch_log_group" "tool_gateway" {
  name              = "/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/${aws_bedrockagentcore_gateway.tools.gateway_id}"
  retention_in_days = 400
  kms_key_id        = aws_kms_key.workflow.arn
}

resource "aws_cloudwatch_log_delivery_source" "tool_gateway" {
  name         = "${local.workflow}-tool-gateway"
  log_type     = "APPLICATION_LOGS"
  resource_arn = aws_bedrockagentcore_gateway.tools.gateway_arn
}

resource "aws_cloudwatch_log_delivery_destination" "tool_gateway" {
  name = "${local.workflow}-tool-gateway"
  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.tool_gateway.arn
  }
}

resource "aws_cloudwatch_log_delivery" "tool_gateway" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.tool_gateway.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.tool_gateway.arn
}

# The workflow identity's invoke scopes, as Cedar: one permit per tool in the manifest, narrowed by
# its `allow` list. The module writes them from the manifest; nothing else adds a policy.
resource "aws_bedrockagentcore_policy" "invoke" {
  for_each = module.workflow_identities.cedar_permits

  name             = "${local.agentcore_name}_${each.key}"
  description      = "${local.workflow} may call ${each.key}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.tools.policy_engine_id
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = each.value
    }
  }

  # Each permit names a tool by target, so the targets come first.
  depends_on = [aws_bedrockagentcore_gateway_target.mcp]
}
