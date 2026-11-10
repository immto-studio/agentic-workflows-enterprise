# The harness on AgentCore Runtime: chapter 7's entry point with RUNTIME=agentcore, in the VPC,
# behind Entra, with the model gateway's key in AgentCore Identity's token vault.

# The key stays in Secrets Manager; the provider holds a reference to it, so Terraform's state never
# sees the value. The harness fetches it per request with the workload access token the runtime
# passes in, and the runtime role's policy names this provider and no other.
resource "aws_bedrockagentcore_api_key_credential_provider" "model_gateway" {
  name                  = "${local.workflow}-model-gateway"
  api_key_secret_source = "EXTERNAL"

  api_key_secret_config {
    secret_id = var.gateway_key_secret_arn
    json_key  = "key"
  }

  depends_on = [aws_budgets_budget.account]
}

# What the harness reads from AgentCore's own resources and from the catalog. The gateway lists
# a target's tools as <target>___<tool>; TOOL_TARGETS lets the harness map them back.
locals {
  key_provider = aws_bedrockagentcore_api_key_credential_provider.model_gateway.name
  tool_gateway = aws_bedrockagentcore_gateway.tools.gateway_url
  live_runtime = join("-", [
    aws_bedrockagentcore_agent_runtime.harness.agent_runtime_id,
    aws_bedrockagentcore_agent_runtime_endpoint.live.name,
  ])
  agentcore_endpoint = aws_vpc_endpoint.interface["bedrock-agentcore"].id
  tool_targets = join(",", [
    for tool in sort(keys(local.manifest.tools)) :
    "${tool}=${local.catalog.servers[local.catalog.tools[tool].server].gateway_target}"
  ])
}

resource "aws_bedrockagentcore_agent_runtime" "harness" {
  agent_runtime_name = local.runtime_name
  description        = "The ${local.workflow} harness: chapter 5's skeleton behind chapter 7's entry point"
  role_arn           = aws_iam_role.runtime.arn

  # V1 starts each session's microVM from the image. V2's snapshots aren't offered in Canada, and a
  # snapshot would copy any secret or random value made at start-up into every session.
  platform_version = "V1"

  agent_runtime_artifact {
    container_configuration {
      container_uri = var.image_uri
    }
  }

  network_configuration {
    network_mode = "VPC"
    network_mode_config {
      subnets         = var.subnet_ids
      security_groups = [aws_security_group.runtime.id]
    }
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  # Only a v2.0 Entra token for this runtime, requested by the Teams bot, gets in. Entra's tokens
  # carry no client_id, which allowed_clients checks; the requesting app is azp. The harness reads
  # the engineer from the token and checks that the session's ID names them.
  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url    = local.entra_oidc
      allowed_audience = [var.entra_runtime_client_id]

      custom_claim {
        inbound_token_claim_name       = "azp"
        inbound_token_claim_value_type = "STRING"
        authorizing_claim_match_value {
          claim_match_operator = "EQUALS"
          claim_match_value {
            match_value_string = var.entra_bot_client_id
          }
        }
      }
    }
  }

  request_header_configuration {
    request_header_allowlist = ["Authorization"]
  }

  # A microVM stops after fifteen idle minutes or an hour, against AWS's eight hours; the session
  # itself resumes on a new one at the next request.
  lifecycle_configuration {
    idle_runtime_session_timeout = 900
    max_lifetime                 = 3600
  }

  environment_variables = {
    RUNTIME                     = "agentcore"
    GATEWAY_URL                 = var.model_gateway_url
    GATEWAY_KEY_PROVIDER        = local.key_provider
    WORKFLOW                    = local.workflow
    MODEL_ALIAS                 = local.model_alias
    DATA_CLASS                  = local.data_class
    MCP_URL                     = local.tool_gateway
    MCP_AUTH                    = "sigv4"
    TOOL_TARGETS                = local.tool_targets
    AWS_REGION                  = var.region
    OTEL_EXPORTER_OTLP_ENDPOINT = var.otel_collector_endpoint
  }

  depends_on = [
    aws_budgets_budget.account, aws_iam_role_policy.runtime_start,
  ]
}

# What the bot invokes: a named endpoint pinned to a version, so a new version reaches nobody until
# the pipeline moves the endpoint. DEFAULT follows every update.
resource "aws_bedrockagentcore_agent_runtime_endpoint" "live" {
  name                  = "live"
  description           = "The version the pipeline last released"
  agent_runtime_id      = aws_bedrockagentcore_agent_runtime.harness.agent_runtime_id
  agent_runtime_version = aws_bedrockagentcore_agent_runtime.harness.agent_runtime_version
}

# The runtime's log group, made here so it has a retention and the workflow's key. It holds
# the harness's output, which can carry Confidential fields.
resource "aws_cloudwatch_log_group" "runtime" {
  name              = "/aws/bedrock-agentcore/runtimes/${local.live_runtime}"
  retention_in_days = 400
  kms_key_id        = aws_kms_key.workflow.arn
}

# VPC mode decides where the runtime's traffic goes. Who may invoke it is this policy's job: with
# OAuth the principal must be *, so the condition is what keeps out a valid token from elsewhere.
resource "aws_bedrockagentcore_resource_policy" "runtime" {
  resource_arn = aws_bedrockagentcore_agent_runtime.harness.agent_runtime_arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "ThroughLarkspursEndpointOnly"
      Effect    = "Allow"
      Principal = "*"
      Action    = "bedrock-agentcore:InvokeAgentRuntime"
      Resource  = aws_bedrockagentcore_agent_runtime.harness.agent_runtime_arn
      Condition = { StringEquals = { "aws:SourceVpce" = local.agentcore_endpoint } }
    }]
  })
}
