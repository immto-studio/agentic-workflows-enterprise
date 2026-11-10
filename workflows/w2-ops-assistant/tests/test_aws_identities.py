"""W2's AWS identities (aws/): one role per server from the catalog, read actions only, EKS Pod Identity
trust, the view policy scoped to the production namespace, the never-list denied by the boundary; and
the offline plan, when terraform and a provider mirror are at hand."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import W2

hcl2 = pytest.importorskip("hcl2", reason="python-hcl2 (labs/ch06/requirements.txt) parses the Terraform")

sys.path.insert(0, str(W2))
sys.path.insert(0, str(W2 / "aws"))
import plan_offline  # noqa: E402
import vet  # noqa: E402

AWS = W2 / "aws"
CATALOG = yaml.safe_load((W2 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
MANIFEST = yaml.safe_load((W2 / "manifest" / "w2-ops-assistant.yaml").read_text(encoding="utf-8"))


def clean(value: Any) -> Any:
    """python-hcl2 keeps HCL's quotes and adds bookkeeping keys; drop both."""
    if isinstance(value, dict):
        return {clean(k): clean(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def load() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {"resource": {}, "data": {}, "variable": {}, "locals": {}, "output": {}}
    for path in sorted(AWS.glob("*.tf")):
        with path.open(encoding="utf-8") as handle:
            parsed = clean(hcl2.load(handle))
        for kind in ("resource", "data"):
            for block in parsed.get(kind, []):
                for type_name, named in block.items():
                    out[kind].setdefault(type_name, {}).update(named)
        for block in parsed.get("variable", []):
            out["variable"].update(block)
        for block in parsed.get("locals", []):
            out["locals"].update(block)
        for block in parsed.get("output", []):
            out["output"].update(block)
    return out


TF = load()


def test_the_provider_is_pinned_and_the_region_is_canadian():
    text = (AWS / "versions.tf").read_text(encoding="utf-8")
    assert 'version = "6.71.0"' in text
    assert TF["variable"]["region"]["default"] == "ca-central-1"


def test_every_catalog_identity_holds_read_actions_only():
    for name, server in CATALOG["servers"].items():
        actions = server["aws"]["role_actions"]
        assert actions, name
        assert all(vet.is_read_action(a) for a in actions), (name, actions)
        assert vet.identity_scope(server)["read_only"], name
    tool_servers = {spec["server"] for spec in CATALOG["tools"].values()}
    assert tool_servers == set(CATALOG["servers"])  # every tool's server has an identity
    assert set(MANIFEST["tools"]) == set(CATALOG["tools"])  # the manifest and the catalog name the same tools


def test_one_role_per_server_trusted_by_pod_identity_under_the_boundary():
    role = TF["resource"]["aws_iam_role"]["server"]
    assert role["for_each"] == "${local.servers}"
    assert role["name"] == "${each.value.identity}"
    assert role["permissions_boundary"] == "${aws_iam_policy.read_boundary.arn}"
    assert role["max_session_duration"] == 3600
    trust = TF["data"]["aws_iam_policy_document"]["pod_identity_trust"]["statement"][0]
    assert trust["principals"][0] == {"type": "Service", "identifiers": ["pods.eks.amazonaws.com"]}
    assert sorted(trust["actions"]) == ["sts:AssumeRole", "sts:TagSession"]
    assert trust["condition"][0]["variable"] == "aws:RequestTag/eks-cluster-arn"
    association = TF["resource"]["aws_eks_pod_identity_association"]["server"]
    assert association["namespace"] == "${var.servers_namespace}" and association["service_account"] == "${each.key}"


def test_the_boundary_denies_the_never_list():
    boundary = TF["data"]["aws_iam_policy_document"]["read_boundary"]["statement"]
    deny = next(s for s in boundary if s["effect"] == "Deny")
    never = TF["locals"]["never_actions"]
    assert deny["actions"] == "${local.never_actions}" and len(never) >= 10
    for action in ("iam:*", "sts:AssumeRole", "secretsmanager:*", "ssm:*", "logs:PutLogEvents", "cloudwatch:PutMetricData",
                   "ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress", "ec2:ModifySecurityGroupRules"):
        assert action in never
    # the manifest's never-list names five capabilities; each maps to a denied family
    assert set(MANIFEST["never"]) == {"restart_deployment", "delete_namespace", "modify_iam", "modify_security_group",
                                      "read_vault_secret", "run_command"}  # chapter 4's six less the payments slice, plus the restart
    assert "iam:*" in never and "secretsmanager:*" in never and "ssm:*" in never and "eks:AccessKubernetesApi" in never


def test_the_kubernetes_role_views_the_production_namespace_only():
    association = TF["resource"]["aws_eks_access_policy_association"]["kubernetes_view"]
    assert association["policy_arn"] == "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
    assert association["access_scope"][0] == {"type": "namespace", "namespaces": "${var.read_namespaces}"}
    assert TF["variable"]["read_namespaces"]["default"] == ["larkspur-prod"]
    entry = TF["resource"]["aws_eks_access_entry"]["kubernetes_reader"]
    assert entry["principal_arn"] == '${aws_iam_role.server["kubernetes-mcp"].arn}'


def test_the_log_reads_are_bounded_to_the_production_log_groups():
    resources = TF["locals"]["resources"]
    assert resources["kubernetes-mcp"] == ["${local.cluster_arn}"]
    assert resources["metrics-mcp"] == ["*"]  # CloudWatch's metric reads take no resource ARN
    assert resources["logs-mcp"][0] == "${local.log_group_arn}"
    assert TF["variable"]["log_group_prefix"]["default"] == "/larkspur/prod/"


PLUGIN_DIR = Path(os.environ["TF_PLUGIN_CACHE_DIR"]) if os.environ.get("TF_PLUGIN_CACHE_DIR") else None


@pytest.mark.skipif(shutil.which("terraform") is None or PLUGIN_DIR is None or not PLUGIN_DIR.exists(),
                    reason="needs terraform and TF_PLUGIN_CACHE_DIR with hashicorp/aws 6.71.0")
def test_the_offline_plan_has_the_fifteen_resources(tmp_path):
    summary = plan_offline.plan(tmp_path, PLUGIN_DIR)
    assert summary["resources_to_add"] == 15
    assert summary["by_type"] == {"aws_eks_access_entry": 1, "aws_eks_access_policy_association": 1,
                                  "aws_eks_pod_identity_association": 3, "aws_iam_policy": 4, "aws_iam_role": 3,
                                  "aws_iam_role_policy_attachment": 3}
    policies = summary["policies"]
    logs = next(v for k, v in policies.items() if k.endswith('["logs-mcp"]'))
    assert logs[0]["Action"] if isinstance(logs[0]["Action"], list) else [logs[0]["Action"]]
    assert all(r.startswith("arn:aws:logs:ca-central-1:111122223333:log-group:/larkspur/prod/") for r in logs[0]["Resource"])
    boundary = next(v for k, v in policies.items() if k.endswith("read_boundary"))
    deny = next(s for s in boundary if s["Effect"] == "Deny")
    assert "iam:*" in deny["Action"] and "secretsmanager:*" in deny["Action"]
