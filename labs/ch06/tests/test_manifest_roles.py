"""The manifest-to-roles module, planned: a manifest and the tool catalog in, roles and Cedar permits out.

Chapter 6, keeping chapter 4's promise. Each test writes a small root module that calls
terraform/modules/manifest_roles with fixed ARNs and plans it with placeholder credentials and
-refresh=false, so no request reaches AWS. The provider comes from the lab's own
`terraform init` (`-plugin-dir`), so these tests skip until that has run, as the validate test does.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

LAB = Path(__file__).resolve().parent.parent
TF = LAB / "terraform"
MODULE = TF / "modules" / "manifest_roles"
PROVIDERS = TF / ".terraform" / "providers"
W3 = LAB / "manifests" / "w3-incident.yaml"
W2 = LAB.parent / "ch05" / "manifest" / "w2-ops-assistant.yaml"
CATALOG = LAB / "catalog" / "tools.yaml"

ACCOUNT = "111122223333"
VARS = {
    "account_id": ACCOUNT,
    "region": "ca-central-1",
    "cluster_arn": f"arn:aws:eks:ca-central-1:{ACCOUNT}:cluster/ops",
    "knowledge_base_arn": f"arn:aws:bedrock:ca-central-1:{ACCOUNT}:knowledge-base/RUNBOOKS01",
    "k8s_mcp_role_arn": f"arn:aws:iam::{ACCOUNT}:role/k8s-mcp-server",
    "knowledge_mcp_role_arn": f"arn:aws:iam::{ACCOUNT}:role/knowledge-mcp-server",
}
BOUNDARY = f"arn:aws:iam::{ACCOUNT}:policy/w3-incident-agent-boundary"
GATEWAY = f"arn:aws:bedrock-agentcore:ca-central-1:{ACCOUNT}:gateway/w3-incident-tools-a1b2c3d4e5"

pytestmark = pytest.mark.skipif(shutil.which("terraform") is None or not PROVIDERS.exists(),
                                reason="needs terraform and `terraform init -backend=false` in labs/ch06/terraform")

ROOT = """terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "6.71.0"
    }}
  }}
}}

provider "aws" {{
  region                      = "ca-central-1"
  access_key                  = "AKIAIOSFODNN7EXAMPLE"
  secret_key                  = "placeholder-secret-for-an-offline-plan"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}}

module "roles" {{
  source                   = "./modules/manifest_roles"
  manifest                 = yamldecode(file("manifest.yaml"))
  catalog                  = yamldecode(file("catalog.yaml"))
  permissions_boundary_arn = "{boundary}"
  workflow_role_arn        = "arn:aws:iam::{account}:role/{workflow}-harness"
  gateway_arn              = "{gateway}"
  eks_cluster_name         = "ops"
  person_domain            = "larkspur.example"
  template_vars            = {vars}
}}

output "cedar_permits" {{
  value = module.roles.cedar_permits
}}

output "never_actions" {{
  value = module.roles.never_actions
}}
"""


def plan(work: Path, manifest: dict[str, Any], catalog: dict[str, Any] | None = None) -> subprocess.CompletedProcess[str]:
    """Plan the module for `manifest` in `work`; the plan's JSON is in work/plan.json when it succeeds."""
    shutil.copytree(MODULE, work / "modules" / "manifest_roles")
    (work / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (work / "catalog.yaml").write_text(yaml.safe_dump(catalog or yaml.safe_load(CATALOG.read_text(encoding="utf-8"))),
                                       encoding="utf-8")
    hcl_vars = "{\n" + "".join(f'    {k} = "{v}"\n' for k, v in VARS.items()) + "  }"
    (work / "main.tf").write_text(ROOT.format(boundary=BOUNDARY, account=ACCOUNT, workflow=manifest["workflow"],
                                              gateway=GATEWAY, vars=hcl_vars), encoding="utf-8")
    env = {"TF_IN_AUTOMATION": "1", "AWS_SHARED_CREDENTIALS_FILE": str(work / "none"),
           "AWS_CONFIG_FILE": str(work / "none")}
    run = lambda *args: subprocess.run(["terraform", *args], cwd=work, capture_output=True, text=True,  # noqa: E731
                                       timeout=600, env={**__import__("os").environ, **env})
    init = run("init", "-backend=false", "-input=false", f"-plugin-dir={PROVIDERS}")
    assert init.returncode == 0, init.stderr
    result = run("plan", "-refresh=false", "-input=false", "-no-color", "-out=plan.out")
    if result.returncode == 0:
        shown = run("show", "-json", "plan.out")
        (work / "plan.json").write_text(shown.stdout, encoding="utf-8")
    return result


@cache
def planned(manifest_path: Path, tmp: Path) -> dict[str, Any]:
    work = tmp / manifest_path.stem
    work.mkdir()
    result = plan(work, yaml.safe_load(manifest_path.read_text(encoding="utf-8")))
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((work / "plan.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def w3(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return planned(W3, tmp_path_factory.mktemp("w3"))


@pytest.fixture(scope="module")
def w2(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return planned(W2, tmp_path_factory.mktemp("w2"))


def created(plan_json: dict[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    """Planned values of every `kind` resource in the module, by its for_each key."""
    return {change["index"]: change["change"]["after"] for change in plan_json["resource_changes"]
            if change["type"] == kind and change["mode"] == "managed" and change["change"]["actions"] == ["create"]}


def test_a_role_per_tool_with_the_boundary_its_tags_and_an_hour_at_most(w3: dict[str, Any]) -> None:
    roles = created(w3, "aws_iam_role")
    assert set(roles) == {"get_pod_status", "get_recent_alerts", "restart_deployment", "search_runbooks"}
    for tool, role in roles.items():
        assert role["name"] == f"w3-incident-{tool.replace('_', '-')}"
        assert role["permissions_boundary"] == BOUNDARY
        assert role["max_session_duration"] == 3600
        assert role["tags"] == {"workflow": "w3-incident", "tool": tool, "owner": "tomasz.nowak@larkspur.example",
                                "sponsor": "priya.raman@larkspur.example",
                                "server": "knowledge-mcp" if tool == "search_runbooks" else "k8s-mcp",
                                "writes": "true" if tool == "restart_deployment" else "false"}


def test_only_the_tools_server_assumes_it_naming_a_person_and_the_workflow(w3: dict[str, Any]) -> None:
    for tool, role in created(w3, "aws_iam_role").items():
        (statement,) = json.loads(role["assume_role_policy"])["Statement"]
        server = VARS["knowledge_mcp_role_arn"] if tool == "search_runbooks" else VARS["k8s_mcp_role_arn"]
        assert statement["Principal"] == {"AWS": server}
        assert sorted(statement["Action"]) == ["sts:AssumeRole", "sts:SetSourceIdentity", "sts:TagSession"]
        assert statement["Condition"] == {
            "StringLike": {"sts:SourceIdentity": "*@larkspur.example"},
            "StringEquals": {"aws:RequestTag/workflow": "w3-incident"},
            "ForAllValues:StringEquals": {"aws:TagKeys": "workflow"},
        }


def test_each_role_gets_its_catalogs_grants_and_the_never_list_denied(w3: dict[str, Any]) -> None:
    policies = {tool: json.loads(p["policy"])["Statement"] for tool, p in created(w3, "aws_iam_role_policy").items()}
    allowed = {tool: sorted((a, s["Resource"]) for s in st if s["Effect"] == "Allow"
                            for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"]))
               for tool, st in policies.items()}
    assert allowed["get_pod_status"] == [("eks:DescribeCluster", VARS["cluster_arn"])]
    assert allowed["restart_deployment"] == [("eks:DescribeCluster", VARS["cluster_arn"])]
    assert allowed["search_runbooks"] == [("bedrock:Retrieve", VARS["knowledge_base_arn"])]
    alarms = f"arn:aws:cloudwatch:ca-central-1:{ACCOUNT}:alarm:*"
    assert allowed["get_recent_alerts"] == [("cloudwatch:DescribeAlarmHistory", alarms), ("cloudwatch:DescribeAlarms", alarms)]
    never = sorted(json.loads(json.dumps(w3["planned_values"]["outputs"]["never_actions"]["value"])))
    assert never == sorted(["iam:*", "secretsmanager:GetSecretValue", "ssm:GetParameter*", "ssm:SendCommand",
                            "ssm:StartSession", "ecs:ExecuteCommand", "eks:DeleteCluster", "eks:UpdateClusterConfig"])
    for statements in policies.values():
        (deny,) = [s for s in statements if s["Effect"] == "Deny"]
        assert sorted(deny["Action"]) == never and deny["Resource"] == "*"


def test_kubernetes_access_is_read_only_in_two_namespaces_or_one_group(w3: dict[str, Any]) -> None:
    entries = created(w3, "aws_eks_access_entry")
    assert set(entries) == {"get_pod_status", "restart_deployment"}
    assert entries["restart_deployment"]["kubernetes_groups"] == ["larkspur:deployment-restarters"]
    (view,) = created(w3, "aws_eks_access_policy_association").items()
    assert view[0] == "get_pod_status"
    assert view[1]["policy_arn"] == "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
    assert view[1]["access_scope"] == [{"type": "namespace", "namespaces": ["billing", "claims"]}]


def test_the_workflow_identity_gets_one_cedar_permit_per_tool(w3: dict[str, Any]) -> None:
    permits = w3["planned_values"]["outputs"]["cedar_permits"]["value"]
    assert set(permits) == {"get_pod_status", "get_recent_alerts", "restart_deployment", "search_runbooks"}
    principal = f'principal == AgentCore::IamEntity::"arn:aws:sts::{ACCOUNT}:assumed-role/w3-incident-harness"'
    for tool, permit in permits.items():
        target = "knowledge" if tool == "search_runbooks" else "k8s"
        assert permit.startswith(f"permit (\n  {principal},\n  action == AgentCore::Action::\"{target}___{tool}\",\n"
                                 f"  resource == AgentCore::Gateway::\"{GATEWAY}\"\n)")
        assert permit.endswith(";")
    assert permits["restart_deployment"].endswith(
        ')\nwhen {\n  context.input has service && ["claims-api","billing-worker"].contains(context.input.service)\n};')
    assert "when" not in permits["get_pod_status"]


def test_chapter_5s_operations_assistant_gets_two_read_only_roles(w2: dict[str, Any]) -> None:
    roles = created(w2, "aws_iam_role")
    assert set(roles) == {"get_pod_status", "get_recent_alerts"}
    assert {role["tags"]["writes"] for role in roles.values()} == {"false"}
    assert set(w2["planned_values"]["outputs"]["cedar_permits"]["value"]) == set(roles)


def broken(change: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = yaml.safe_load(W3.read_text(encoding="utf-8"))
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    if change == "unknown tool":
        manifest["tools"]["drop_table"] = {"args": ["name"], "writes": True}
    elif change == "writes differs":
        manifest["tools"]["restart_deployment"].pop("writes")
    elif change == "allow on an argument the tool doesn't take":
        manifest["tools"]["restart_deployment"]["allow"] = {"namespace": ["claims"]}
    return manifest, catalog


@pytest.mark.parametrize("change, message", [
    ("unknown tool", "the catalog doesn't have: drop_table"),
    ("writes differs", "writes flag"),
    ("allow on an argument the tool doesn't take", "names an argument its tool doesn't take"),
])
def test_the_plan_stops_when_the_manifest_and_the_catalog_disagree(tmp_path: Path, change: str, message: str) -> None:
    result = plan(tmp_path, *broken(change))
    assert result.returncode != 0
    assert message in " ".join((result.stdout + result.stderr).split())
