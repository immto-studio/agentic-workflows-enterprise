"""W4's identities on AWS (aws/): three pull-request-only identities, one role each through Pod Identity,
the analyst and the risk scorer holding no AWS action and the scribe the trigger queue's reads; a fourth
role for GitHub Actions through OIDC (ADR-0049) that may only send the trigger; every role under a
boundary that denies the never-list, sts:AssumeRole and the apply included; the GitHub Apps with no
merge-capable permission, which the plan refuses to grant; and the offline plan, when terraform and a
provider mirror are at hand."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from a2a_support import ANALYST_IDENTITY, RISK_SCORER_IDENTITY, SCRIBE_IDENTITY

W4 = Path(__file__).resolve().parents[1]
hcl2 = pytest.importorskip("hcl2", reason="python-hcl2 (labs/ch06/requirements.txt) parses the Terraform")

sys.path.insert(0, str(W4 / "aws"))
import plan_offline  # noqa: E402

AWS = W4 / "aws"
CATALOG = yaml.safe_load((W4 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
MANIFEST = yaml.safe_load((W4 / "manifest" / "w4-change.yaml").read_text(encoding="utf-8"))
AGENTS = CATALOG["agents"]
QUEUE_ACTIONS = {"sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes",
                 "sqs:ChangeMessageVisibility"}
# What a merge or an approving review needs on GitHub (the Apps permission reference, read 2026-11-02):
# PUT .../pulls/{n}/merge is under Contents (write); POST .../pulls/{n}/reviews under Pull requests (write).
MERGE_CAPABLE = {("contents", "write"), ("pull_requests", "write"), ("administration", "write"), ("workflows", "write")}
NEVER_LIST = ["merge_pull_request", "approve_pull_request", "delete_namespace", "modify_iam", "modify_security_group",
              "read_vault_secret", "run_command"]


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


def code_text() -> str:
    """The Terraform without its comments, for assertions about what the configuration never says."""
    lines = []
    for path in sorted(AWS.glob("*.tf")):
        for line in path.read_text(encoding="utf-8").splitlines():
            lines.append(line.split("#", 1)[0])
    return "\n".join(lines)


def test_the_provider_is_pinned_and_the_region_is_canadian():
    text = (AWS / "versions.tf").read_text(encoding="utf-8")
    assert 'version = "6.71.0"' in text
    assert TF["variable"]["region"]["default"] == "ca-central-1"


def test_the_catalog_names_three_agents_a_trigger_and_the_lab_identities():
    assert set(AGENTS) == {"analyst", "risk_scorer", "scribe"}
    assert AGENTS["analyst"]["identity"] == "larkspur-change-analyst"
    assert AGENTS["risk_scorer"]["identity"] == "larkspur-risk-scorer"
    assert AGENTS["scribe"]["identity"] == "larkspur-change-scribe"
    assert CATALOG["trigger"]["identity"] == "larkspur-change-trigger"
    # The risk scorer is the change-management team's, in its own namespace; the other two the platform team's.
    assert AGENTS["risk_scorer"]["team"] == "change-management" and AGENTS["risk_scorer"]["namespace"] == "larkspur-change"
    assert {AGENTS["analyst"]["team"], AGENTS["scribe"]["team"]} == {"platform-engineering"}
    # The A2A names the lab runs under are the audiences and the caller the catalog records for production.
    assert CATALOG["a2a"]["audiences"] == {"analyst": ANALYST_IDENTITY, "risk_scorer": RISK_SCORER_IDENTITY}
    assert CATALOG["a2a"]["caller"] == SCRIBE_IDENTITY


def test_the_analyst_and_the_risk_scorer_hold_no_aws_action_and_the_scribe_only_the_queue():
    assert AGENTS["analyst"]["aws"]["role_actions"] == []
    assert AGENTS["risk_scorer"]["aws"]["role_actions"] == []
    scribe = set(AGENTS["scribe"]["aws"]["role_actions"])
    assert scribe and scribe <= QUEUE_ACTIONS and "sqs:SendMessage" not in scribe
    assert CATALOG["trigger"]["aws"]["role_actions"] == ["sqs:SendMessage"]
    # No identity reads a secret: the downstream credentials are leased from Vault, not granted to a role.
    for agent in AGENTS.values():
        assert not any(a.startswith(("secretsmanager:", "ssm:", "kms:")) for a in agent["aws"]["role_actions"])


def test_the_github_apps_can_read_and_comment_but_never_merge_or_approve():
    reader = AGENTS["analyst"]["github_app"]["permissions"]
    assert set(reader.values()) == {"read"}
    assert {"pull_requests", "checks", "statuses", "actions", "metadata"} <= set(reader)
    scribe = AGENTS["scribe"]["github_app"]["permissions"]
    assert scribe == {"metadata": "read", "issues": "write"}  # the conversation comment is an issue comment
    for name, agent in AGENTS.items():
        for permission, level in agent.get("github_app", {}).get("permissions", {}).items():
            assert (permission, level) not in MERGE_CAPABLE, f"{name}: {permission}: {level}"


def test_the_risk_scorer_reaches_no_source():
    assert "github_app" not in AGENTS["risk_scorer"] and "servicenow" not in AGENTS["risk_scorer"]
    assert AGENTS["risk_scorer"]["gateway"]["alias"] == "larkspur-chat"  # the one thing it reaches, for the rationale
    # The sources' roles: the analyst reads changes, the scribe writes one (the fact sheet, C.4).
    assert AGENTS["analyst"]["servicenow"]["roles"] == ["sn_change_read"]
    assert AGENTS["scribe"]["servicenow"]["roles"] == ["itil"]


def test_each_agent_role_is_bound_through_pod_identity_under_the_boundary():
    role = TF["resource"]["aws_iam_role"]["agent"]
    assert role["for_each"] == "${local.agents}"
    assert role["name"] == "${each.value.identity}"
    assert role["permissions_boundary"] == "${aws_iam_policy.boundary.arn}"
    trust = TF["data"]["aws_iam_policy_document"]["pod_identity_trust"]["statement"][0]
    assert trust["principals"][0] == {"type": "Service", "identifiers": ["pods.eks.amazonaws.com"]}
    assert trust["condition"][0]["variable"] == "aws:RequestTag/eks-cluster-arn"
    association = TF["resource"]["aws_eks_pod_identity_association"]["agent"]
    assert association["for_each"] == "${local.agents}"
    assert association["namespace"] == "${each.value.namespace}"
    assert association["service_account"] == "${each.value.service_account}"
    # Only the agents with an action get a policy; the policy's one statement is on the queue.
    policy = TF["resource"]["aws_iam_policy"]["agent"]
    assert policy["for_each"] == "${local.agents_with_actions}"
    statement = TF["data"]["aws_iam_policy_document"]["agent"]["statement"][0]
    assert statement["actions"] == "${each.value.aws.role_actions}"
    assert statement["resources"] == ["${local.queue_arn}"]


def test_the_trigger_role_trusts_one_repository_and_environment_and_may_only_send():
    trigger = TF["resource"]["aws_iam_role"]["trigger"]
    assert trigger["name"] == "${local.trigger.identity}"
    assert trigger["permissions_boundary"] == "${aws_iam_policy.boundary.arn}"
    trust = TF["data"]["aws_iam_policy_document"]["trigger_trust"]["statement"][0]
    assert trust["actions"] == ["sts:AssumeRoleWithWebIdentity"]
    assert trust["principals"][0] == {"type": "Federated", "identifiers": ["${local.oidc_provider_arn}"]}
    conditions = {c["variable"]: c["values"] for c in trust["condition"]}
    assert conditions["token.actions.githubusercontent.com:aud"] == ["sts.amazonaws.com"]
    assert conditions["token.actions.githubusercontent.com:sub"] == ["${local.oidc_subject}"]
    # ADR-0049's form: repo:<org>/<repo>:environment:<env>.
    assert TF["locals"]["oidc_subject"].startswith("repo:${local.trigger.github.organization}/")
    assert ":environment:${local.trigger.github.environment}" in TF["locals"]["oidc_subject"]
    statement = TF["data"]["aws_iam_policy_document"]["trigger"]["statement"][0]
    assert statement["actions"] == "${local.trigger.aws.role_actions}"
    assert statement["resources"] == ["${local.queue_arn}"]


def test_the_boundary_allows_the_queue_and_denies_the_never_list_including_assume_role_and_the_apply():
    boundary = TF["data"]["aws_iam_policy_document"]["boundary"]["statement"]
    allow = next(s for s in boundary if s["effect"] == "Allow")
    assert allow["actions"] == "${local.ceiling_actions}" and allow["resources"] == ["${local.queue_arn}"]
    deny = next(s for s in boundary if s["effect"] == "Deny")
    assert deny["actions"] == "${local.never_actions}" and deny["resources"] == ["*"]
    never = TF["locals"]["never_actions"]
    for action in ("iam:*", "sts:AssumeRole", "secretsmanager:*", "ssm:*", "eks:*", "ec2:*", "lambda:*",
                   "cloudformation:*", "s3:PutObject", "s3:DeleteObject", "logs:PutLogEvents", "cloudwatch:PutMetricData"):
        assert action in never, action
    assert MANIFEST["never"] == NEVER_LIST and set(CATALOG["never"]) == set(NEVER_LIST)
    # The configuration grants no secret read anywhere; secretsmanager appears only in the deny.
    text = code_text()
    assert "secretsmanager:GetSecretValue" not in text and "kms:" not in text


def test_the_plan_refuses_a_merge_capable_app_permission_by_precondition():
    checks = TF["resource"]["terraform_data"]["catalog_checks"]["lifecycle"][0]["precondition"]
    conditions = [c["condition"] for c in checks]
    assert any("offending_permissions" in c for c in conditions)
    assert any("merge_pull_request" in c and "approve_pull_request" in c for c in conditions)
    assert any("risk_scorer.github_app" in c for c in conditions)
    merge_capable = TF["locals"]["merge_capable"]
    assert merge_capable == {"contents": "write", "pull_requests": "write", "administration": "write", "workflows": "write"}


PLUGIN_DIR = Path(os.environ["TF_PLUGIN_CACHE_DIR"]) if os.environ.get("TF_PLUGIN_CACHE_DIR") else None
needs_terraform = pytest.mark.skipif(shutil.which("terraform") is None or PLUGIN_DIR is None or not PLUGIN_DIR.exists(),
                                     reason="needs terraform and TF_PLUGIN_CACHE_DIR with hashicorp/aws 6.71.0")


@needs_terraform
def test_the_offline_plan_has_the_fourteen_resources(tmp_path):
    summary = plan_offline.plan(tmp_path, PLUGIN_DIR)
    assert summary["resources_to_add"] == 14
    assert summary["by_type"] == {"aws_eks_pod_identity_association": 3, "aws_iam_policy": 3, "aws_iam_role": 4,
                                  "aws_iam_role_policy_attachment": 2, "aws_sqs_queue": 1, "terraform_data": 1}
    queue = f"arn:aws:sqs:ca-central-1:{plan_offline.ACCOUNT}:w4-change-trigger"
    boundary = summary["policies"]["aws_iam_policy.boundary"]
    allow = next(s for s in boundary if s["Effect"] == "Allow")
    assert sorted(allow["Action"]) == sorted(QUEUE_ACTIONS) and allow["Resource"] == queue
    deny = next(s for s in boundary if s["Effect"] == "Deny")
    assert {"iam:*", "sts:AssumeRole", "secretsmanager:*", "eks:*", "ec2:*"} <= set(deny["Action"])
    scribe = summary["policies"]['aws_iam_policy.agent["scribe"]'][0]
    assert "sqs:SendMessage" not in scribe["Action"] and scribe["Resource"] == queue
    trigger = summary["policies"]["aws_iam_policy.trigger"][0]
    assert trigger["Action"] == "sqs:SendMessage" and trigger["Resource"] == queue
    # Who may assume what: the agents only pods of this account's clusters, the trigger only the one job.
    for agent in ("analyst", "risk_scorer", "scribe"):
        trust = summary["trusts"][f'aws_iam_role.agent["{agent}"]'][0]
        assert trust["Principal"] == {"Service": "pods.eks.amazonaws.com"}
    trust = summary["trusts"]["aws_iam_role.trigger"][0]
    assert trust["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert trust["Condition"]["StringEquals"]["token.actions.githubusercontent.com:sub"] == \
        "repo:larkspur-mutual/platform-infra:environment:change-evidence"


@needs_terraform
def test_the_offline_plan_stops_when_the_catalog_gives_an_app_a_merge_capable_permission(tmp_path):
    def give_the_scribe_pull_requests_write(work: Path) -> None:
        path = work / "catalog" / "tools.yaml"
        catalog = yaml.safe_load(path.read_text(encoding="utf-8"))
        catalog["agents"]["scribe"]["github_app"]["permissions"]["pull_requests"] = "write"
        path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")

    with pytest.raises(RuntimeError) as failed:
        plan_offline.plan(tmp_path, PLUGIN_DIR, mutate=give_the_scribe_pull_requests_write)
    reason = " ".join(str(failed.value).split())  # terraform wraps the message; compare on one line
    assert "merge-capable" in reason and "scribe: pull_requests: write" in reason
