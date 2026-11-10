"""Policy checks on the chapter 7 Terraform: what the chapter says the deployment does, it does.

The configuration is validated, not applied (no Google Cloud account yet), so these tests read
the HCL. What only an apply can show, such as the roles Google grants an agent identity by
default, is a post-apply step in the README. The last test runs `terraform validate` when
Terraform and the providers are installed (`terraform init -backend=false` in labs/ch07/terraform).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import hcl2
import pytest

TF = Path(__file__).resolve().parent.parent / "terraform"


def clean(value: Any) -> Any:
    """python-hcl2 keeps HCL's quotes and adds bookkeeping keys; drop both."""
    if isinstance(value, dict):
        return {clean(k): clean(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def load() -> dict[str, Any]:
    merged: dict[str, Any] = {"resource": {}, "variable": {}, "locals": {}, "provider": {}}
    for path in sorted(TF.glob("*.tf")):
        with path.open(encoding="utf-8") as handle:
            parsed = clean(hcl2.load(handle))
        for block in parsed.get("resource", []):
            for kind, named in block.items():
                merged["resource"].setdefault(kind, {}).update(named)
        for block in parsed.get("variable", []):
            merged["variable"].update(block)
        for block in parsed.get("locals", []):
            merged["locals"].update(block)
        for block in parsed.get("provider", []):
            merged["provider"].update(block)
    return merged


CONFIG = load()
RESOURCES = CONFIG["resource"]
LOCALS = CONFIG["locals"]
ENGINE = RESOURCES["google_vertex_ai_reasoning_engine"]["harness"]
SPEC = ENGINE["spec"][0]
DEPLOYMENT = SPEC["deployment_spec"][0]
GATEWAY = RESOURCES["google_network_services_agent_gateway"]["egress"]
TEMPLATE = RESOURCES["google_network_services_agent_connectivity_template"]["egress"]
EXTENSION = RESOURCES["google_network_services_authz_extension"]["iap"]
AUTHZ = RESOURCES["google_network_security_authz_policy"]["egress"]
DENY = RESOURCES["google_iam_deny_policy"]["models_through_gateway"]["rules"][0]["deny_rule"][0]


def variable_default(name: str) -> Any:
    return CONFIG["variable"][name].get("default")


def test_the_agent_runs_under_an_identity_of_its_own() -> None:
    assert SPEC["identity_type"] == "AGENT_IDENTITY"
    assert "service_account" not in SPEC


def test_the_image_is_pinned_by_digest() -> None:
    assert SPEC["container_spec"][0]["image_uri"] == "${var.harness_image}"
    assert SPEC["container_spec"][0]["port"] == 8080
    rule = CONFIG["variable"]["harness_image"]["validation"][0]["condition"]
    assert "@sha256:" in rule


def test_the_adapter_method_is_declared_by_hand() -> None:
    methods = SPEC["class_methods"]
    assert 'name = "query"' in methods and '"message"' in methods


def test_the_image_gets_the_environment_its_entry_point_reads() -> None:
    env = {e["name"]: e["value"] for e in DEPLOYMENT["env"]}
    assert set(env) == {"RUNTIME", "GATEWAY_URL", "WORKFLOW", "MODEL_ALIAS", "DATA_CLASS", "MCP_URL",
                        "OTEL_EXPORTER_OTLP_ENDPOINT"}
    assert env["RUNTIME"] == "agent-runtime"  # the image serves Foundry too; this picks Google's route
    for name in ("gateway_url", "mcp_url", "otel_endpoint"):
        url = variable_default(name)
        assert url.startswith("https://") and ".internal" in url and "googleapis" not in url, name
    secret = DEPLOYMENT["secret_env"][0]
    assert secret["name"] == "GATEWAY_KEY"
    assert secret["secret_ref"][0]["version"] == "${var.gateway_key_version}"
    assert variable_default("gateway_key_version") is None, "no default, so never 'latest' by accident"


def test_every_outbound_call_goes_through_the_workflows_own_gateway() -> None:
    egress = DEPLOYMENT["agent_gateway_config"][0]["agent_to_anywhere_config"][0]
    assert egress["agent_gateway"] == "${google_network_services_agent_gateway.egress.id}"
    assert GATEWAY["google_managed"][0]["governed_access_path"] == "AGENT_TO_ANYWHERE"
    assert "agent_connectivity_template" in GATEWAY


def test_the_gateway_is_one_the_perimeter_can_enforce() -> None:
    """VPC Service Controls covers gateways created after 8 September 2026 whose template is ALL_TRAFFIC."""
    network = TEMPLATE["egress_network_config"][0]
    assert TEMPLATE["access_path"] == "AGENT_TO_ANYWHERE"
    assert network["vpc_egress"] == "ALL_TRAFFIC"
    assert network["tls_config"][0]["trust_config"] == "${var.trust_config}"


def test_iam_decides_at_the_gateway_and_fails_closed() -> None:
    assert EXTENSION["service"] == "iap.googleapis.com"
    assert EXTENSION["fail_open"] is False
    assert "DRY_RUN" in EXTENSION["metadata"] and "var.gateway_dry_run" in EXTENSION["metadata"]
    assert variable_default("gateway_dry_run") is True, "a new workflow's gateway starts audit-only"
    assert AUTHZ["action"] == "CUSTOM" and AUTHZ["policy_profile"] == "REQUEST_AUTHZ"
    assert AUTHZ["target"][0]["resources"] == ["${google_network_services_agent_gateway.egress.id}"]
    extension = AUTHZ["custom_provider"][0]["authz_extension"][0]["resources"]
    assert extension == ["${google_network_services_authz_extension.iap.id}"]


def test_the_essential_endpoints_cover_every_hostname_variant() -> None:
    apis = LOCALS["essential_apis"]
    assert {"aiplatform", "agentregistry", "secretmanager", "cloudtrace", "telemetry"} <= set(apis)
    endpoints = LOCALS["essential_endpoints"]
    for form in ("${api}.googleapis.com", "${api}.mtls.googleapis.com",
                 "${var.region}-aiplatform.googleapis.com", "aiplatform.${var.region}.rep.googleapis.com"):
        assert form in endpoints, form


def test_terraform_grants_the_agent_identity_nothing() -> None:
    project_grants = [k for k in RESOURCES if k.startswith("google_project_iam")]
    assert not project_grants
    members = [str(r.get("member", "")) for kind in RESOURCES.values() for r in kind.values()]
    assert not any("principal://agents" in m for m in members)


def test_only_the_model_gateway_may_send_a_prompt() -> None:
    assert set(DENY["denied_permissions"]) == {
        "aiplatform.googleapis.com/endpoints.predict",
        "aiplatform.googleapis.com/batchPredictionJobs.create",
        "aiplatform.googleapis.com/cachedContents.create",
        "aiplatform.googleapis.com/interactions.create",
        "aiplatform.googleapis.com/memories.generate",
    }
    assert DENY["denied_principals"] == ["principalSet://goog/public:all"]
    assert DENY["exception_principals"] == [
        "principal://iam.googleapis.com/projects/-/serviceAccounts/${var.model_gateway_service_account}",
        "principalSet://cloudresourcemanager.googleapis.com/${local.deny_scope_type}/${local.deny_scope_number}/type/ServiceAgent",
    ]


def test_the_deny_sits_on_the_agent_folder_or_the_sandbox_project() -> None:
    assert "folders" in LOCALS["deny_scope_type"] and "projects" in LOCALS["deny_scope_type"]
    assert variable_default("deny_folder_number") is None
    parent = RESOURCES["google_iam_deny_policy"]["models_through_gateway"]["parent"]
    assert "local.deny_scope_type" in parent and "local.deny_parent" in parent


def dependencies(body: dict[str, Any]) -> set[str]:
    return {re.sub(r"^\$\{|\}$", "", d) for d in body.get("depends_on", [])}


def test_the_budget_comes_first() -> None:
    """Only the two APIs the alarm needs, its channel and the budget come before the budget."""
    first = {"google_project_service.budget_apis", "google_monitoring_notification_channel.budget",
             "google_billing_budget.workflow"}
    graph = {f"{kind}.{name}": dependencies(body) for kind, named in RESOURCES.items() for name, body in named.items()}

    def reaches_budget(node: str, seen: frozenset[str] = frozenset()) -> bool:
        if node == "google_billing_budget.workflow":
            return True
        return any(reaches_budget(d, seen | {node}) for d in graph.get(node, set()) if d not in seen)

    for node in graph:
        if node not in first:
            assert reaches_budget(node), node


def test_memories_and_their_revisions_expire_on_the_manifest_schedule() -> None:
    bank = ENGINE["context_spec"][0]["memory_bank_config"][0]
    ttl = bank["ttl_config"][0]
    assert ttl["default_ttl"] == "${local.ttl}" and ttl["memory_revision_default_ttl"] == "${local.ttl}"
    assert LOCALS["ttl"] == "${var.memory_retention_days * 86400}s"


def test_memory_bank_models_are_pinned_to_ones_google_lists_for_canada() -> None:
    """A necessary pin, not a sufficient one: no Google page says Memory Bank honours it (README)."""
    bank = ENGINE["context_spec"][0]["memory_bank_config"][0]
    assert bank["generation_config"][0]["model"] == "${local.models}/gemini-3.5-flash"
    embedding = bank["similarity_search_config"][0]["embedding_model"]
    assert embedding == "${local.models}/text-multilingual-embedding-002"
    assert LOCALS["models"] == "projects/${var.project_id}/locations/${var.region}/publishers/google/models"
    assert variable_default("region") == "northamerica-northeast1"


def test_the_agent_carries_the_cost_labels() -> None:
    assert ENGINE["labels"] == {"workflow": "${var.workflow}", "owner": "${var.owner}"}


def test_the_runtime_is_sized_and_bounded() -> None:
    assert 1 <= DEPLOYMENT["min_instances"] <= DEPLOYMENT["max_instances"] <= 100
    cpu = int(DEPLOYMENT["resource_limits"]["cpu"])
    assert cpu in {1, 2, 4, 6, 8}
    assert DEPLOYMENT["container_concurrency"] == 2 * cpu + 1


def test_production_refuses_to_replace_the_agent() -> None:
    assert ENGINE["deletion_policy"] == "${var.deletion_policy}"
    assert variable_default("deletion_policy") == "PREVENT"
    text = (TF / "example.tfvars.txt").read_text(encoding="utf-8")
    assert re.search(r'deletion_policy\s*=\s*"FORCE"', text), "the sandbox example destroys cleanly"


def test_the_budget_api_works_with_user_credentials() -> None:
    provider = CONFIG["provider"]["google"]
    assert provider["billing_project"] == "${var.project_id}" and provider["user_project_override"] is True


def test_the_example_values_pass_the_image_rule() -> None:
    text = (TF / "example.tfvars.txt").read_text(encoding="utf-8")
    image = re.search(r'harness_image\s*=\s*"([^"]+)"', text)
    assert image and re.search(r"@sha256:[0-9a-f]{64}$", image.group(1))


@pytest.mark.skipif(not shutil.which("terraform") or not (TF / ".terraform").exists(),
                    reason="needs terraform and `terraform init -backend=false` in labs/ch07/terraform")
def test_terraform_validate() -> None:
    result = subprocess.run(["terraform", "validate", "-no-color"], cwd=TF, capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stdout + result.stderr
