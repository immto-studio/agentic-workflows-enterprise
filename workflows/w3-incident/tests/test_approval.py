"""The approval service: lst-04-03's rules made durable, the approvers from the service map, the timeout and the
late yes, the check a write tool makes, the apply mark set once, the card the bot would post, and the HTTP layer the
harness and the write tools call."""

from __future__ import annotations

import json

import httpx
import pytest
from machine import State
from approval_service import DEFAULT_TTL_SECONDS, Refused, canonical_args, iso, parse_iso
from datetime import timedelta

from conftest import (ENGINEER, SERVICE_KEY, USERS, ScriptedModel, approver_token, call, harness_over,
                      membership_table, reply)

SERVICE = "claims-api"
RESTART = {"name": "restart_deployment", "args": {"service": SERVICE}}


def file_request(service, tool=RESTART, trace_id="run-1", requester=ENGINEER, **kw):
    return service.request(workflow="w3-incident", trace_id=trace_id, tool=tool["name"], args=tool["args"],
                           service=tool["args"]["service"], requester_oid=USERS[requester],
                           requester_upn=f"{requester}@larkspur.example", **kw)


def test_a_request_takes_its_approvers_from_the_service_map(approval_service, cards_dir, clock):
    record = file_request(approval_service)
    assert record["status"] == "pending" and record["approvers"] == "lm-sec-incident-response" and record["required"] == 1
    assert parse_iso(record["expires_at"]) == clock.now + timedelta(seconds=900), "fifteen minutes by default (lst-04-03)"
    assert record["args"] == {"service": SERVICE} and record["trace_id"] == "run-1"
    pci = file_request(approval_service, {"name": "scale_deployment", "args": {"service": "billing-worker", "replicas": 4}})
    assert (pci["approvers"], pci["required"]) == ("lm-pci-cde-operators", 1)
    portal = file_request(approval_service, {"name": "restart_deployment", "args": {"service": "customer-portal"}})
    assert (portal["approvers"], portal["required"]) == ("lm-eng-all", 2)
    card = json.loads((cards_dir / f"{record['approval_id']}-request.json").read_text(encoding="utf-8"))
    assert card["version"] == "1.5" and card["refresh"]["userIds"] == ["29:lm-sec-incident-response-member"]
    assert [a["type"] for a in card["actions"]] == ["Action.Execute", "Action.Execute"]
    assert all(a["fallback"]["type"] == "Action.Submit" for a in card["actions"])
    assert card["actions"][0]["data"] == {"approval_id": record["approval_id"], "approved": True}


def test_the_requester_cannot_approve_their_own_call(approval_service):
    record = file_request(approval_service, requester="incident.responder")  # a responder asked; responders approve
    with pytest.raises(Refused, match="requester cannot approve"):
        approval_service.decide(record["approval_id"], approver_token("incident.responder"), approved=True)
    after = approval_service.get(record["approval_id"])
    assert after["status"] == "pending"
    assert after["decisions"][-1]["accepted"] is False and after["decisions"][-1]["oid"] == USERS["incident.responder"]


def test_only_the_approvers_group_may_decide(approval_service):
    record = file_request(approval_service)
    with pytest.raises(Refused, match="not in the approvers group lm-sec-incident-response"):
        approval_service.decide(record["approval_id"], approver_token("ea.lead"), approved=True)
    assert approval_service.get(record["approval_id"])["status"] == "pending"


def test_an_approval_covers_exactly_the_call_in_the_run_and_applies_once(approval_service, cards_dir, clock):
    record = file_request(approval_service)
    approval_id = record["approval_id"]
    decided = approval_service.decide(approval_id, approver_token("incident.responder"), approved=True, reason="runbook step 3")
    assert decided["status"] == "approved" and decided["approved_by"] == [USERS["incident.responder"]]
    assert approval_service.check(approval_id, tool="restart_deployment", args={"service": SERVICE}, trace_id="run-1") == {
        "covers": True, "reason": "covered", "approved_by": [USERS["incident.responder"]]}
    other_args = approval_service.check(approval_id, tool="restart_deployment", args={"service": "policy-admin"}, trace_id="run-1")
    assert (other_args["covers"], other_args["reason"]) == (False, "the approval is for another call")
    other_tool = approval_service.check(approval_id, tool="scale_deployment", args={"service": SERVICE}, trace_id="run-1")
    assert other_tool["reason"] == "the approval is for another call"
    other_run = approval_service.check(approval_id, tool="restart_deployment", args={"service": SERVICE}, trace_id="run-2")
    assert other_run["reason"] == "the approval is for another run"
    applied = approval_service.mark_applied(approval_id)
    assert applied["applied_at"] == iso(clock.now)
    again = approval_service.check(approval_id, tool="restart_deployment", args={"service": SERVICE}, trace_id="run-1")
    assert (again["covers"], again["reason"]) == (False, "already applied")
    with pytest.raises(Refused, match="already applied"):
        approval_service.mark_applied(approval_id)
    card = json.loads((cards_dir / f"{approval_id}-decided.json").read_text(encoding="utf-8"))
    assert card["actions"] == [] and any(f["value"] == "Approved" for f in card["body"][1]["facts"])
    assert any(f["value"] == "incident.responder@larkspur.example" for f in card["body"][1]["facts"])


def test_a_second_decision_is_refused_and_recorded(approval_service):
    approval_id = file_request(approval_service)["approval_id"]
    approval_service.decide(approval_id, approver_token("incident.responder"), approved=True)
    with pytest.raises(Refused, match="already decided"):
        approval_service.decide(approval_id, approver_token("incident.responder"), approved=False)
    record = approval_service.get(approval_id)
    assert record["status"] == "approved"
    assert [d["accepted"] for d in record["decisions"]] == [True, False]


def test_a_late_yes_is_refused_as_expired(approval_service, clock):
    approval_id = file_request(approval_service)["approval_id"]
    clock.advance(DEFAULT_TTL_SECONDS)
    assert approval_service.get(approval_id)["status"] == "expired"
    with pytest.raises(Refused, match="the approval has expired"):
        approval_service.decide(approval_id, approver_token("incident.responder"), approved=True)
    assert approval_service.get(approval_id)["decisions"][-1]["reason"] == "the approval has expired"
    check = approval_service.check(approval_id, tool="restart_deployment", args={"service": SERVICE}, trace_id="run-1")
    assert check["covers"] is False and check["reason"] == "the approval has expired"


def test_an_approved_request_expires_for_applying_too(approval_service, clock):
    approval_id = file_request(approval_service)["approval_id"]
    approval_service.decide(approval_id, approver_token("incident.responder"), approved=True)
    clock.advance(DEFAULT_TTL_SECONDS)
    check = approval_service.check(approval_id, tool="restart_deployment", args={"service": SERVICE}, trace_id="run-1")
    assert check == {"covers": False, "reason": "the approval has expired"}, "the yes covers the call for fifteen minutes"


def test_a_two_approval_service_needs_two_people(approval_service):
    portal = {"name": "restart_deployment", "args": {"service": "customer-portal"}}
    approval_id = file_request(approval_service, portal)["approval_id"]
    first = approval_service.decide(approval_id, approver_token("ea.lead"), approved=True)
    assert first["status"] == "pending" and len(first["approved_by"]) == 1
    with pytest.raises(Refused, match="already approved by this person"):
        approval_service.decide(approval_id, approver_token("ea.lead"), approved=True)
    second = approval_service.decide(approval_id, approver_token("many.groups"), approved=True)
    assert second["status"] == "approved" and set(second["approved_by"]) == {USERS["ea.lead"], USERS["many.groups"]}


def test_one_decline_declines_whatever_the_count(approval_service):
    portal = {"name": "restart_deployment", "args": {"service": "customer-portal"}}
    approval_id = file_request(approval_service, portal)["approval_id"]
    declined = approval_service.decide(approval_id, approver_token("ea.lead"), approved=False, reason="change freeze")
    assert declined["status"] == "declined"
    with pytest.raises(Refused, match="already decided"):
        approval_service.decide(approval_id, approver_token("many.groups"), approved=True)


def test_a_token_for_another_app_is_refused(approval_service):
    approval_id = file_request(approval_service)["approval_id"]
    w2_shaped = approver_token("incident.responder", scope="Ops.Read", audience="3f1c9a52-6d4e-5b7a-9c0d-1e2f3a4b5c6d")
    with pytest.raises(Refused, match="token refused"):
        approval_service.decide(approval_id, w2_shaped, approved=True)
    record = approval_service.get(approval_id)
    assert record["decisions"][-1]["oid"] is None and record["decisions"][-1]["accepted"] is False


def test_a_stale_table_lets_only_broad_groups_approve(tmp_path, clock, approval_service):
    """W1-D27 applied to approvals: a table older than a day and a half grants the broad groups only, so a narrow
    approvers group cannot decide until a fresh table arrives, and a broad one still can."""
    stale = membership_table(age=timedelta(hours=40))
    approval_service.table = lambda: stale
    narrow = file_request(approval_service)["approval_id"]
    with pytest.raises(Refused, match="not in the approvers group"):
        approval_service.decide(narrow, approver_token("incident.responder"), approved=True)
    broad = file_request(approval_service, {"name": "restart_deployment", "args": {"service": "customer-portal"}})["approval_id"]
    assert approval_service.decide(broad, approver_token("ea.lead"), approved=True)["status"] == "pending"


def test_the_http_layer_end_to_end(approval_http):
    url, client = approval_http
    approval_id = client.request("run-9", call("restart_deployment", {"service": SERVICE}), USERS[ENGINEER])
    assert approval_id.startswith("APR-") and client.decision(approval_id) is None and client.expired(approval_id) is False
    # The bot posts the person's decision with the person's token; no key.
    refused = httpx.post(f"{url}/requests/{approval_id}/decisions", json={"approved": True})
    assert refused.status_code == 403 and "no X-Larkspur-Actor" in refused.json()["error"]
    own = httpx.post(f"{url}/requests/{approval_id}/decisions", json={"approved": True},
                     headers={"X-Larkspur-Actor": approver_token(ENGINEER)})
    assert own.status_code == 403 and "requester" in own.json()["error"]
    yes = httpx.post(f"{url}/requests/{approval_id}/decisions", json={"approved": True, "reason": "step 3"},
                     headers={"X-Larkspur-Actor": f"Bearer {approver_token('incident.responder')}"})
    assert yes.status_code == 200 and yes.json()["status"] == "approved"
    assert client.decision(approval_id) == {"approved": True, "by": USERS["incident.responder"], "reason": ""}
    check = client.check(approval_id, tool="restart_deployment", args={"service": SERVICE}, trace_id="run-9")
    assert check["covers"] is True
    client.applied(approval_id)
    with pytest.raises(RuntimeError, match="already applied"):
        client.applied(approval_id)
    assert httpx.get(f"{url}/requests/{approval_id}").status_code == 401, "the record needs the service's key"
    assert httpx.post(f"{url}/requests", json={}).status_code == 401
    assert httpx.get(f"{url}/requests/APR-nothing", headers={"Authorization": f"Bearer {SERVICE_KEY}"}).status_code == 404


def test_the_harness_waits_on_the_real_service_and_resumes_on_its_decision(approval_http, store_path, parts):
    url, client = approval_http
    parts["approvals"] = client
    look = reply(call("get_pod_status", {"service": SERVICE}, "c1"))
    restart = reply(call("restart_deployment", {"service": SERVICE}, "c2"), reasoning="runbook step 3")
    first = harness_over(store_path, ScriptedModel([look, restart]), parts)
    run = first.start(f"{SERVICE} is paging", USERS[ENGINEER], trace_id="run-h1")
    assert run.state is State.AWAITING_APPROVAL
    approval_id = first.machine.payload("run-h1", State.AWAITING_APPROVAL)["approval_id"]
    assert client.get(approval_id)["trace_id"] == "run-h1" and client.get(approval_id)["requester_oid"] == USERS[ENGINEER]
    second = harness_over(store_path, ScriptedModel([]), parts)
    assert second.resume("run-h1").state is State.AWAITING_APPROVAL
    httpx.post(f"{url}/requests/{approval_id}/decisions", json={"approved": True},
               headers={"X-Larkspur-Actor": approver_token("incident.responder")}).raise_for_status()
    run = second.resume("run-h1")
    assert run.state is State.DONE
    assert parts["writer"].calls == [("restart_deployment", {"service": SERVICE}, approval_id)]
    assert second.machine.payload("run-h1", State.EXECUTING)["by"] == USERS["incident.responder"]
    assert canonical_args(client.get(approval_id)["args"]) == canonical_args({"service": SERVICE})
