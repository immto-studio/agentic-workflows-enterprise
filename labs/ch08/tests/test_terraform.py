"""Policy checks on the chapter 8 Terraform: what the chapter says the deployment does, it does.

Validated, not applied (no Azure subscription yet), so these tests read the HCL. The last one
runs `terraform validate` when Terraform and the providers are installed (`terraform init
-backend=false` in labs/ch08/terraform). The model register and the cost sheet have their own
tests (test_models_and_costs.py).
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

# Built-in roles by ID, scoped to the subscription as azurerm keeps them (see foundry.tf).
ROLE_DEFINITIONS = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/"
OPENAI_USER = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"  # Azure built-in roles for AI + machine learning, 2026-07-01
REPOSITORY_READER = "b93aa761-3e63-49ed-ac28-beffa264f7ac"  # Azure built-in roles for Containers, 2026-07-01


def clean(value: Any) -> Any:
    """python-hcl2 keeps HCL's quotes and adds bookkeeping keys; drop both."""
    if isinstance(value, dict):
        return {clean(k): clean(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def load() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    resources: dict[str, dict[str, Any]] = {}
    variables: dict[str, Any] = {}
    for path in sorted(TF.glob("*.tf")):
        with path.open(encoding="utf-8") as handle:
            parsed = clean(hcl2.load(handle))
        for block in parsed.get("resource", []):
            for kind, named in block.items():
                resources.setdefault(kind, {}).update(named)
        for block in parsed.get("variable", []):
            variables.update(block)
    return resources, variables


RESOURCES, VARIABLES = load()
AGENTS = RESOURCES["azurerm_cognitive_account"]["agents"]
MODELS = RESOURCES["azurerm_cognitive_account"]["models"]
CHAT = RESOURCES["azurerm_cognitive_deployment"]["chat"]


def default(name: str) -> Any:
    return VARIABLES[name].get("default")


def test_the_agents_account_is_private_keyless_and_injected_at_creation() -> None:
    assert AGENTS["kind"] == "AIServices" and AGENTS["project_management_enabled"] is True
    assert AGENTS["local_auth_enabled"] is False and AGENTS["public_network_access_enabled"] is False
    injection = AGENTS["network_injection"][0]
    assert injection == {"scenario": "agent", "subnet_id": "${var.agent_subnet_id}"}


def test_terraform_refuses_to_replace_the_agents_account_or_the_project() -> None:
    """Replacing the account takes every project, agent and identity in it; the README's teardown
    lifts the guard by hand, because prevent_destroy takes no variable."""
    project = RESOURCES["azurerm_cognitive_account_project"]["workflow"]
    for body in (AGENTS, project):
        assert body["lifecycle"] == [{"prevent_destroy": True}], body["name"]


def test_the_agents_account_holds_no_model_deployment() -> None:
    accounts = {d["cognitive_account_id"] for d in RESOURCES["azurerm_cognitive_deployment"].values()}
    assert accounts == {"${azurerm_cognitive_account.models.id}"}


def test_policy_denies_model_deployments_in_the_agents_account() -> None:
    rule = RESOURCES["azurerm_policy_definition"]["no_model_deployments"]["policy_rule"]
    compact = re.sub(r"\s+", " ", rule)
    assert 'field = "type", equals = "Microsoft.CognitiveServices/accounts/deployments"' in compact
    assert 'effect = "deny"' in compact
    assignment = RESOURCES["azurerm_resource_policy_assignment"]["agents_account"]
    assert assignment["resource_id"] == "${azurerm_cognitive_account.agents.id}"


def test_policy_allows_only_deployments_that_stay_in_the_geography_in_the_models_account() -> None:
    """The grid as structure: Global and Data Zone deployments can't be created, whatever their name."""
    rule = re.sub(r"\s+", " ", RESOURCES["azurerm_policy_definition"]["in_geography_deployments_only"]["policy_rule"])
    assert 'allOf = [{field = "type", equals = "Microsoft.CognitiveServices/accounts/deployments"}, ' in rule
    assert ('{field = "Microsoft.CognitiveServices/accounts/deployments/sku.name", '
            'notIn = ["Standard", "ProvisionedManaged"]}]') in rule
    assert 'then = {effect = "deny"}' in rule
    assignment = RESOURCES["azurerm_resource_policy_assignment"]["models_account"]
    assert assignment["resource_id"] == "${azurerm_cognitive_account.models.id}"
    assert assignment["policy_definition_id"] == "${azurerm_policy_definition.in_geography_deployments_only.id}"
    assert CHAT["sku"][0]["name"] in ("Standard", "ProvisionedManaged")  # the policy admits the lab's own


def test_only_the_model_gateway_may_call_the_models() -> None:
    assert MODELS["local_auth_enabled"] is False and MODELS["public_network_access_enabled"] is False
    grants = [r for r in RESOURCES["azurerm_role_assignment"].values()
              if r["scope"] == "${azurerm_cognitive_account.models.id}"]
    assert len(grants) == 1
    assert grants[0]["principal_id"] == "${var.gateway_principal_id}"
    assert grants[0]["role_definition_id"] == ROLE_DEFINITIONS + OPENAI_USER  # Cognitive Services OpenAI User


def test_the_chat_model_is_a_standard_deployment_in_canada() -> None:
    assert MODELS["location"] == "${var.model_location}" and default("model_location") == "canadaeast"
    assert CHAT["sku"][0]["name"] == "Standard", "Global and Data Zone deployments may process outside Canada"
    assert CHAT["version_upgrade_option"] == "NoAutoUpgrade"
    assert CHAT["rai_policy_name"] == "Microsoft.DefaultV2"


def test_the_project_identity_is_user_assigned_from_the_start_and_pulls_images() -> None:
    project = RESOURCES["azurerm_cognitive_account_project"]["workflow"]
    assert project["identity"][0]["type"] == "UserAssigned"
    pull = RESOURCES["azurerm_role_assignment"]["project_pulls_images"]
    assert pull["role_definition_id"] == ROLE_DEFINITIONS + REPOSITORY_READER  # Container Registry Repository Reader
    assert pull["scope"] == "${azurerm_container_registry.agents.id}"
    assert pull["principal_id"] == "${azurerm_user_assigned_identity.project.principal_id}"
    registry = RESOURCES["azurerm_container_registry"]["agents"]
    assert registry["admin_enabled"] is False and registry["public_network_access_enabled"] is False


def test_the_registry_takes_foundrys_arm_audience_tokens_in_the_pull_roles_mode() -> None:
    """Foundry pulls with ARM-audience tokens, so the setting is stated rather than left to the default;
    Microsoft's built-in policy that turns it off needs an exemption for this registry."""
    registry = RESOURCES["azurerm_container_registry"]["agents"]
    assert registry["azuread_authentication_as_arm_policy_enabled"] is True
    assert registry["role_assignment_mode"] == "AbacRepositoryPermissions"  # where Repository Reader is listed


def test_roles_are_assigned_by_id_scoped_to_the_subscription() -> None:
    """A role's name can change and its ID can't; any other form of the ID would replace the grant."""
    guid = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    for name, grant in RESOURCES["azurerm_role_assignment"].items():
        assert "role_definition_name" not in grant, name
        assert re.fullmatch(re.escape(ROLE_DEFINITIONS) + guid, grant["role_definition_id"]), name


def test_every_account_and_the_registry_has_a_private_endpoint() -> None:
    targets = {e["private_service_connection"][0]["private_connection_resource_id"]
               for e in RESOURCES["azurerm_private_endpoint"].values()}
    assert targets == {"${azurerm_cognitive_account.agents.id}", "${azurerm_cognitive_account.models.id}",
                       "${azurerm_container_registry.agents.id}"}


def test_the_models_account_logs_requests_to_the_workspace() -> None:
    setting = RESOURCES["azurerm_monitor_diagnostic_setting"]["models"]
    assert {log["category"] for log in setting["enabled_log"]} == {"Audit", "RequestResponse",
                                                                   "AzureOpenAIRequestUsage"}


def test_the_agents_account_logs_to_the_workspace() -> None:
    setting = RESOURCES["azurerm_monitor_diagnostic_setting"]["agents"]
    assert setting["target_resource_id"] == "${azurerm_cognitive_account.agents.id}"
    assert setting["log_analytics_workspace_id"] == "${azurerm_log_analytics_workspace.workflow.id}"
    assert {log["category"] for log in setting["enabled_log"]} == {"Audit", "RequestResponse"}


def references(body: Any) -> set[str]:
    return set(re.findall(r"\b(azurerm_[a-z_]+\.[a-z_]+)\b", json.dumps(body)))


def test_the_budget_comes_first() -> None:
    """Only the resource group the budget watches comes before it; everything else reaches it."""
    graph = {f"{kind}.{name}": references(body) for kind, named in RESOURCES.items() for name, body in named.items()}
    budget = "azurerm_consumption_budget_resource_group.workflow"

    def reaches(node: str, seen: frozenset[str] = frozenset()) -> bool:
        if node == budget:
            return True
        return any(reaches(d, seen | {node}) for d in graph.get(node, set()) if d in graph and d not in seen)

    for node in graph:
        if node not in {budget, "azurerm_resource_group.workflow"}:
            assert reaches(node), node


def test_the_budget_needs_an_address_because_azure_refuses_one_without_a_notification() -> None:
    """Found at the sandbox apply of 2026-11-02: "Insufficient notification blocks"."""
    budget = RESOURCES["azurerm_consumption_budget_resource_group"]["workflow"]
    thresholds = sorted((n["threshold_type"], n["threshold"]) for n in budget["notification"])
    assert thresholds == [("Actual", 80), ("Forecasted", 100)]
    assert "default" not in VARIABLES["budget_alert_emails"]
    assert VARIABLES["budget_alert_emails"]["validation"][0]["condition"] == "${length(var.budget_alert_emails) >= 1}"


def test_every_resource_carries_the_cost_tags_where_azure_takes_them() -> None:
    untaggable = {"azurerm_consumption_budget_resource_group", "azurerm_role_assignment", "azurerm_policy_definition",
                  "azurerm_resource_policy_assignment", "azurerm_monitor_diagnostic_setting",
                  "azurerm_cognitive_deployment"}
    for kind, named in RESOURCES.items():
        if kind in untaggable:
            continue
        for name, body in named.items():
            assert body.get("tags") == "${local.tags}", f"{kind}.{name}"


@pytest.mark.skipif(not shutil.which("terraform") or not (TF / ".terraform").exists(),
                    reason="needs terraform and `terraform init -backend=false` in labs/ch08/terraform")
def test_terraform_validate() -> None:
    result = subprocess.run(["terraform", "validate", "-no-color"], cwd=TF, capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stdout + result.stderr
