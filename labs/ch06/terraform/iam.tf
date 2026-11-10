# Roles. Every role that acts for the workflow (the harness's and each tool's) carries the same
# permission boundary; the service roles (tool gateway, knowledge base, invocation logging) don't
# act for it and get only their own narrow policies.

# --- the boundary: the most an agent or tool role in this account may ever do ---------------------

data "aws_iam_policy_document" "agent_boundary" {
  statement {
    sid    = "Ceiling"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:InvokeGateway",
      "bedrock-agentcore:GetWorkloadAccessToken",
      "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
      "bedrock-agentcore:GetResourceApiKey",
      "secretsmanager:GetSecretValue", # the gateway key's secret, which the vault reads as the caller (below)
      "bedrock:Retrieve",
      "eks:DescribeCluster",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:DescribeAlarmHistory",
      "cloudwatch:PutMetricData",
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
      "ecr:GetAuthorizationToken",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = ["*"]
  }

  # Models are called through the model gateway, never by an agent's own role.
  statement {
    sid       = "NoDirectModelCalls"
    effect    = "Deny"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock-mantle:*"]
    resources = ["*"]
  }

  # No role chaining, no identity changes, and nothing that switches the tool gateway's policy
  # engine to LOG_ONLY or detaches it: UpdateGateway alone controls that.
  statement {
    sid    = "NoEscalation"
    effect = "Deny"
    actions = [
      "sts:AssumeRole",
      "iam:*",
      "organizations:*",
      "bedrock-agentcore:UpdateGateway",
      "bedrock-agentcore:CreatePolicy",
      "bedrock-agentcore:UpdatePolicy",
      "bedrock-agentcore:DeletePolicy",
      "bedrock-agentcore:UpdatePolicyEngine",
      "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "agent_boundary" {
  name        = "${local.workflow}-agent-boundary"
  description = "Permission boundary on every role that acts for ${local.workflow}"
  policy      = data.aws_iam_policy_document.agent_boundary.json
  depends_on  = [aws_budgets_budget.account]
}

# --- the harness: the runtime's execution role, the workflow identity ----------------------------

data "aws_iam_policy_document" "runtime_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["${local.arn_prefix}:runtime/${local.runtime_name}-*"]
    }
  }
}

resource "aws_iam_role" "runtime" {
  name                 = "${local.workflow}-harness"
  description          = "The ${local.workflow} harness on AgentCore Runtime: invoke tools through the gateway, nothing else"
  assume_role_policy   = data.aws_iam_policy_document.runtime_trust.json
  permissions_boundary = aws_iam_policy.agent_boundary.arn
  max_session_duration = 3600
  depends_on           = [aws_budgets_budget.account]
}

# What the runtime needs before the first request: the image and the log group. It holds no
# bedrock:InvokeModel, which AWS's example execution role grants; model calls go to the gateway.
data "aws_iam_policy_document" "runtime_start" {
  statement {
    sid       = "EcrToken"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid       = "ThisImageOnly"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [var.ecr_repository_arn]
  }
  statement {
    sid       = "OwnLogGroup"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/bedrock-agentcore/runtimes/${local.runtime_name}-*"]
  }
  statement {
    sid       = "OwnMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }
}

resource "aws_iam_role_policy" "runtime_start" {
  name   = "start"
  role   = aws_iam_role.runtime.id
  policy = data.aws_iam_policy_document.runtime_start.json
}

# What a request needs: the model gateway's key from the token vault, for this runtime's workload
# identity only, and the tool gateway. AgentCore doesn't bind workload identities to credential
# providers itself; the role's Resource block is the binding.
data "aws_iam_policy_document" "runtime_requests" {
  # The provider's ARN is the one AgentCore authorizes against (token-vault/default/apikeycredentialprovider/
  # <name>, from the resource, not a guessed form): the first invocation's GetResourceApiKey was refused on
  # that ARN with no secretsmanager permission in question (CloudTrail, 2 November 2026).
  statement {
    sid     = "GatewayKeyFromTheVault"
    actions = ["bedrock-agentcore:GetResourceApiKey"]
    resources = [
      "${local.arn_prefix}:workload-identity-directory/default",
      aws_bedrockagentcore_agent_runtime.harness.workload_identity_details[0].workload_identity_arn,
      "${local.arn_prefix}:token-vault/default",
      aws_bedrockagentcore_api_key_credential_provider.model_gateway.credential_provider_arn,
    ]
  }
  # A provider with an external secret reads it with the caller's credentials: GetResourceApiKey was
  # refused "when retrieving the provided secret" until the runtime's role could read that one secret
  # (CloudTrail, 2 November 2026; the call arrives with invokedBy bedrock-agentcore.amazonaws.com). The
  # read is bound to the key's secret and to a service's call on the role's behalf: aws:CalledVia names
  # a short list of services AgentCore is not on, so the condition is aws:ViaAWSService.
  statement {
    sid       = "GatewayKeySecretThroughTheVault"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.gateway_key_secret_arn]
    condition {
      test     = "Bool"
      variable = "aws:ViaAWSService"
      values   = ["true"]
    }
  }
  statement {
    sid       = "ToolGatewayOnly"
    actions   = ["bedrock-agentcore:InvokeGateway"]
    resources = [aws_bedrockagentcore_gateway.tools.gateway_arn]
  }
}

resource "aws_iam_role_policy" "runtime_requests" {
  name   = "requests"
  role   = aws_iam_role.runtime.id
  policy = data.aws_iam_policy_document.runtime_requests.json
}

# --- the tool gateway's execution role --------------------------------------------------------------

data "aws_iam_policy_document" "tool_gateway_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["${local.arn_prefix}:gateway/*"]
    }
  }
}

resource "aws_iam_role" "tool_gateway" {
  name               = "${local.workflow}-tool-gateway"
  description        = "AgentCore Gateway for ${local.workflow}: evaluates the policy engine and reaches the MCP servers"
  assume_role_policy = data.aws_iam_policy_document.tool_gateway_trust.json
  depends_on         = [aws_budgets_budget.account]
}

# The three permissions AWS lists for a gateway with a policy engine; a token for the MCP servers
# from its own credential provider, signed with its own key through AgentCore Identity; and
# Larkspur's root CA, which the gateway reads when the pipeline registers it on a target.
# What CreateGateway checks before it makes the gateway: that the role can read the policy engine
# (the sandbox's first apply failed without it). The rest of the role's policy names the gateway's
# own workload identity, so it can only come after.
data "aws_iam_policy_document" "tool_gateway_start" {
  statement {
    sid       = "ReadTheEngine"
    actions   = ["bedrock-agentcore:GetPolicyEngine"]
    resources = [aws_bedrockagentcore_policy_engine.tools.policy_engine_arn]
  }
  statement {
    sid     = "Authorize"
    actions = ["bedrock-agentcore:AuthorizeAction", "bedrock-agentcore:PartiallyAuthorizeActions"]
    resources = [
      aws_bedrockagentcore_policy_engine.tools.policy_engine_arn,
      "${local.arn_prefix}:gateway/*",
    ]
  }
}

resource "aws_iam_role_policy" "tool_gateway_start" {
  name   = "policy-engine"
  role   = aws_iam_role.tool_gateway.id
  policy = data.aws_iam_policy_document.tool_gateway_start.json
}

data "aws_iam_policy_document" "tool_gateway" {
  statement {
    sid     = "TokenForTheMcpServers"
    actions = ["bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetResourceOauth2Token"]
    resources = [
      "${local.arn_prefix}:workload-identity-directory/default",
      aws_bedrockagentcore_gateway.tools.workload_identity_details[0].workload_identity_arn,
      "${local.arn_prefix}:token-vault/default",
      aws_bedrockagentcore_oauth2_credential_provider.tool_gateway.credential_provider_arn,
    ]
  }
  statement {
    sid       = "SignTheClientAssertion"
    actions   = ["kms:Sign", "kms:DescribeKey"]
    resources = [aws_kms_key.tool_gateway_signing.arn]
    condition {
      test     = "StringLike"
      variable = "kms:ViaService"
      values   = ["bedrock-agentcore-identity.*.amazonaws.com"]
    }
  }
  statement {
    sid       = "LarkspursRootCA"
    actions   = ["s3:GetObject"]
    resources = [local.private_ca_arn]
  }
}

resource "aws_iam_role_policy" "tool_gateway" {
  name   = "mcp-servers"
  role   = aws_iam_role.tool_gateway.id
  policy = data.aws_iam_policy_document.tool_gateway.json
}
