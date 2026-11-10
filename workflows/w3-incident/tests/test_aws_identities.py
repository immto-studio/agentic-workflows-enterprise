"""W3's AWS write identities (aws/): a runtime role via Pod Identity that assumes a write role per request
(chapters 4 and 6), one write role per write tool from the catalog holding eks:DescribeCluster only, each
with an EKS access entry mapped to the writers' Kubernetes group, every write role under a boundary that
denies the never-list; and the offline plan, when terraform and a provider mirror are at hand."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

W3 = Path(__file__).resolve().parents[1]
hcl2 = pytest.importorskip("hcl2", reason="python-hcl2 (labs/ch06/requirements.txt) parses the Terraform")

sys.path.insert(0, str(W3 / "aws"))
import plan_offline  # noqa: E402

AWS = W3 / "aws"
CATALOG = yaml.safe_load((W3 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
MANIFEST = yaml.safe_load((W3 / "manifest" / "w3-incident.yaml").read_text(encoding="utf-8"))
IDENTITIES = CATALOG["servers"]["writer-mcp"]["identities"]  # tool -> role name
NEVER_LIST_SHAPES = {"delete_namespace", "modify_iam", "modify_security_group", "read_vault_secret", "run_command"}
# The verbs a write action may carry; a write role may hold only Describe (the read that reaches the API).
WRITE_SAFE = ("eks:DescribeCluster",)
FORBIDDEN_IN_A_WRITE_ROLE = ("secretsmanager:GetSecretValue", "secretsmanager:*", "ssm:GetParameter", "ssm:*",
                             "kms:Decrypt", "eks:AccessKubernetesApi", "ec2:RunInstances", "ssm:StartSession")


def clean(value: Any) -> Any:
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


def test_the_catalog_names_two_write_identities_and_the_servicenow_user():
    assert set(IDENTITIES) == {"restart_deployment", "scale_deployment"}
    assert IDENTITIES["restart_deployment"] == "larkspur-ops-restarter"
    assert IDENTITIES["scale_deployment"] == "larkspur-ops-scaler"
    # The write role's only IAM action is eks:DescribeCluster; the write itself is the Kubernetes Role's.
    assert CATALOG["servers"]["writer-mcp"]["aws"]["role_actions"] == ["eks:DescribeCluster"]
    # ServiceNow is not an AWS identity; it holds the itil role on the instance, not an IAM role.
    assert CATALOG["servers"]["servicenow-mcp"]["servicenow"]["write_role"] == "itil"
    assert "aws" not in CATALOG["servers"]["servicenow-mcp"]


def test_the_runtime_role_assumes_the_write_roles_per_request():
    runtime = TF["resource"]["aws_iam_role"]["runtime"]
    assert runtime["name"] == "${local.runtime_name}"
    assert "permissions_boundary" not in runtime, "the runtime must assume the write roles; the boundary denies sts:AssumeRole"
    trust = TF["data"]["aws_iam_policy_document"]["runtime_trust"]["statement"][0]
    assert trust["principals"][0] == {"type": "Service", "identifiers": ["pods.eks.amazonaws.com"]}
    assert trust["condition"][0]["variable"] == "aws:RequestTag/eks-cluster-arn"
    assume = TF["data"]["aws_iam_policy_document"]["runtime"]["statement"][0]
    assert sorted(assume["actions"]) == ["sts:AssumeRole", "sts:SetSourceIdentity", "sts:TagSession"]
    assert assume["resources"] == "${values(local.write_role_arns)}"
    association = TF["resource"]["aws_eks_pod_identity_association"]["runtime"]
    assert association["service_account"] == "${var.writer_service_account}"


def test_each_write_role_is_assumed_by_the_runtime_with_a_workflow_tag_under_the_boundary():
    role = TF["resource"]["aws_iam_role"]["write"]
    assert role["for_each"] == "${local.identities}"
    assert role["name"] == "${each.value}"
    assert role["permissions_boundary"] == "${aws_iam_policy.write_boundary.arn}"
    trust = TF["data"]["aws_iam_policy_document"]["write_trust"]["statement"][0]
    assert trust["principals"][0] == {"type": "AWS", "identifiers": ["${aws_iam_role.runtime.arn}"]}
    assert trust["condition"][0]["variable"] == "aws:RequestTag/workflow"
    assert trust["condition"][0]["values"] == ["${local.workflow}"]


def test_a_write_role_holds_only_describe_cluster_not_a_secret_or_exec_action():
    actions = TF["locals"]["write_actions"]
    assert actions == "${local.writer.aws.role_actions}"  # from the catalog: [eks:DescribeCluster]
    catalog_actions = CATALOG["servers"]["writer-mcp"]["aws"]["role_actions"]
    assert catalog_actions == list(WRITE_SAFE)
    for forbidden in FORBIDDEN_IN_A_WRITE_ROLE:
        assert forbidden not in catalog_actions


def test_the_boundary_denies_the_never_list_including_assume_role():
    boundary = TF["data"]["aws_iam_policy_document"]["write_boundary"]["statement"]
    allow = next(s for s in boundary if s["effect"] == "Allow")
    assert allow["actions"] == "${local.write_actions}", "the boundary allows only the write actions (DescribeCluster)"
    deny = next(s for s in boundary if s["effect"] == "Deny")
    never = TF["locals"]["never_actions"]
    assert deny["actions"] == "${local.never_actions}"
    for action in ("iam:*", "sts:AssumeRole", "secretsmanager:*", "ssm:*", "eks:AccessKubernetesApi",
                   "logs:PutLogEvents", "cloudwatch:PutMetricData", "ec2:AuthorizeSecurityGroupIngress",
                   "ec2:ModifySecurityGroupRules", "logs:DeleteLogGroup"):
        assert action in never, action
    assert MANIFEST["never"] == ["delete_namespace", "modify_iam", "modify_security_group", "read_vault_secret", "run_command"]
    assert NEVER_LIST_SHAPES == set(MANIFEST["never"])


def test_the_access_entries_map_to_the_writers_group_not_a_broad_policy():
    entry = TF["resource"]["aws_eks_access_entry"]["write"]
    assert entry["for_each"] == "${local.identities}"
    assert entry["kubernetes_groups"] == ["${var.writer_k8s_group}"]
    assert entry["type"] == "STANDARD"
    # No AWS-managed access policy is associated: the built-in edit policy is too broad (fact sheet B.4).
    assert "aws_eks_access_policy_association" not in TF["resource"]
    # No AWS-managed access policy ARN is assigned anywhere (comments that explain why not are ignored).
    code = []
    for f in ("main.tf", "versions.tf", "outputs.tf"):
        for line in (AWS / f).read_text(encoding="utf-8").splitlines():
            code.append(line.split("#", 1)[0])
    text = "\n".join(code)
    assert "cluster-access-policy/" not in text, "no AWS-managed EKS access policy is associated"
    assert TF["variable"]["write_namespaces"]["default"] == ["larkspur-prod"]


PLUGIN_DIR = Path(os.environ["TF_PLUGIN_CACHE_DIR"]) if os.environ.get("TF_PLUGIN_CACHE_DIR") else None


@pytest.mark.skipif(shutil.which("terraform") is None or PLUGIN_DIR is None or not PLUGIN_DIR.exists(),
                    reason="needs terraform and TF_PLUGIN_CACHE_DIR with hashicorp/aws 6.71.0")
def test_the_offline_plan_has_the_thirteen_resources(tmp_path):
    summary = plan_offline.plan(tmp_path, PLUGIN_DIR)
    assert summary["resources_to_add"] == 13
    assert summary["by_type"] == {"aws_eks_access_entry": 2, "aws_eks_pod_identity_association": 1,
                                  "aws_iam_policy": 4, "aws_iam_role": 3, "aws_iam_role_policy_attachment": 3}
    policies = summary["policies"]
    boundary = next(v for k, v in policies.items() if k.endswith("write_boundary"))
    deny = next(s for s in boundary if s["Effect"] == "Deny")
    assert "iam:*" in deny["Action"] and "secretsmanager:*" in deny["Action"] and "sts:AssumeRole" in deny["Action"]
    allow = next(s for s in boundary if s["Effect"] == "Allow")
    allow_actions = allow["Action"] if isinstance(allow["Action"], list) else [allow["Action"]]
    assert allow_actions == ["eks:DescribeCluster"]
