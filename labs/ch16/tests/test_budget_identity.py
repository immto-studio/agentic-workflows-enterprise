"""The identity half of the kill switch, offline: botocore's Stubber answers for IAM, and no AWS call is made.

`identity.pull` puts the deny-all policy, with its `aws:TokenIssueTime` statement, on a workflow's harness role
and tool roles; `identity.release` leaves only the revoke statement, moved to the release; `--purge` removes the
policy. Step 7 runs the same functions with real credentials and times them.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import botocore.session
import identity
import pytest
import yaml
from botocore.stub import Stubber

LAB = Path(__file__).resolve().parents[1]
CH05_W3 = LAB.parent / "ch05" / "manifest" / "w3-incident.yaml"
W3 = yaml.safe_load(CH05_W3.read_text(encoding="utf-8"))
PULLED = datetime(2026, 11, 3, 23, 40, 5, tzinfo=timezone.utc)
ROLES = ["w3-incident-harness", "w3-incident-get-pod-status", "w3-incident-get-recent-alerts",
         "w3-incident-restart-deployment"]


def iam():
    session = botocore.session.get_session()
    return session.create_client("iam", region_name="us-east-1", aws_access_key_id="LARKSPURLABDUMMYKEY0",
                                 aws_secret_access_key="dummy-secret-for-the-stubber")


def role(name: str, workflow: str = "w3-incident") -> dict:
    return {"Role": {"Path": "/", "RoleName": name, "RoleId": "AROALARKSPURLAB00001",
                     "Arn": f"arn:aws:iam::123456789012:role/{name}", "CreateDate": PULLED,
                     "Tags": [{"Key": "workflow", "Value": workflow}, {"Key": "owner", "Value": W3["owner"]}]}}


def test_the_roles_are_chapter_6s():
    assert identity.role_names(W3) == ROLES
    module = (LAB.parent / "ch06" / "terraform" / "modules" / "manifest_roles" / "main.tf").read_text(encoding="utf-8")
    assert 'substr("${local.workflow}-${replace(tool, "_", "-")}", 0, 64)' in module
    assert 'name                 = "${local.workflow}-harness"' in \
        (LAB.parent / "ch06" / "terraform" / "iam.tf").read_text(encoding="utf-8")


def test_the_pull_document_denies_everything_and_names_issued_sessions():
    document = identity.pull_document(PULLED)
    deny_all, revoke = document["Statement"]
    assert document["Version"] == "2012-10-17"
    assert deny_all == {"Sid": "KillSwitchDenyAll", "Effect": "Deny", "Action": "*", "Resource": "*"}
    assert revoke["Effect"] == "Deny" and revoke["Action"] == "*" and revoke["Resource"] == "*"
    # AWS's revoke: DateLessThan on aws:TokenIssueTime, about 30 seconds past the pull (fact sheet 8.3)
    assert revoke["Condition"] == {"DateLessThan": {"aws:TokenIssueTime": "2026-11-03T23:40:35Z"}}
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", revoke["Condition"]["DateLessThan"]["aws:TokenIssueTime"])
    assert len(json.dumps(document)) < 2048  # far inside a role's inline policy quota


def test_pull_puts_the_policy_on_the_harness_role_and_every_tool_role():
    client = iam()
    document = json.dumps(identity.pull_document(PULLED))
    with Stubber(client) as stub:
        for name in ROLES:
            stub.add_response("get_role", role(name), {"RoleName": name})
            stub.add_response("put_role_policy", {}, {"RoleName": name, "PolicyName": "larkspur-kill-switch",
                                                      "PolicyDocument": document})
        results = identity.pull(client, ROLES, "w3-incident", PULLED)
        stub.assert_no_pending_responses()
    assert [(r.role, r.action) for r in results] == [(name, "put") for name in ROLES]


def test_pull_never_touches_a_role_of_another_workflow():
    client = iam()
    with Stubber(client) as stub:
        stub.add_response("get_role", role(ROLES[0], workflow="w2-ops-assistant"), {"RoleName": ROLES[0]})
        results = identity.pull(client, ROLES[:1], "w3-incident", PULLED)
        stub.assert_no_pending_responses()  # and no put_role_policy was made
    assert results[0].action == "skipped" and "w2-ops-assistant" in results[0].why


def test_pull_reports_a_missing_role_and_carries_on():
    client = iam()
    document = json.dumps(identity.pull_document(PULLED))
    with Stubber(client) as stub:
        stub.add_client_error("get_role", service_error_code="NoSuchEntity", http_status_code=404,
                              expected_params={"RoleName": ROLES[0]})
        stub.add_response("get_role", role(ROLES[1]), {"RoleName": ROLES[1]})
        stub.add_response("put_role_policy", {}, {"RoleName": ROLES[1], "PolicyName": "larkspur-kill-switch",
                                                  "PolicyDocument": document})
        results = identity.pull(client, ROLES[:2], "w3-incident", PULLED)
        stub.assert_no_pending_responses()
    assert [(r.action, r.why) for r in results] == [("skipped", "no such role"), ("put", "deny-all and revoke")]


def test_release_leaves_only_the_revoke_moved_to_the_release():
    released = datetime(2026, 11, 4, 2, 15, tzinfo=timezone.utc)
    document = identity.release_document(released)
    assert [s["Sid"] for s in document["Statement"]] == ["KillSwitchRevokeIssued"]
    assert document["Statement"][0]["Condition"] == {"DateLessThan": {"aws:TokenIssueTime": "2026-11-04T02:15:00Z"}}
    client = iam()
    with Stubber(client) as stub:
        stub.add_response("get_role", role(ROLES[0]), {"RoleName": ROLES[0]})
        stub.add_response("put_role_policy", {}, {"RoleName": ROLES[0], "PolicyName": "larkspur-kill-switch",
                                                  "PolicyDocument": json.dumps(document)})
        results = identity.release(client, ROLES[:1], "w3-incident", released)
        stub.assert_no_pending_responses()
    assert results[0].action == "put"


def test_release_purge_removes_the_policy_and_tolerates_its_absence():
    client = iam()
    with Stubber(client) as stub:
        stub.add_response("get_role", role(ROLES[0]), {"RoleName": ROLES[0]})
        stub.add_response("delete_role_policy", {}, {"RoleName": ROLES[0], "PolicyName": "larkspur-kill-switch"})
        stub.add_response("get_role", role(ROLES[1]), {"RoleName": ROLES[1]})
        stub.add_client_error("delete_role_policy", service_error_code="NoSuchEntity", http_status_code=404,
                              expected_params={"RoleName": ROLES[1], "PolicyName": "larkspur-kill-switch"})
        results = identity.release(client, ROLES[:2], "w3-incident", purge=True)
        stub.assert_no_pending_responses()
    assert [r.action for r in results] == ["deleted", "absent"]


def test_a_dry_run_prints_the_plan_and_calls_nothing(monkeypatch, capsys):
    import boto3

    monkeypatch.setattr(boto3, "Session", lambda *a, **k: pytest.fail("a dry run made a client"))
    assert identity.main(["pull", "--manifest", str(CH05_W3), "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["roles"] == ROLES and printed["policy"] == "larkspur-kill-switch"
    assert [s["Sid"] for s in printed["document"]["Statement"]] == ["KillSwitchDenyAll", "KillSwitchRevokeIssued"]


def test_every_workflow_manifest_gives_role_names_iam_accepts():
    for path in sorted((LAB.parent.parent / "workflows").glob("*/manifest/*.yaml")):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name in identity.role_names(manifest):
            assert re.fullmatch(r"[\w+=,.@-]{1,64}", name), (path.name, name)
