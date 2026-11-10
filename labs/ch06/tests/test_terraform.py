"""Policy checks on the chapter 6 Terraform: what the chapter says the deployment does, it does.

Validated, not applied, so these tests read the HCL. The last one runs `terraform validate` when
Terraform and the provider are installed (`terraform init -backend=false` in labs/ch06/terraform).
The manifest-to-roles module has its own tests, which plan it (test_manifest_roles.py).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import hcl2
import pytest

LAB = Path(__file__).resolve().parent.parent
TF = LAB / "terraform"


def clean(value: Any) -> Any:
    """python-hcl2 keeps HCL's quotes and adds bookkeeping keys; drop both."""
    if isinstance(value, dict):
        return {clean(k): clean(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def load() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    resources: dict[str, dict[str, Any]] = {}
    data: dict[str, dict[str, Any]] = {}
    variables: dict[str, Any] = {}
    locals_: dict[str, Any] = {}
    for path in sorted(TF.glob("*.tf")):
        with path.open(encoding="utf-8") as handle:
            parsed = clean(hcl2.load(handle))
        for block in parsed.get("resource", []):
            for kind, named in block.items():
                resources.setdefault(kind, {}).update(named)
        for block in parsed.get("data", []):
            for kind, named in block.items():
                data.setdefault(kind, {}).update(named)
        for block in parsed.get("variable", []):
            variables.update(block)
        for block in parsed.get("locals", []):
            locals_.update(block)
    return resources, data, variables, locals_


RESOURCES, DATA, VARIABLES, LOCALS = load()
RUNTIME = RESOURCES["aws_bedrockagentcore_agent_runtime"]["harness"]
GATEWAY = RESOURCES["aws_bedrockagentcore_gateway"]["tools"]
BUDGET = "aws_budgets_budget.account"


def statements(document: dict[str, Any]) -> list[dict[str, Any]]:
    return document.get("statement", [])


def actions(document: dict[str, Any], effect: str = "Allow") -> set[str]:
    return {a for s in statements(document) if s.get("effect", "Allow") == effect for a in s["actions"]}


def test_the_provider_is_pinned_and_the_region_is_canadian_unless_the_data_is_synthetic() -> None:
    text = (TF / "versions.tf").read_text(encoding="utf-8")
    assert re.search(r'version\s*=\s*"6\.71\.0"', text)
    assert VARIABLES["region"]["default"] == "ca-central-1"
    condition = VARIABLES["region"]["validation"][0]["condition"]
    assert condition == '${var.region == "ca-central-1" || var.synthetic_data}'
    assert VARIABLES["synthetic_data"]["default"] is False  # a real deployment never sets it


def test_the_budget_comes_first() -> None:
    """Every resource that refers to nothing else in this configuration waits for the budget."""
    for kind, named in RESOURCES.items():
        for name, body in named.items():
            if f"{kind}.{name}" == BUDGET:
                continue
            text = json.dumps(body)
            refers = re.search(r"\$\{(aws_[a-z0-9_]+\.[a-z0-9_]+|module\.)", text)
            if not refers:
                assert BUDGET in str(body.get("depends_on")), f"{kind}.{name} doesn't depend on the budget"
    budget = RESOURCES["aws_budgets_budget"]["account"]
    (alarms,) = [d["notification"] for d in budget["dynamic"] if "notification" in d]
    assert alarms["for_each"] == '${var.budget_alert_email == "" ? [] : local.budget_alarms}'
    thresholds = sorted((a["type"], a["threshold"]) for a in LOCALS["budget_alarms"])
    assert thresholds == [("ACTUAL", 80), ("ACTUAL", 100), ("FORECASTED", 100)]
    assert VARIABLES["budget_alert_email"]["default"] == ""  # D-029: a free plan's credits cap the spend
    assert VARIABLES["monthly_budget_usd"]["default"] == 150  # D-018's cap for the lab account


def test_the_runtime_is_v1_in_the_vpc_behind_entra_with_short_sessions() -> None:
    assert RUNTIME["platform_version"] == "V1"  # V2 isn't offered in Canada
    network = RUNTIME["network_configuration"][0]
    assert network["network_mode"] == "VPC"
    jwt = RUNTIME["authorizer_configuration"][0]["custom_jwt_authorizer"][0]
    assert jwt["discovery_url"] == "${local.entra_oidc}"
    assert LOCALS["entra_oidc"].startswith("https://login.microsoftonline.com/${var.entra_tenant_id}/v2.0/")
    # A v2.0 token's audience is the app's client ID; Entra issues no client_id claim, so the caller is azp.
    assert jwt["allowed_audience"] == ["${var.entra_runtime_client_id}"] and "allowed_clients" not in jwt
    claim = jwt["custom_claim"][0]
    assert (claim["inbound_token_claim_name"], claim["inbound_token_claim_value_type"]) == ("azp", "STRING")
    match = claim["authorizing_claim_match_value"][0]
    assert match["claim_match_operator"] == "EQUALS"
    assert match["claim_match_value"][0]["match_value_string"] == "${var.entra_bot_client_id}"
    assert RUNTIME["request_header_configuration"][0]["request_header_allowlist"] == ["Authorization"]
    life = RUNTIME["lifecycle_configuration"][0]
    assert (life["idle_runtime_session_timeout"], life["max_lifetime"]) == (900, 3600)
    assert RUNTIME["agent_runtime_artifact"][0]["container_configuration"][0]["container_uri"] == "${var.image_uri}"
    assert "@sha256:" in json.dumps(VARIABLES["image_uri"]["validation"])


def test_no_secret_is_in_the_runtimes_environment() -> None:
    env = RUNTIME["environment_variables"]
    assert "GATEWAY_KEY" not in env
    assert env["GATEWAY_KEY_PROVIDER"] == "${local.key_provider}"
    assert "aws_bedrockagentcore_api_key_credential_provider.model_gateway.name" in (TF / "runtime.tf").read_text(encoding="utf-8")
    provider = RESOURCES["aws_bedrockagentcore_api_key_credential_provider"]["model_gateway"]
    assert provider["api_key_secret_source"] == "EXTERNAL" and "api_key" not in provider  # never in the state
    assert (env["MCP_AUTH"], env["DATA_CLASS"], env["MODEL_ALIAS"]) == ("sigv4", "${local.data_class}", "${local.model_alias}")
    # Until the harness classifies each call, every call carries the manifest's highest class.
    assert LOCALS["data_class"] == "${local.manifest.data_class_max}"
    assert "restricted   = \"larkspur-chat-restricted\"" in (TF / "main.tf").read_text(encoding="utf-8")


def test_the_harness_role_can_reach_the_tool_gateway_and_the_vault_and_no_model() -> None:
    role = RESOURCES["aws_iam_role"]["runtime"]
    assert role["permissions_boundary"] == "${aws_iam_policy.agent_boundary.arn}"
    trust = statements(DATA["aws_iam_policy_document"]["runtime_trust"])[0]
    assert trust["principals"][0]["identifiers"] == ["bedrock-agentcore.amazonaws.com"]
    conditions = {(c["test"], c["variable"]) for c in trust["condition"]}
    assert conditions == {("StringEquals", "aws:SourceAccount"), ("ArnLike", "aws:SourceArn")}
    granted = actions(DATA["aws_iam_policy_document"]["runtime_start"]) | actions(DATA["aws_iam_policy_document"]["runtime_requests"])
    assert not [a for a in granted if a.startswith("bedrock:")], "model calls go through the model gateway"
    requests = {s["sid"]: s for s in statements(DATA["aws_iam_policy_document"]["runtime_requests"])}
    assert requests["ToolGatewayOnly"]["resources"] == ["${aws_bedrockagentcore_gateway.tools.gateway_arn}"]
    vault = requests["GatewayKeyFromTheVault"]["resources"]
    # The provider's own ARN (token-vault/default/apikeycredentialprovider/<name>), never a guessed form: the
    # first invocation was refused on exactly that resource.
    assert "${aws_bedrockagentcore_api_key_credential_provider.model_gateway.credential_provider_arn}" in vault
    assert not any("api-key/" in r for r in vault)
    # The vault reads an external secret as the caller, so the runtime may read that one secret, through
    # the vault's call only; the tool roles keep the never-list's deny on every secret read.
    secret = requests["GatewayKeySecretThroughTheVault"]
    assert secret["actions"] == ["secretsmanager:GetSecretValue"] and secret["resources"] == ["${var.gateway_key_secret_arn}"]
    assert secret["condition"][0]["variable"] == "aws:ViaAWSService"  # AgentCore is not on aws:CalledVia's list
    assert "*" not in vault


def test_the_boundary_denies_model_calls_chaining_and_switching_the_policy_engine_off() -> None:
    boundary = DATA["aws_iam_policy_document"]["agent_boundary"]
    denied = actions(boundary, "Deny")
    assert {"bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "sts:AssumeRole", "iam:*",
            "bedrock-agentcore:UpdateGateway", "bedrock-agentcore:GetWorkloadAccessTokenForUserId"} <= denied
    assert not [a for a in actions(boundary) if a.endswith(":*") or a == "*"], "the ceiling names actions"
    module = (TF / "tools.tf").read_text(encoding="utf-8")
    assert "permissions_boundary_arn = aws_iam_policy.agent_boundary.arn" in module


def test_the_tool_gateway_authorizes_with_iam_and_enforces_its_policy_engine() -> None:
    assert (GATEWAY["authorizer_type"], GATEWAY["protocol_type"]) == ("AWS_IAM", "MCP")
    engine = GATEWAY["policy_engine_configuration"][0]
    assert engine == {"arn": "${aws_bedrockagentcore_policy_engine.tools.policy_engine_arn}", "mode": "ENFORCE"}
    target = RESOURCES["aws_bedrockagentcore_gateway_target"]["mcp"]
    assert "managed_vpc_resource" in target["private_endpoint"][0]  # the MCP servers stay private
    assert target["metadata_configuration"][0]["allowed_request_headers"] == ["X-Larkspur-Actor"]
    policy = RESOURCES["aws_bedrockagentcore_policy"]["invoke"]
    assert policy["for_each"] == "${module.workflow_identities.cedar_permits}"
    assert policy["validation_mode"] == "FAIL_ON_ANY_FINDINGS"
    gateway_role = actions(DATA["aws_iam_policy_document"]["tool_gateway_start"]) | actions(
        DATA["aws_iam_policy_document"]["tool_gateway"])
    assert gateway_role == {"bedrock-agentcore:GetPolicyEngine", "bedrock-agentcore:AuthorizeAction",  # AWS's three
                            "bedrock-agentcore:PartiallyAuthorizeActions",
                            "bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetResourceOauth2Token",
                            "kms:Sign", "kms:DescribeKey",  # the token for the MCP servers
                            "s3:GetObject"}  # Larkspur's root CA


def test_the_endpoints_cover_what_agentcore_needs_without_internet() -> None:
    endpoints = set(LOCALS["interface_endpoints"])
    assert {"ecr.api", "ecr.dkr", "logs"} <= endpoints  # AWS's list for a runtime in a VPC
    assert {"bedrock-agentcore", "bedrock-agentcore.gateway", "sts", "bedrock-runtime", "bedrock-agent-runtime"} <= endpoints
    runtime_policy = json.dumps(LOCALS["endpoint_policies"]["bedrock-runtime"])
    assert "var.model_gateway_role_arn" in runtime_policy  # only the model gateway reaches the models
    s3 = RESOURCES["aws_vpc_endpoint"]["s3"]
    assert s3["vpc_endpoint_type"] == "Gateway" and "starport-layer-bucket" in json.dumps(s3["policy"])
    assert "ca-central-1: cac1-az1, cac1-az2, cac1-az4" in VARIABLES["subnet_ids"]["description"]
    assert "us-east-2: use2-az1, use2-az2, use2-az3" in VARIABLES["subnet_ids"]["description"]


def test_the_knowledge_base_is_customer_managed_and_embeds_in_its_region() -> None:
    kb = RESOURCES["aws_bedrockagent_knowledge_base"]["runbooks"]
    assert kb["knowledge_base_configuration"][0]["type"] == "VECTOR"
    assert kb["storage_configuration"][0]["type"] == "S3_VECTORS"
    assert LOCALS["embedding_model_arn"] == "arn:aws:bedrock:${var.region}::foundation-model/amazon.titan-embed-text-v2:0"
    source = RESOURCES["aws_bedrockagent_data_source"]["runbooks"]
    assert "parsing_configuration" not in json.dumps(source["vector_ingestion_configuration"])  # the default parser
    chunking = source["vector_ingestion_configuration"][0]["chunking_configuration"][0]
    assert chunking["chunking_strategy"] == "FIXED_SIZE"
    index = RESOURCES["aws_s3vectors_index"]["runbooks"]
    assert (index["dimension"], index["distance_metric"], index["data_type"]) == (1024, "cosine", "float32")


def test_the_guardrail_is_standard_tier_evaluated_in_canada_and_starts_in_detect_mode() -> None:
    guardrail = RESOURCES["aws_bedrock_guardrail"]["workflow"]
    profile = guardrail["cross_region_config"][0]["guardrail_profile_identifier"]
    assert profile.endswith(":guardrail-profile/${local.guardrail_profile}")
    # ca-central-1 maps to the Canada profile; a synthetic run in us-east-2 to the US one.
    assert LOCALS["guardrail_profile"] == '${local.guardrail_geography[split("-", var.region)[0]]}.guardrail.v1:0'
    assert LOCALS["guardrail_geography"]["ca"] == "ca" and LOCALS["guardrail_geography"]["us"] == "us"
    assert guardrail["content_policy_config"][0]["tier_config"][0]["tier_name"] == "STANDARD"
    assert VARIABLES["guardrail_mode"]["default"] == "detect"
    assert LOCALS["guardrail_action"] == '${var.guardrail_mode == "block" ? "BLOCK" : "NONE"}'
    assert RESOURCES["aws_bedrock_guardrail_version"]["workflow"]["skip_destroy"] is True


def test_the_gateways_role_can_read_its_policy_engine_before_the_gateway_exists() -> None:
    """CreateGateway checks GetPolicyEngine on the gateway's role first; the sandbox's first apply failed on it."""
    start = actions(DATA["aws_iam_policy_document"]["tool_gateway_start"])
    assert "bedrock-agentcore:GetPolicyEngine" in start
    assert "aws_bedrockagentcore_gateway" not in json.dumps(DATA["aws_iam_policy_document"]["tool_gateway_start"])
    assert "aws_iam_role_policy.tool_gateway_start" in str(GATEWAY["depends_on"])


def test_every_security_group_description_is_one_ec2_accepts() -> None:
    """EC2 takes a-zA-Z0-9, spaces and ._-:/()#,@[]+=&;{}!$* only; the first apply refused an apostrophe."""
    allowed = re.compile(r"^[a-zA-Z0-9. _\-:/()#,@\[\]+=&;{}!$*]{0,255}$")
    for name, group in RESOURCES["aws_security_group"].items():
        assert allowed.match(group["description"]), name


def test_the_runtime_and_the_tool_gateway_take_calls_through_larkspurs_endpoints_only() -> None:
    policies = RESOURCES["aws_bedrockagentcore_resource_policy"]
    runtime = json.dumps(policies["runtime"]["policy"])
    assert "InvokeAgentRuntime" in runtime and "aws:SourceVpce" in runtime and "local.agentcore_endpoint" in runtime
    gateway = json.dumps(policies["tool_gateway"]["policy"])
    assert "StringNotEquals" in gateway and "local.gateway_endpoint" in gateway and "aws_iam_role.runtime.arn" in gateway
    endpoint = RESOURCES["aws_bedrockagentcore_agent_runtime_endpoint"]["live"]
    assert endpoint["agent_runtime_version"] == "${aws_bedrockagentcore_agent_runtime.harness.agent_runtime_version}"


def test_the_harness_reaches_named_security_groups_not_the_whole_vpc() -> None:
    egress = LOCALS["runtime_egress"]
    assert set(egress) == {"endpoints", "model_gateway", "collector"}
    for kind in ("runtime", "tool_gateway_https"):
        assert "cidr_ipv4" not in RESOURCES["aws_vpc_security_group_egress_rule"][kind], kind
    # The one egress beyond the named groups: S3's prefix list, for the image layers through the gateway
    # endpoint, which has no group (the first invocation timed out on the pull without it).
    s3 = RESOURCES["aws_vpc_security_group_egress_rule"]["runtime_s3"]
    assert s3["prefix_list_id"] == "${aws_vpc_endpoint.s3.prefix_list_id}" and "cidr_ipv4" not in s3
    assert (s3["from_port"], s3["to_port"]) == (443, 443)
    assert VARIABLES["otel_collector_endpoint"]["validation"][0]["condition"].startswith("${startswith(")


def test_the_tool_gateway_authenticates_to_its_servers_with_a_key_that_never_leaves_kms() -> None:
    provider = RESOURCES["aws_bedrockagentcore_oauth2_credential_provider"]["tool_gateway"]
    custom = provider["oauth2_provider_config"][0]["custom_oauth2_provider_config"][0]
    assert (provider["credential_provider_vendor"], custom["client_authentication_method"]) == ("CustomOauth2", "PRIVATE_KEY_JWT")
    assert "client_secret" not in json.dumps(custom)
    jwt = custom["private_key_jwt_config"][0]
    assert jwt["signing_algorithm"] == "RS256" and "x5t#S256" in jwt["additional_header_claims"]
    key = RESOURCES["aws_kms_key"]["tool_gateway_signing"]
    assert (key["key_usage"], key["customer_master_key_spec"]) == ("SIGN_VERIFY", "RSA_2048")
    oauth = RESOURCES["aws_bedrockagentcore_gateway_target"]["mcp"]["credential_provider_configuration"][0]["oauth"][0]
    assert (oauth["grant_type"], oauth["scopes"]) == ("CLIENT_CREDENTIALS", ["${var.mcp_servers_scope}"])
    role = {s["sid"]: s for s in statements(DATA["aws_iam_policy_document"]["tool_gateway"])}
    assert role["SignTheClientAssertion"]["condition"][0]["values"] == ["bedrock-agentcore-identity.*.amazonaws.com"]
    assert role["LarkspursRootCA"]["resources"] == ["${local.private_ca_arn}"]


def test_the_stores_fixed_at_creation_get_the_workflows_key_and_the_logs_a_retention() -> None:
    vectors = RESOURCES["aws_s3vectors_vector_bucket"]["runbooks"]["encryption_configuration"][0]
    assert (vectors["sse_type"], vectors["kms_key_arn"]) == ("aws:kms", "${aws_kms_key.workflow.arn}")
    corpus = RESOURCES["aws_s3_bucket_server_side_encryption_configuration"]["corpus"]["rule"][0]
    assert corpus["apply_server_side_encryption_by_default"][0]["kms_master_key_id"] == "${aws_kms_key.workflow.arn}"
    index = RESOURCES["aws_s3vectors_index"]["runbooks"]["metadata_configuration"][0]
    assert set(index["non_filterable_metadata_keys"]) == {"AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"}
    for name, group in RESOURCES["aws_cloudwatch_log_group"].items():
        assert (group["retention_in_days"], group["kms_key_id"]) == (400, "${aws_kms_key.workflow.arn}"), name
    knowledge = {s["sid"]: s for s in statements(DATA["aws_iam_policy_document"]["knowledge"])}
    assert knowledge["ListTheRunbooksOnly"]["condition"][0]["values"] == ["runbooks/*"]
    assert knowledge["ReadTheCorpus"]["resources"] == ["${aws_s3_bucket.corpus.arn}/runbooks/*"]


def test_invocation_logging_keeps_prompts_out_when_the_manifest_does() -> None:
    config = RESOURCES["aws_bedrock_model_invocation_logging_configuration"]["account"]["logging_config"][0]
    assert config["text_data_delivery_enabled"] == "${local.manifest.trace_content}"
    assert config["cloudwatch_config"][0]["log_group_name"] == "${aws_cloudwatch_log_group.invocations.name}"


@pytest.mark.skipif(shutil.which("terraform") is None or not (TF / ".terraform").exists(),
                    reason="needs terraform and `terraform init -backend=false` in labs/ch06/terraform")
def test_terraform_validate() -> None:
    result = subprocess.run(["terraform", "validate", "-json"], cwd=TF, capture_output=True, text=True, timeout=300)
    report = json.loads(result.stdout)
    assert report["valid"], report["diagnostics"]
