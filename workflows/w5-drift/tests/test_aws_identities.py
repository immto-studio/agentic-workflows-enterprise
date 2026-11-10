"""W5's identities on AWS (aws/), in the ops account and the three workload accounts the map names: six roles
in the ops account, each bound through Pod Identity to its service accounts in the platform team's namespace
of the ops cluster; a target role for the cloud reader and one for the cost reader in each workload account,
holding exactly the reads its fake mirrors for one account and trusting only the reader's ops role, from the
organization, with the Pod's session tags; the two chain roles in the ops account holding only sts:AssumeRole
and sts:TagSession on their targets; the cost reader's export read in the ops account by an identity of its
own; a boundary in every account, the ops one denying sts:AssumeRole on every role but the targets and the
targets' denying it outright, both denying the never-list and no read a reader needs; the state bucket's deny
of the writes to every role, for the state stack to merge; the GitHub Apps' line and the map's accounts, which
the plan refuses to cross; and the offline plan, when terraform and a provider mirror are at hand."""

from __future__ import annotations

import fnmatch
import functools
import json
import os
import shutil
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import IDENTITY, W5

hcl2 = pytest.importorskip("hcl2", reason="python-hcl2 (labs/ch06/requirements.txt) parses the Terraform")

sys.path.insert(0, str(W5 / "aws"))
import plan_offline  # noqa: E402

import cloud_fake  # noqa: E402  (servers/, on the path through conftest)

AWS = W5 / "aws"
MODULE = AWS / "workload-account"
WORKFLOWS = W5.parent
RESULTS = AWS / "results" / "2026-11-10"
CATALOG = yaml.safe_load((W5 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
MANIFEST = yaml.safe_load((W5 / "manifest" / "w5-drift.yaml").read_text(encoding="utf-8"))
WORKSPACE_MAP = yaml.safe_load((W5 / "catalog" / "workspace-map.yaml").read_text(encoding="utf-8"))
SERVERS = CATALOG["servers"]
EXPORT = SERVERS["cost-mcp"]["export"]
IDENTITIES = {**SERVERS, "harness": CATALOG["harness"], "cost-export": EXPORT}  # the six roles in the ops account
CHAINED = ("cloud-mcp", "cost-mcp")  # the readers with a target role in each workload account
GITHUB = CATALOG["github"]
GROUP = CATALOG["membership"]["group"]
WORKSPACES = WORKSPACE_MAP["teams"][GROUP]
ACCOUNTS = WORKSPACE_MAP["accounts"][GROUP]
OPS = plan_offline.ACCOUNT
CLUSTER_ARN = f"arn:aws:eks:ca-central-1:{OPS}:cluster/ops"
EXPECTED_BY_TYPE = {"aws_eks_pod_identity_association": 10, "aws_iam_policy": 14, "aws_iam_role": 12,
                    "aws_iam_role_policy_attachment": 10, "terraform_data": 1}
READ_VERBS = ("Get", "List", "Describe", "Lookup", "View")
CHAIN = {"sts:AssumeRole", "sts:TagSession"}  # the chain's two actions, "Write" in AWS's reference (C.13.6)

# What each tool's call needs on AWS, as its fake mirrors the call: the state reader's listing by the mapped
# keys and its object reads, which decrypt with the bucket's key (fact sheet B.2, C.5); the cloud reader's
# describe call per kind, GetResources, LookupEvents, and GetMetricStatistics (C.1, C.2); the cost reader's
# Cost Explorer calls, DescribeBudgets with its two actions (C.1, C.4), GetAnomalies, and a billing period's
# export files listed and read (C.3). The policy reader's two tools read the corpus and ServiceNow. The tools
# come from each server's lock and the kinds from cloud_fake.KINDS, so a tool or a kind added to a server
# without its action fails here.
DESCRIBE_ACTIONS = {
    "instances": "ec2:DescribeInstances",
    "volumes": "ec2:DescribeVolumes",
    "snapshots": "ec2:DescribeSnapshots",
    "security_groups": "ec2:DescribeSecurityGroups",
    "route_tables": "ec2:DescribeRouteTables",
    "load_balancers": "elasticloadbalancing:DescribeLoadBalancers",
}
TOOL_ACTIONS: dict[str, set[str]] = {
    "list_workspaces": {"s3:ListBucket"},
    "get_state": {"s3:GetObject", "kms:Decrypt"},
    "get_state_version": {"s3:GetObjectVersion", "kms:Decrypt"},
    "list_state_versions": {"s3:ListBucketVersions"},
    "describe_resources": set(DESCRIBE_ACTIONS.values()),
    "get_resources_by_tag": {"tag:GetResources"},
    "lookup_events": {"cloudtrail:LookupEvents"},
    "get_cpu_utilization": {"cloudwatch:GetMetricStatistics"},
    "get_cost_and_usage": {"ce:GetCostAndUsage"},
    "get_cost_by_resource": {"ce:GetCostAndUsageWithResources"},
    "describe_budgets": {"budgets:ViewBudget", "aws-portal:ViewBilling"},
    "get_anomalies": {"ce:GetAnomalies"},
    "read_cost_export": {"s3:ListBucket", "s3:GetObject"},
    "get_tagging_standard": set(),
    "list_policy_exceptions": set(),
}
# The tools whose resources are in the ops account: the state bucket and its key, and the bucket the
# organization's CUR 2.0 export lands in (C.11). Every other tool with an action reads the account it names,
# so its actions are that account's target role's (C.7, C.9, C.10).
IN_THE_OPS_ACCOUNT = {"list_workspaces", "get_state", "get_state_version", "list_state_versions", "read_cost_export"}
# The call each fake says it mirrors, in the fake's own text.
OPERATIONS = {
    "state-mcp": ("s3:GetObject", "s3:GetObjectVersion", "ListObjectVersions"),
    "cloud-mcp": ("DescribeInstances", "DescribeVolumes", "DescribeSnapshots", "DescribeSecurityGroups",
                  "DescribeRouteTables", "DescribeLoadBalancers", "GetResources", "LookupEvents", "GetMetricStatistics"),
    "cost-mcp": ("GetCostAndUsage", "GetCostAndUsageWithResources", "DescribeBudgets", "GetAnomalies"),
}

# The never-list, entry by entry, as AWS actions the boundaries must deny. The two GitHub entries are not IAM
# actions: the precondition holds them.
NEVER: dict[str, list[str]] = {
    "apply_plan": ["sts:AssumeRole", "s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion", "kms:Encrypt",
                   "kms:GenerateDataKey", "cloudformation:CreateStack", "lambda:UpdateFunctionCode", "rds:ModifyDBInstance",
                   "ec2:CreateRoute", "ec2:ReplaceRoute", "budgets:ModifyBudget", "ce:UpdateAnomalyMonitor"],
    "delete_resource": ["ec2:TerminateInstances", "ec2:DeleteVolume", "ec2:DeleteSnapshot", "ec2:DeleteSecurityGroup",
                        "ec2:DeleteRouteTable", "ec2:DeleteRoute", "elasticloadbalancing:DeleteLoadBalancer",
                        "rds:DeleteDBInstance", "lambda:DeleteFunction", "ce:DeleteAnomalyMonitor"],
    "stop_instance": ["ec2:StopInstances", "ec2:ModifyInstanceAttribute", "ec2:ModifyVolume", "rds:StopDBInstance"],
    "modify_security_group": ["ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
                              "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
                              "ec2:ModifySecurityGroupRules", "ec2:UpdateSecurityGroupRuleDescriptionsIngress",
                              "ec2:UpdateSecurityGroupRuleDescriptionsEgress", "ec2:CreateSecurityGroup",
                              "ec2:DeleteSecurityGroup"],
    "delete_namespace": ["eks:AccessKubernetesApi", "eks:CreateAccessEntry", "eks:AssociateAccessPolicy"],
    "modify_iam": ["iam:PutRolePolicy", "iam:AttachRolePolicy", "iam:DeleteRolePermissionsBoundary", "iam:CreateRole",
                   "budgets:ExecuteBudgetAction"],  # a budget action can apply an IAM policy or an SCP (C.14)
    "read_vault_secret": ["secretsmanager:GetSecretValue", "ssm:GetParameter"],
    "run_command": ["ssm:SendCommand", "ssm:StartSession"],
}
GITHUB_ENTRIES = {"merge_pull_request", "approve_pull_request"}


def clean(value: Any) -> Any:
    """python-hcl2 keeps HCL's quotes and adds bookkeeping keys; drop both."""
    if isinstance(value, dict):
        return {clean(k): clean(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def load(folder: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"resource": {}, "data": {}, "variable": {}, "locals": {}, "output": {}, "module": {},
                           "provider": []}
    for path in sorted(folder.glob("*.tf")):
        with path.open(encoding="utf-8") as handle:
            parsed = clean(hcl2.load(handle))
        for kind in ("resource", "data"):
            for block in parsed.get(kind, []):
                for type_name, named in block.items():
                    out[kind].setdefault(type_name, {}).update(named)
        for kind in ("variable", "locals", "output", "module"):
            for block in parsed.get(kind, []):
                out[kind].update(block)
        for block in parsed.get("provider", []):
            out["provider"] += [{"name": name, **body} for name, body in block.items()]
    return out


TF = load(AWS)
MOD = load(MODULE)


def code_text() -> str:
    """The Terraform, the module's included, without its comments, for assertions about what it never says."""
    return "\n".join(line.split("#", 1)[0] for path in sorted(AWS.glob("*.tf")) + sorted(MODULE.glob("*.tf"))
                     for line in path.read_text(encoding="utf-8").splitlines())


def lock_tools(server: str) -> set[str]:
    """The tools a server serves, from the lock it writes from its own definitions."""
    path = W5 / "servers" / f"{server.removesuffix('-mcp')}.lock.json"
    return set(json.loads(path.read_text(encoding="utf-8"))["tools"])


def expected_actions(server: str) -> set[str]:
    return set().union(*(TOOL_ACTIONS[tool] for tool in lock_tools(server)))


def target_actions(server: str) -> set[str]:
    """What the server's target role holds in each workload account: the actions of its tools that read the
    account they name."""
    return set().union(*(TOOL_ACTIONS[tool] for tool in lock_tools(server) - IN_THE_OPS_ACCOUNT))


def ops_actions(server: str) -> set[str]:
    """What the server reads in the ops account: the actions of its tools on the buckets and the key there."""
    return set().union(*(TOOL_ACTIONS[tool] for tool in lock_tools(server) & IN_THE_OPS_ACCOUNT))


def matches(action: str, patterns: Iterable[str]) -> bool:
    """IAM compares action names without regard to case, with * as a wildcard."""
    return any(fnmatch.fnmatchcase(action.lower(), pattern.lower()) for pattern in patterns)


def as_list(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def statement_actions(statements: Iterable[dict[str, Any]]) -> set[str]:
    return {action for statement in statements for action in as_list(statement["Action"])}


def denies(statements: list[dict[str, Any]], action: str, resource: str) -> bool:
    """Whether a Deny statement covers `action` on `resource`: its Action, then its Resource or NotResource,
    each with * as a wildcard. The boundaries' denies carry no condition (check_boundaries asserts it)."""
    for statement in statements:
        if statement["Effect"] != "Deny" or not matches(action, as_list(statement["Action"])):
            continue
        if "NotResource" in statement:
            if not any(fnmatch.fnmatchcase(resource, p) for p in as_list(statement["NotResource"])):
                return True
        elif any(fnmatch.fnmatchcase(resource, p) for p in as_list(statement["Resource"])):
            return True
    return False


def allows(statements: list[dict[str, Any]], action: str, resource: str) -> bool:
    return any(statement["Effect"] == "Allow" and matches(action, as_list(statement["Action"]))
               and any(fnmatch.fnmatchcase(resource, p) for p in as_list(statement["Resource"]))
               for statement in statements)


def installs(app: dict[str, Any]) -> list[str]:
    places = app["installed_on"]
    return [places] if isinstance(places, str) else list(places)


def module_of(account: str) -> str:
    return f"module.{plan_offline.alias(account)}"


def ops_role_arn(name: str) -> str:
    return f"arn:aws:iam::{OPS}:role/{IDENTITIES[name]['identity']}"


def target_arn(server: str, account: str) -> str:
    return f"arn:aws:iam::{plan_offline.WORKLOAD_ACCOUNTS[account]}:role/{SERVERS[server]['aws']['target_role']}"


TARGET_ARNS = sorted(target_arn(server, account) for server in CHAINED for account in ACCOUNTS)

# service account -> the identity whose ops role it is bound to, and the account whose target role is
# chained to it (None for an identity without a target).
SERVICE_ACCOUNTS: dict[str, tuple[str, str | None]] = {
    **{spec["service_account"]: (name, None) for name, spec in IDENTITIES.items() if name not in CHAINED},
    **{sa: (server, account) for server in CHAINED for account, sa in SERVERS[server]["service_accounts"].items()},
}


@functools.cache
def kept_summary() -> dict[str, Any]:
    return json.loads((RESULTS / "plan-summary.json").read_text(encoding="utf-8"))


def expected_addresses() -> list[str]:
    out = ["terraform_data.catalog_checks", "aws_iam_policy.boundary"]
    out += [f'aws_iam_role.identity["{name}"]' for name in IDENTITIES]
    for kind in ("aws_iam_policy", "aws_iam_role_policy_attachment"):
        out += [f'{kind}.reads["{name}"]' for name in ("state-mcp", "cost-export")]
        out += [f'{kind}.chain["{server}"]' for server in CHAINED]
    out += [f'aws_eks_pod_identity_association.identity["{sa}"]' for sa in SERVICE_ACCOUNTS]
    for account in ACCOUNTS:
        module = module_of(account)
        out.append(f"{module}.aws_iam_policy.boundary")
        for server in CHAINED:
            out += [f'{module}.{kind}["{server}"]' for kind in
                    ("aws_iam_role.target", "aws_iam_policy.reads", "aws_iam_role_policy_attachment.reads")]
    return sorted(out)


# --- checks of a plan's summary: the kept one and a fresh one -------------------------------------------------

def check_resources(summary: dict[str, Any]) -> None:
    assert summary["resources_to_add"] == 47 == len(expected_addresses())
    assert summary["by_type"] == EXPECTED_BY_TYPE
    assert summary["addresses"] == expected_addresses()


def check_ops_reads(summary: dict[str, Any]) -> None:
    """The two read policies in the ops account: the state reader's mapped keys and key, the export's prefix."""
    policies = summary["policies"]
    state = {s["Sid"]: s for s in policies['aws_iam_policy.reads["state-mcp"]']}
    assert statement_actions(state.values()) == ops_actions("state-mcp") == expected_actions("state-mcp")
    keys = [f"live/{workspace}/terraform.tfstate" for workspace in WORKSPACES]
    assert sorted(state["StateObjects"]["Resource"]) == sorted(f"arn:aws:s3:::larkspur-terraform-state/{k}" for k in keys)
    assert state["StateKeysListed"]["Condition"] == {"StringEquals": {"s3:prefix": keys}}
    assert state["StateKeyDecrypt"]["Resource"] == plan_offline.STATE_KEY_ARN
    export = {s["Sid"]: s for s in policies['aws_iam_policy.reads["cost-export"]']}
    assert statement_actions(export.values()) == ops_actions("cost-mcp") == {"s3:GetObject", "s3:ListBucket"}
    assert export["ExportObjects"]["Resource"] == "arn:aws:s3:::larkspur-cost-exports/larkspur-cur2-daily/*"
    assert export["ExportListed"]["Resource"] == "arn:aws:s3:::larkspur-cost-exports"
    assert export["ExportListed"]["Condition"] == {"StringLike": {"s3:prefix": "larkspur-cur2-daily/*"}}
    assert "tflock" not in json.dumps([state, export]) and "payments-cde" not in json.dumps(policies)


def check_target_reads(summary: dict[str, Any]) -> None:
    """Each target role in each account holds exactly the reads its reader's fake mirrors for one account, on
    "*", under a boundary, for an hour at most."""
    for account in ACCOUNTS:
        module = module_of(account)
        for server in CHAINED:
            statements = summary["policies"][f'{module}.aws_iam_policy.reads["{server}"]']
            assert len(statements) == 1 and statements[0]["Effect"] == "Allow" and statements[0]["Resource"] == "*"
            assert statement_actions(statements) == target_actions(server), (account, server)
            assert summary["roles"][f'{module}.aws_iam_role.target["{server}"]'] == {
                "name": SERVERS[server]["aws"]["target_role"], "max_session_duration": 3600,
                "permissions_boundary": "known after apply"}


def check_trusts(summary: dict[str, Any]) -> None:
    """Each target role trusts the ops account, narrowed to its reader's ops role, the organization, and the
    session tags of that account's service account, with no external ID (C.7.4, C.8); each ops role trusts
    Pod Identity in the ops account's clusters."""
    for account in ACCOUNTS:
        for server in CHAINED:
            trust = summary["trusts"][f'{module_of(account)}.aws_iam_role.target["{server}"]']
            assert len(trust) == 1 and sorted(trust[0]["Action"]) == sorted(CHAIN)
            assert {k: v for k, v in trust[0].items() if k != "Action"} == {
                "Sid": "OpsReaderThroughPodIdentity", "Effect": "Allow", "Principal": {"AWS": f"arn:aws:iam::{OPS}:root"},
                "Condition": {
                    "ArnEquals": {"aws:PrincipalArn": ops_role_arn(server)},
                    "StringEquals": {
                        "aws:PrincipalOrgID": plan_offline.ORGANIZATION_ID,
                        "aws:RequestTag/eks-cluster-arn": CLUSTER_ARN,
                        "aws:RequestTag/kubernetes-namespace": "larkspur-ops",
                        "aws:RequestTag/kubernetes-service-account": SERVERS[server]["service_accounts"][account],
                    },
                }}, (account, server)
            assert "externalid" not in json.dumps(trust).lower()
    for name, spec in IDENTITIES.items():
        trust = summary["trusts"][f'aws_iam_role.identity["{name}"]']
        assert len(trust) == 1 and sorted(trust[0]["Action"]) == sorted(CHAIN)
        assert {k: v for k, v in trust[0].items() if k != "Action"} == {
            "Sid": "EKSPodIdentity", "Effect": "Allow", "Principal": {"Service": "pods.eks.amazonaws.com"},
            "Condition": {"StringLike": {"aws:RequestTag/eks-cluster-arn": f"arn:aws:eks:ca-central-1:{OPS}:cluster/*"}}}
        assert summary["roles"][f'aws_iam_role.identity["{name}"]'] == {
            "name": spec["identity"], "max_session_duration": 3600, "permissions_boundary": "known after apply"}


def check_chains(summary: dict[str, Any]) -> None:
    """The cloud and cost readers' ops roles hold sts:AssumeRole and sts:TagSession on their own three target
    roles and nothing else, and no other policy attached to a role holds an STS action."""
    for server in CHAINED:
        statements = summary["policies"][f'aws_iam_policy.chain["{server}"]']
        assert len(statements) == 1 and statements[0]["Effect"] == "Allow" and "Condition" not in statements[0]
        assert statement_actions(statements) == CHAIN
        assert sorted(as_list(statements[0]["Resource"])) == sorted(target_arn(server, a) for a in ACCOUNTS)
    for address, statements in summary["policies"].items():
        if ".chain[" not in address and not address.endswith(".boundary"):
            assert not any(action.startswith("sts:") for action in statement_actions(statements)), address


def check_boundaries(summary: dict[str, Any]) -> None:
    """The ops boundary: the ops roles' statements as the ceiling, the lock files and the never-list denied, and
    sts:AssumeRole denied on every role but the six targets. Each workload account's boundary: its target
    roles' reads as the ceiling, and the whole never-list denied on every resource, sts:AssumeRole included."""
    policies = summary["policies"]
    never = TF["locals"]["never_actions"]
    ops = policies["aws_iam_policy.boundary"]
    by_sid = {s["Sid"]: s for s in ops}
    attached = [s for address, statements in policies.items()
                if address.startswith(("aws_iam_policy.reads", "aws_iam_policy.chain")) for s in statements]
    assert sorted((s for s in ops if s["Effect"] == "Allow"), key=lambda s: s["Sid"]) == sorted(attached, key=lambda s: s["Sid"])
    assert by_sid["LockFiles"] == {"Action": "s3:*", "Effect": "Deny", "Sid": "LockFiles",
                                   "Resource": "arn:aws:s3:::larkspur-terraform-state/*.tflock"}
    assert by_sid["NeverList"]["Effect"] == "Deny" and by_sid["NeverList"]["Resource"] == "*"
    assert sorted(by_sid["NeverList"]["Action"]) == sorted(a for a in never if a != "sts:AssumeRole")
    outside = by_sid["AssumeRoleOutsideTargets"]
    assert {k: v for k, v in outside.items() if k != "NotResource"} == {"Sid": "AssumeRoleOutsideTargets", "Effect": "Deny",
                                                                        "Action": "sts:AssumeRole"}
    assert sorted(outside["NotResource"]) == TARGET_ARNS
    assert not any("Condition" in s for s in ops if s["Effect"] == "Deny")
    for arn in TARGET_ARNS:  # the chain stays open to the six targets ...
        assert allows(ops, "sts:AssumeRole", arn) and allows(ops, "sts:TagSession", arn) and not denies(ops, "sts:AssumeRole", arn)
    target_name = SERVERS["cloud-mcp"]["aws"]["target_role"]
    for arn in (f"arn:aws:iam::{OPS}:role/any-other-role", f"arn:aws:iam::{OPS}:role/{target_name}",
                f"arn:aws:iam::{cloud_fake.ACCOUNTS['lm-payments-cde']}:role/{target_name}"):
        assert denies(ops, "sts:AssumeRole", arn), arn  # ... and closed to every other role, a target's name included
    for account in ACCOUNTS:
        module = module_of(account)
        boundary = policies[f"{module}.aws_iam_policy.boundary"]
        reads = [s for server in CHAINED for s in policies[f'{module}.aws_iam_policy.reads["{server}"]']]
        assert sorted((s for s in boundary if s["Effect"] == "Allow"), key=lambda s: s["Sid"]) == sorted(reads, key=lambda s: s["Sid"])
        deny = [s for s in boundary if s["Effect"] == "Deny"]
        assert len(deny) == 1 and deny[0]["Sid"] == "NeverList" and deny[0]["Resource"] == "*" and "Condition" not in deny[0]
        assert sorted(deny[0]["Action"]) == sorted(never) and "sts:AssumeRole" in deny[0]["Action"]
        for arn in [*TARGET_ARNS, f"arn:aws:iam::{OPS}:role/any-other-role"]:
            assert denies(boundary, "sts:AssumeRole", arn), (account, arn)


def check_no_writes(summary: dict[str, Any]) -> None:
    """No role in any account holds a write: every action a role's policy allows is a read by its verb, or the
    state reader's decrypt, except the chain's two STS actions, which AWS files under "Write" (C.13.6) and the
    two chain policies hold on the named targets only."""
    never = TF["locals"]["never_actions"]
    for address, statements in summary["policies"].items():
        if address.endswith("aws_iam_policy.boundary"):
            continue
        for statement in statements:
            assert statement["Effect"] == "Allow", address
            for action in as_list(statement["Action"]):
                if address.startswith("aws_iam_policy.chain"):
                    assert action in CHAIN and set(as_list(statement["Resource"])) <= set(TARGET_ARNS), (address, action)
                    continue
                assert action == "kms:Decrypt" or action.split(":", 1)[1].startswith(READ_VERBS), (address, action)
                assert not matches(action, never), (address, action)


def check_bindings(summary: dict[str, Any]) -> None:
    """Ten service accounts, each bound to its identity's ops role, the cloud and cost readers' with that
    account's target role, and the session tags left on."""
    bindings = summary["pod_identity"]
    assert len(bindings) == len(SERVICE_ACCOUNTS) == 10
    for sa, (name, account) in SERVICE_ACCOUNTS.items():
        target = target_arn(name, account) if account else None
        assert bindings[f'aws_eks_pod_identity_association.identity["{sa}"]'] == {
            "cluster": "ops", "namespace": "larkspur-ops", "service_account": sa, "target_role_arn": target,
            "disable_session_tags": False}, sa
        assert summary["outputs"]["service_accounts"][f"larkspur-ops/{sa}"] == {"role_arn": ops_role_arn(name),
                                                                               "target_role_arn": target}
    assert summary["outputs"]["target_role_arns"] == {
        server: {account: target_arn(server, account) for account in ACCOUNTS} for server in CHAINED}


def check_bucket_deny(summary: dict[str, Any]) -> None:
    """The bucket's deny, known at plan time: the three writes, to every W5 role in every account by its ARN."""
    deny = summary["outputs"]["state_bucket_deny_policy"]
    assert len(deny) == 1 and deny[0]["Effect"] == "Deny" and deny[0]["Principal"] == "*"
    assert sorted(deny[0]["Action"]) == sorted(TF["locals"]["state_writes"])
    assert deny[0]["Resource"] == "arn:aws:s3:::larkspur-terraform-state/*"
    assert sorted(deny[0]["Condition"]["ArnEquals"]["aws:PrincipalArn"]) == sorted(
        [ops_role_arn(name) for name in IDENTITIES] + TARGET_ARNS)


SUMMARY_CHECKS = (check_resources, check_ops_reads, check_target_reads, check_trusts, check_chains, check_boundaries,
                  check_no_writes, check_bindings, check_bucket_deny)


# --- the configuration -------------------------------------------------------------------------------------

def test_the_provider_is_pinned_and_the_region_is_canadian():
    text = (AWS / "versions.tf").read_text(encoding="utf-8")
    assert 'version = "6.71.0"' in text
    assert TF["variable"]["region"]["default"] == "ca-central-1" and MANIFEST["regions"] == ["ca-central-1"]
    assert len(TF["provider"]) == 1 + len(ACCOUNTS)
    for provider in TF["provider"]:  # the ops account's and one per workload account, none with assume_role
        assert provider["name"] == "aws" and provider["region"] == "${var.region}" and "assume_role" not in provider


def test_six_identities_in_the_ops_account_each_with_its_service_accounts_in_the_platform_teams_namespace():
    assert set(IDENTITIES) == {"state-mcp", "cloud-mcp", "cost-mcp", "policy-mcp", "harness", "cost-export"}
    for server, spec in SERVERS.items():
        name = server.removesuffix("-mcp")
        assert spec["identity"] == IDENTITY.format(name)  # the identity the reader runs under in the lab
        if server in CHAINED:  # one service account per workload account, and a target role named after the reader
            assert "service_account" not in spec
            assert spec["service_accounts"] == {account: f"w5-{name}-reader-{account}" for account in ACCOUNTS}
            assert spec["aws"]["target_role"] == f"{spec['identity']}-target"
        else:
            assert spec["service_account"] == f"w5-{name}-reader" and "target_role" not in spec["aws"]
    assert CATALOG["harness"]["identity"] == "larkspur-drift-harness" and CATALOG["harness"]["service_account"] == "w5-harness"
    assert EXPORT["identity"] == "larkspur-drift-cost-export-reader" and EXPORT["service_account"] == "w5-cost-export-reader"
    assert {spec["namespace"] for spec in IDENTITIES.values()} == {"larkspur-ops"}
    assert {spec["team"] for spec in IDENTITIES.values()} == {"platform-engineering"}
    names = [spec["service_account"] for name, spec in IDENTITIES.items() if name not in CHAINED]
    names += [sa for server in CHAINED for sa in SERVERS[server]["service_accounts"].values()]
    assert len(names) == len(set(names)) == len(SERVICE_ACCOUNTS) == 10
    assert len({spec["identity"] for spec in IDENTITIES.values()}) == 6


def test_the_service_accounts_are_new_in_the_namespace_w2_w3_and_w4_bind_in():
    """An association binds one service account in one namespace; W5's must take no name W2's servers,
    W3's writer, or W4's agents already hold in larkspur-ops."""
    w2_vars = load(WORKFLOWS / "w2-ops-assistant" / "aws")["variable"]
    w2 = yaml.safe_load((WORKFLOWS / "w2-ops-assistant" / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
    taken = {(w2_vars["servers_namespace"]["default"], server) for server in w2["servers"]}  # named after the server
    w3_vars = load(WORKFLOWS / "w3-incident" / "aws")["variable"]
    taken.add((w3_vars["servers_namespace"]["default"], w3_vars["writer_service_account"]["default"]))
    w4 = yaml.safe_load((WORKFLOWS / "w4-change" / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
    taken |= {(agent["namespace"], agent["service_account"]) for agent in w4["agents"].values()}
    assert ("larkspur-ops", "writer-mcp") in taken and ("larkspur-ops", "w4-scribe") in taken
    ours = {("larkspur-ops", sa) for sa in SERVICE_ACCOUNTS}
    assert len(ours) == 10 and not ours & taken, ours & taken


def test_each_map_account_has_a_provider_a_module_call_and_a_service_account_per_reader():
    """The map's three accounts, each with a provider alias, a module call under it, and a service account per
    reader; the placeholder IDs are the fakes' own, and none is the ops account. The map names no workspace
    in the ops account, so no account read stays on an ops role."""
    assert ACCOUNTS == ["lm-network-prod", "lm-claims-prod", "lm-sandbox"]  # lm-payments-cde is in no grant
    aliases = {provider["alias"] for provider in TF["provider"] if "alias" in provider}
    assert aliases == {plan_offline.alias(account) for account in ACCOUNTS} == set(TF["module"])
    for account in ACCOUNTS:
        alias = plan_offline.alias(account)
        module = TF["module"][alias]
        assert module["source"] == "./workload-account" and module["account"] == account
        assert module["providers"] == {"aws": f"${{aws.{alias}}}"}
        assert module["readers"] == "${local.target_readers}" and module["never_actions"] == "${local.never_actions}"
        assert module["ops_account_id"] == "${var.account_id}" and module["organization_id"] == "${var.organization_id}"
        assert f"${{module.{alias}}}" in TF["locals"]["account_modules"]
        for server in CHAINED:
            assert account in SERVERS[server]["service_accounts"], (server, account)
    assert len(TF["locals"]["account_modules"]) == len(ACCOUNTS)
    assert plan_offline.WORKLOAD_ACCOUNTS == {account: cloud_fake.ACCOUNTS[account] for account in ACCOUNTS}
    assert OPS not in plan_offline.WORKLOAD_ACCOUNTS.values() and OPS not in cloud_fake.ACCOUNTS.values()
    override = plan_offline.override()  # placeholder credentials for every provider, and no assume_role block
    assert override.count('provider "aws"') == 1 + len(ACCOUNTS) and "assume_role" not in override
    for account in ACCOUNTS:
        assert f'= "{plan_offline.alias(account)}"' in override


def test_each_reader_holds_what_its_fake_mirrors_and_no_more():
    assert set(DESCRIBE_ACTIONS) == set(cloud_fake.KINDS)
    for server, spec in SERVERS.items():
        tools = lock_tools(server)
        assert tools == {tool for tool, entry in CATALOG["tools"].items() if entry["server"] == server}
        assert tools <= set(TOOL_ACTIONS), tools - set(TOOL_ACTIONS)
        actions = spec["aws"]["role_actions"]
        assert len(actions) == len(set(actions)) and set(actions) == expected_actions(server), server
        # aws/ sends the account-wide reads (neither S3 nor KMS) to the target roles; they are exactly the
        # actions of the tools that read the account they name.
        assert {a for a in actions if not a.startswith(("s3:", "kms:"))} == target_actions(server), server
    for server, operations in OPERATIONS.items():
        source = (W5 / "servers" / f"{server.removesuffix('-mcp')}_fake.py").read_text(encoding="utf-8")
        for operation in operations:
            assert operation in source, (server, operation)
    assert {server for server in SERVERS if target_actions(server)} == set(CHAINED)
    assert target_actions("cloud-mcp") == expected_actions("cloud-mcp") and not ops_actions("cloud-mcp")
    assert ops_actions("state-mcp") == expected_actions("state-mcp") and not target_actions("state-mcp")
    assert target_actions("cost-mcp") | ops_actions("cost-mcp") == expected_actions("cost-mcp")
    assert TF["locals"]["chained"] == "${sort([for name, server in local.servers : name if can(server.aws.target_role)])}"
    assert "actions = local.account_reads[name]" in TF["locals"]["target_readers"]
    # The cost fake reads the anomalies and never lists the monitors, so the reader is not granted the listing.
    assert "GetAnomalyMonitors" not in (W5 / "servers" / "cost_fake.py").read_text(encoding="utf-8")
    assert "ce:GetAnomalyMonitors" not in SERVERS["cost-mcp"]["aws"]["role_actions"]


def test_the_policy_reader_and_the_harness_hold_no_aws_action_and_get_a_role_with_no_policy():
    assert SERVERS["policy-mcp"]["aws"]["role_actions"] == [] and CATALOG["harness"]["aws"]["role_actions"] == []
    assert set(TF["locals"]["read_documents"]) == {"state-mcp", "cost-export"}
    assert TF["locals"]["chain_documents"].startswith("${{for name in local.chained : name =>")
    for kind, documents in (("reads", "${local.read_documents}"), ("chain", "${local.chain_documents}")):
        assert TF["resource"]["aws_iam_policy"][kind]["for_each"] == documents
        assert TF["resource"]["aws_iam_role_policy_attachment"][kind]["for_each"] == documents
    identities = TF["locals"]["identities"]
    assert "local.servers" in identities and "harness = local.catalog.harness" in identities
    assert "cost-export = local.export" in identities and TF["locals"]["export"] == '${local.servers["cost-mcp"].export}'
    assert TF["resource"]["aws_iam_role"]["identity"]["for_each"] == "${local.identities}"


def test_the_state_reader_reads_the_mapped_state_keys_and_never_a_lock_file():
    assert WORKSPACES == ["network-live", "claims-api-prod", "sandbox-quill"]  # payments-cde is in no grant
    prefix = SERVERS["state-mcp"]["aws"]["resources"]["prefix"]
    assert all(prefix.replace("*", workspace).endswith("/terraform.tfstate") for workspace in WORKSPACES)
    assert TF["locals"]["workspaces"] == "${local.workspace_map.teams[local.catalog.membership.group]}"
    statements = {s["sid"]: s for s in TF["data"]["aws_iam_policy_document"]["state_reader"]["statement"]}
    assert statements["StateObjects"]["resources"] == "${local.state_objects}"
    assert statements["StateKeysListed"]["condition"][0] == {"test": "StringEquals", "variable": "s3:prefix",
                                                             "values": "${local.state_keys}"}
    assert statements["StateKeyDecrypt"]["resources"] == ["${var.state_kms_key_arn}"]
    lock = next(s for s in TF["data"]["aws_iam_policy_document"]["boundary"]["statement"] if s["sid"] == "LockFiles")
    assert lock == {"sid": "LockFiles", "effect": "Deny", "actions": ["s3:*"], "resources": ["${local.state_bucket_arn}/*.tflock"]}
    assert code_text().count(".tflock") == 1  # named once, in the deny


def test_the_decrypt_rests_on_the_corpus_and_is_the_state_readers_alone():
    """kms:Decrypt is granted because the corpus says Larkspur's buckets are SSE-KMS with a customer-managed
    key for Confidential data, and state is Confidential (W5-D4)."""
    module = (WORKFLOWS / "w1-knowledge-assistant" / "corpus" / "docs" / "tfmod-s3-secure-bucket.md").read_text(encoding="utf-8")
    assert "The only approved way to create an S3 bucket at Larkspur." in module
    assert "SSE-KMS with a customer-managed key" in module
    assert MANIFEST["data_class_max"] == "confidential"
    holders = {server: [a for a in spec["aws"]["role_actions"] if a.startswith("kms:")] for server, spec in SERVERS.items()}
    assert {server: kms for server, kms in holders.items() if kms} == {"state-mcp": ["kms:Decrypt"]}
    assert TF["variable"]["state_kms_key_arn"].get("default") is None  # the state stack gives the key's ARN


def test_the_export_is_read_in_the_ops_account_by_an_identity_of_its_own():
    """The organization's CUR 2.0 export lands in a bucket the ops account owns (C.11): the export identity
    reads it there with the object and listing reads under the export's prefix, no key (SSE-S3, C.11.3), and
    no target role; the bucket is a variable and never the state bucket."""
    assert EXPORT == {"identity": "larkspur-drift-cost-export-reader", "team": "platform-engineering",
                      "namespace": "larkspur-ops", "service_account": "w5-cost-export-reader",
                      "prefix": "larkspur-cur2-daily/*"}
    statements = {s["sid"]: s for s in TF["data"]["aws_iam_policy_document"]["export_reader"]["statement"]}
    assert statements["ExportObjects"]["actions"] == '${local.object_reads["cost-mcp"]}'
    assert statements["ExportObjects"]["resources"] == ["${local.export_bucket_arn}/${local.export.prefix}"]
    assert statements["ExportListed"]["actions"] == '${local.listing_reads["cost-mcp"]}'
    assert statements["ExportListed"]["condition"][0] == {"test": "StringLike", "variable": "s3:prefix",
                                                          "values": ["${local.export.prefix}"]}
    assert TF["locals"]["export_bucket_arn"] == "arn:aws:s3:::${var.cost_export_bucket}"
    bucket = TF["variable"]["cost_export_bucket"]
    assert bucket["default"] == "larkspur-cost-exports" != SERVERS["state-mcp"]["aws"]["resources"]["bucket"]
    assert bucket["validation"][0]["condition"] == "${var.cost_export_bucket != local.state.bucket}"
    assert not any(action.startswith("kms:") for action in ops_actions("cost-mcp"))
    assert SERVICE_ACCOUNTS[EXPORT["service_account"]] == ("cost-export", None)


def test_each_identity_is_bound_through_pod_identity_under_its_boundary():
    role = TF["resource"]["aws_iam_role"]["identity"]
    assert role["name"] == "${each.value.identity}"
    assert role["permissions_boundary"] == "${aws_iam_policy.boundary.arn}"
    assert role["max_session_duration"] == 3600
    trust = TF["data"]["aws_iam_policy_document"]["pod_identity_trust"]["statement"][0]
    assert trust["principals"][0] == {"type": "Service", "identifiers": ["pods.eks.amazonaws.com"]}
    assert sorted(trust["actions"]) == ["sts:AssumeRole", "sts:TagSession"]
    assert trust["condition"][0]["variable"] == "aws:RequestTag/eks-cluster-arn"
    association = TF["resource"]["aws_eks_pod_identity_association"]["identity"]
    assert association["for_each"] == "${local.bindings}"
    assert association["namespace"] == "${each.value.namespace}" and association["service_account"] == "${each.key}"
    assert association["role_arn"] == "${aws_iam_role.identity[each.value.identity].arn}"
    assert association["target_role_arn"] == "${each.value.target_role_arn}"
    assert association["disable_session_tags"] is False  # the targets' trusts match the session tags (C.7.4)
    assert "setproduct(local.chained, local.read_accounts)" in TF["locals"]["bindings"]
    target = MOD["resource"]["aws_iam_role"]["target"]
    assert target["for_each"] == "${var.readers}" and target["name"] == "${each.value.role}"
    assert target["permissions_boundary"] == "${aws_iam_policy.boundary.arn}" and target["max_session_duration"] == 3600
    check_bindings(kept_summary())


def test_each_target_role_holds_exactly_its_fakes_reads():
    reads = MOD["data"]["aws_iam_policy_document"]["reads"]
    assert reads["for_each"] == "${var.readers}"
    assert reads["statement"] == [{"sid": "${each.value.sid}Reads", "effect": "Allow", "actions": "${each.value.actions}",
                                   "resources": ["*"]}]
    assert MOD["resource"]["aws_iam_policy"]["reads"]["policy"] == "${data.aws_iam_policy_document.reads[each.key].json}"
    assert MOD["resource"]["aws_iam_role_policy_attachment"]["reads"]["role"] == "${aws_iam_role.target[each.key].name}"
    check_target_reads(kept_summary())


def test_each_target_trust_carries_the_ops_role_the_organization_and_the_session_tags():
    trust = MOD["data"]["aws_iam_policy_document"]["trust"]["statement"][0]
    assert trust["principals"] == [{"type": "AWS", "identifiers": ["arn:aws:iam::${var.ops_account_id}:root"]}]
    assert sorted(trust["actions"]) == sorted(CHAIN)
    assert [(c["test"], c["variable"], c["values"]) for c in trust["condition"]] == [
        ("ArnEquals", "aws:PrincipalArn", ["${each.value.ops_role_arn}"]),
        ("StringEquals", "aws:PrincipalOrgID", ["${var.organization_id}"]),
        ("StringEquals", "aws:RequestTag/eks-cluster-arn", ["${var.cluster_arn}"]),
        ("StringEquals", "aws:RequestTag/kubernetes-namespace", ["${each.value.namespace}"]),
        ("StringEquals", "aws:RequestTag/kubernetes-service-account", ["${local.service_accounts[each.key]}"]),
    ]
    code = code_text().lower()
    assert "externalid" not in code and "external_id" not in code  # no external ID condition (section E)
    check_trusts(kept_summary())


def test_the_ops_chain_roles_hold_only_the_two_sts_actions_on_their_targets():
    chain = TF["data"]["aws_iam_policy_document"]["chain"]
    assert chain["for_each"] == "${local.target_readers}"
    assert chain["statement"] == [{"sid": "${each.value.sid}Targets", "effect": "Allow", "actions": "${local.chain_actions}",
                                   "resources": "${values(local.target_role_arns[each.key])}"}]
    assert TF["locals"]["chain_actions"] == ["sts:AssumeRole", "sts:TagSession"]
    assert [server for server, spec in SERVERS.items() if "target_role" in spec["aws"]] == list(CHAINED)
    check_chains(kept_summary())


def test_the_ops_boundary_denies_assume_role_outside_the_targets_and_the_target_boundaries_deny_it_outright():
    ops = {s["sid"]: s for s in TF["data"]["aws_iam_policy_document"]["boundary"]["statement"]}
    assert ops["NeverList"]["actions"] == "${local.ops_never_actions}"
    assert ops["AssumeRoleOutsideTargets"] == {"sid": "AssumeRoleOutsideTargets", "effect": "Deny",
                                               "actions": ["sts:AssumeRole"], "not_resources": "${local.target_arns}"}
    target = MOD["data"]["aws_iam_policy_document"]["boundary"]
    assert target["statement"] == [{"sid": "NeverList", "effect": "Deny", "actions": "${var.never_actions}",
                                    "resources": ["*"]}]
    assert "sts:AssumeRole" in TF["locals"]["never_actions"]
    assert MOD["resource"]["aws_iam_role"]["target"]["permissions_boundary"] == "${aws_iam_policy.boundary.arn}"
    check_boundaries(kept_summary())


def test_the_boundaries_deny_every_never_list_action_and_none_of_the_reads():
    boundary = TF["data"]["aws_iam_policy_document"]["boundary"]
    # The ceiling: the ops roles' own statements, the chains included.
    assert boundary["source_policy_documents"] == "${concat(values(local.read_documents), values(local.chain_documents))}"
    never = TF["locals"]["never_actions"]
    assert isinstance(never, list) and len(never) == len(set(never)) == 36
    assert set(NEVER) | GITHUB_ENTRIES == set(MANIFEST["never"]) == set(CATALOG["never"])
    for entry, actions in NEVER.items():
        for action in actions:
            assert matches(action, never), (entry, action)
    assert set(TF["locals"]["state_writes"]) <= set(never)
    assert "ec2:*" not in never and "s3:*" not in never  # the cloud reader describes; the readers read objects
    for server, spec in SERVERS.items():
        for action in spec["aws"]["role_actions"]:
            assert not matches(action, never), (server, action)


def test_no_role_in_any_account_holds_a_write():
    check_no_writes(kept_summary())


def test_no_role_could_have_made_any_change_the_fixtures_trail_records():
    """Every write in the fakes' audit trail (LookupEvents with ReadOnly false, ninety days, every account) is
    beyond every W5 role, and each one the never-list covers is denied outright. Starting an instance and
    creating a volume are on no never-list: the ceiling alone keeps them out."""
    writes = set()
    for account in cloud_fake.ACCOUNTS:
        page = cloud_fake.lookup_events(account, cloud_fake.REGION, "ReadOnly", "false", cloud_fake.MAX_LOOKUP_DAYS)
        writes |= {f"{e['EventSource'].split('.')[0]}:{e['EventName']}" for e in page["response"]["Events"]}
    assert {"ec2:AuthorizeSecurityGroupIngress", "ec2:CreateRoute", "ec2:DeleteVolume"} <= writes  # Jenkins, the route, the volume
    granted = {action for spec in SERVERS.values() for action in spec["aws"]["role_actions"]} | CHAIN
    assert not {write for write in writes if matches(write, granted)}
    never = TF["locals"]["never_actions"]
    assert {write for write in writes if not matches(write, never)} == {"ec2:StartInstances", "ec2:CreateVolume"}


def test_the_bucket_deny_names_every_role_and_is_left_to_the_state_stack():
    statement = TF["data"]["aws_iam_policy_document"]["state_bucket_deny"]["statement"][0]
    assert statement["effect"] == "Deny" and statement["actions"] == "${local.state_writes}"
    assert statement["resources"] == ["${local.state_bucket_arn}/*"]
    assert statement["principals"][0] == {"type": "*", "identifiers": ["*"]}
    assert statement["condition"][0] == {"test": "ArnEquals", "variable": "aws:PrincipalArn",
                                         "values": "${sort(concat(values(local.role_arns), local.target_arns))}"}
    assert TF["locals"]["state_writes"] == ["s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"]
    assert "local.identities" in TF["locals"]["role_arns"]  # every identity, the harness and the export's included
    # The bucket's one policy is the state stack's: this configuration outputs the statement and writes none.
    assert "aws_s3_bucket_policy" not in TF["resource"] and "aws_s3_bucket_policy" not in code_text()
    assert TF["output"]["state_bucket_deny_policy"]["value"] == "${data.aws_iam_policy_document.state_bucket_deny.json}"
    assert "NotPrincipal" not in code_text()
    check_bucket_deny(kept_summary())


def test_the_catalog_keeps_each_app_on_its_side_of_the_line():
    import github_fake  # writer/, on the path through conftest
    apps, fork, upstream = GITHUB["apps"], GITHUB["fork"], GITHUB["upstream"]
    assert installs(apps["larkspur-w5-fork"]) == [fork] and apps["larkspur-w5-fork"]["permissions"] == {"contents": "write"}
    assert installs(apps["larkspur-w5-upstream"]) == [upstream]
    assert apps["larkspur-w5-upstream"]["permissions"] == {"pull_requests": "write", "metadata": "read"}
    assert {name: app["id"] for name, app in apps.items()} == {name: app["id"] for name, app in github_fake.APPS.items()}
    ruleset = GITHUB["ruleset"]
    assert ruleset["bypass_actors"] == [] and ruleset["require_pull_request"]["code_owner_review"] is True
    assert ruleset["require_status_checks"] == [{"context": "validate", "integration_id": github_fake.GITHUB_ACTIONS_ID}]
    assert "restrict_updates" not in ruleset  # dropped: no page says what "Restrict updates" does to a merge (A.12.1)
    for name, app in apps.items():
        if upstream in installs(app):
            for permission in ("contents", "workflows", "administration"):
                assert app["permissions"].get(permission) not in ("write", "admin"), (name, permission)


def test_the_plan_refuses_by_precondition_what_would_cross_the_line():
    checks = TF["resource"]["terraform_data"]["catalog_checks"]["lifecycle"][0]["precondition"]
    conditions = " ".join(check["condition"] for check in checks)
    for name in ("offending_permissions", "fork_apps_upstream", "bypassing_apps", "local.bypass_actors", "local.code_owner_review",
                 "local.w5_never", "not_reads", "harness.aws.role_actions", "local.granted", "local.account_disagreements"):
        assert name in conditions, name
    # A W5 App on the bypass list is found by actor type and id, never by its name inside the list's JSON (A.6.4).
    assert "actor.actor_type" in TF["locals"]["bypassing_apps"] and "actor.actor_id" in TF["locals"]["bypassing_apps"]
    assert "jsonencode" not in TF["locals"]["bypassing_apps"] and "strcontains" not in TF["locals"]["bypassing_apps"]
    assert all(check["error_message"].startswith("The catalog") for check in checks[:5])  # named for what they check
    assert TF["locals"]["merge_capable"] == ["contents", "workflows", "administration"]
    assert TF["locals"]["w5_never"] == ["apply_plan", "merge_pull_request", "approve_pull_request", "delete_resource",
                                        "stop_instance", "modify_security_group"]
    # The map holds at IAM: its accounts against the module calls and the catalog's service accounts, both ways.
    assert TF["locals"]["mapped_accounts"] == "${local.workspace_map.accounts[local.catalog.membership.group]}"
    assert "local.target_accounts[account][name]" in TF["locals"]["accounts_without_targets"]
    assert "local.servers[name].service_accounts[account]" in TF["locals"]["accounts_without_service_accounts"]
    assert "keys(local.target_accounts)" in TF["locals"]["accounts_outside_the_map"]
    for name in ("accounts_without_targets", "accounts_without_service_accounts", "accounts_outside_the_map"):
        assert f"local.{name}" in TF["locals"]["account_disagreements"], name
    assert TF["locals"]["target_accounts"] == "${{for m in local.account_modules : m.account => m.target_roles}}"


def test_the_kept_results_are_this_plan_and_name_no_local_path():
    text = (RESULTS / "terraform-plan.txt").read_text(encoding="utf-8")
    summary = kept_summary()
    assert "Plan: 47 to add, 0 to change, 0 to destroy." in text
    check_resources(summary)
    assert summary["account_id"] == OPS and summary["measured"] == "2026-11-10"
    assert summary["workload_account_ids"] == plan_offline.WORKLOAD_ACCOUNTS
    assert summary["organization_id"] == plan_offline.ORGANIZATION_ID
    check_ops_reads(summary)  # the kept policies are the catalog's of today
    for content in (text, json.dumps(summary)):
        assert not plan_offline.LOCAL_PATH.search(content)
    for path in ("C:\\Users\\someone\\x", "C:/Users/someone/x", "/home/someone/x", "/tmp/w5-aws-plan-x"):
        assert plan_offline.LOCAL_PATH.search(path), path
    for sample in ("https://registry.terraform.io/hashicorp/aws", "arn:aws:s3:::larkspur-terraform-state/live/x"):
        assert not plan_offline.LOCAL_PATH.search(sample), sample


# --- the offline plan ----------------------------------------------------------------------------------------

PLUGIN_DIR = Path(os.environ["TF_PLUGIN_CACHE_DIR"]) if os.environ.get("TF_PLUGIN_CACHE_DIR") else None
needs_terraform = pytest.mark.skipif(shutil.which("terraform") is None or PLUGIN_DIR is None or not PLUGIN_DIR.exists(),
                                     reason="needs terraform and TF_PLUGIN_CACHE_DIR with hashicorp/aws 6.71.0")


def edit_yaml(name: str, change: Callable[[dict[str, Any]], None]) -> Callable[[Path], None]:
    """A mutation for plan_offline.plan: load the copied catalog file `name`, change it, write it back."""
    def mutate(work: Path) -> None:
        path = work / "catalog" / name
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return mutate


@needs_terraform
def test_the_offline_plan_has_the_forty_seven_resources(tmp_path):
    summary = plan_offline.plan(tmp_path, PLUGIN_DIR)
    assert "Plan: 47 to add, 0 to change, 0 to destroy." in summary["plan_text"]
    assert summary["workload_account_ids"] == plan_offline.WORKLOAD_ACCOUNTS
    for check in SUMMARY_CHECKS:
        check(summary)


@needs_terraform
def test_the_offline_plan_stops_when_the_catalog_gives_the_upstream_app_contents_write(tmp_path):
    def give_the_upstream_app_contents_write(catalog: dict[str, Any]) -> None:
        catalog["github"]["apps"]["larkspur-w5-upstream"]["permissions"]["contents"] = "write"

    with pytest.raises(RuntimeError) as failed:
        plan_offline.plan(tmp_path, PLUGIN_DIR, mutate=edit_yaml("tools.yaml", give_the_upstream_app_contents_write))
    reason = " ".join(str(failed.value).split())  # terraform wraps the message; compare on one line
    assert "merge-capable" in reason and "larkspur-w5-upstream: contents: write" in reason


def _install_the_fork_app_upstream(catalog: dict[str, Any]) -> None:
    catalog["github"]["apps"]["larkspur-w5-fork"]["installed_on"] = [catalog["github"]["fork"], catalog["github"]["upstream"]]


def _make_the_upstream_app_a_bypass_actor(catalog: dict[str, Any]) -> None:
    """GitHub's shape, which names an App by its id and never by its name (A.6.4)."""
    catalog["github"]["ruleset"]["bypass_actors"] = [{"actor_id": 410002, "actor_type": "Integration", "bypass_mode": "always"}]


def _drop_the_code_owner_review(catalog: dict[str, Any]) -> None:
    catalog["github"]["ruleset"]["require_pull_request"]["code_owner_review"] = False


@needs_terraform
@pytest.mark.parametrize(("change", "expected"), [
    (_install_the_fork_app_upstream, "The catalog installs the fork App on the upstream: larkspur-w5-fork"),
    (_make_the_upstream_app_a_bypass_actor, "names an App of W5 as a bypass actor: larkspur-w5-upstream (Integration 410002)"),
    (_drop_the_code_owner_review, "The catalog's ruleset does not require a code owner's review"),
], ids=["fork-app-on-the-upstream", "app-as-bypass-actor", "no-code-owner-review"])
def test_the_offline_plan_stops_when_an_app_could_reach_past_the_ruleset(tmp_path, change, expected):
    with pytest.raises(RuntimeError) as failed:
        plan_offline.plan(tmp_path, PLUGIN_DIR, mutate=edit_yaml("tools.yaml", change))
    assert expected in " ".join(str(failed.value).split())


@needs_terraform
def test_the_offline_plan_allows_the_upstream_app_on_the_fork_as_well(tmp_path):
    """The fallback should GitHub refuse a pull request from a private fork its opener cannot see (fact sheet A.11):
    the upstream App installed on the fork too. It adds no Contents write anywhere, and the plan passes."""
    def install_the_upstream_app_on_the_fork(catalog: dict[str, Any]) -> None:
        github = catalog["github"]
        github["apps"]["larkspur-w5-upstream"]["installed_on"] = [github["upstream"], github["fork"]]

    summary = plan_offline.plan(tmp_path, PLUGIN_DIR, mutate=edit_yaml("tools.yaml", install_the_upstream_app_on_the_fork))
    assert "Plan: 47 to add, 0 to change, 0 to destroy." in summary["plan_text"]


@needs_terraform
def test_the_offline_plan_stops_for_any_bypass_actor_and_names_a_w5_app_only_by_its_id(tmp_path):
    """GitHub Actions on the bypass list: no App of W5, and still refused, because no actor may skip the code owner's
    review or the required check. The old check matched an App's name inside the list's JSON and passed it."""
    def make_github_actions_a_bypass_actor(catalog: dict[str, Any]) -> None:
        catalog["github"]["ruleset"]["bypass_actors"] = [{"actor_id": 15368, "actor_type": "Integration", "bypass_mode": "always"}]

    with pytest.raises(RuntimeError) as failed:
        plan_offline.plan(tmp_path, PLUGIN_DIR, mutate=edit_yaml("tools.yaml", make_github_actions_a_bypass_actor))
    reason = " ".join(str(failed.value).split())
    assert "The catalog's ruleset names bypass actors: Integration 15368 (always)" in reason
    assert "an App of W5" not in reason


def _map_the_payments_account(workspace_map: dict[str, Any]) -> None:
    """The payments CDE's account added to the map, with no module call and no service account for it."""
    workspace_map["accounts"][GROUP].append("lm-payments-cde")


def _drop_a_service_account(catalog: dict[str, Any]) -> None:
    del catalog["servers"]["cost-mcp"]["service_accounts"]["lm-sandbox"]


def _unmap_the_sandbox(workspace_map: dict[str, Any]) -> None:
    """lm-sandbox taken out of the map while its module call and service accounts stay."""
    workspace_map["accounts"][GROUP].remove("lm-sandbox")


@needs_terraform
@pytest.mark.parametrize(("name", "change", "expected"), [
    ("workspace-map.yaml", _map_the_payments_account, "lm-payments-cde has no target roles; lm-payments-cde has no service accounts"),
    ("tools.yaml", _drop_a_service_account, "lm-sandbox has no service accounts"),
    ("workspace-map.yaml", _unmap_the_sandbox, "lm-sandbox has target roles or service accounts and is not in the map"),
], ids=["map-account-without-targets", "map-account-without-a-service-account", "targets-outside-the-map"])
def test_the_offline_plan_stops_when_the_map_and_the_identities_disagree(tmp_path, name, change, expected):
    with pytest.raises(RuntimeError) as failed:
        plan_offline.plan(tmp_path, PLUGIN_DIR, mutate=edit_yaml(name, change))
    reason = " ".join(str(failed.value).split())
    assert "Resource precondition failed" in reason and "disagree on the accounts" in reason
    assert expected in reason
