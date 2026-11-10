"""The writer and the shared cluster state: a write runs only under an approval that covers it, applies once, and
changes the state W2's get_pod_status reads back; a scale past capacity fails its verification and rolls back; the
ServiceNow fake reads recent changes (with the planted ticket) and writes the change record once."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

W3 = Path(__file__).resolve().parents[1]
for folder in (W3 / "servers",):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import changes  # noqa: E402
import fakes  # noqa: E402
from cluster_state import ClusterState  # noqa: E402
from writer import ApprovalNotCovered, ApprovalUnchecked, Writer  # noqa: E402

from machine import State  # noqa: E402
from conftest import ENGINEER, USERS, approver_token, call, harness_over, reply, ScriptedModel  # noqa: E402

SERVICE = "claims-api"


class FakeApprovals:
    """Stands in for the approval client's check/applied: `covers` decides, `applied_ids` records marks."""

    def __init__(self, covers: bool = True, reason: str = "covered") -> None:
        self.covers, self.reason = covers, reason
        self.checks: list[tuple[str, dict]] = []
        self.applied_ids: list[str] = []

    def check(self, approval_id, *, tool, args, trace_id):
        self.checks.append((tool, args))
        return {"covers": self.covers, "reason": self.reason}

    def applied(self, approval_id):
        self.applied_ids.append(approval_id)
        return {"applied": True}


@pytest.fixture
def state_file(tmp_path):
    return tmp_path / "cluster.json"


def test_a_restart_heals_the_deployment_and_bumps_the_generation(state_file):
    writer = Writer(FakeApprovals(), state_file)
    before = ClusterState(state_file).current(SERVICE)
    assert before["ready"] == 2 and before["desired"] == 3 and before["generation"] == 1
    result = writer.restart_deployment({"service": SERVICE}, "APR-1", trace_id="run-1")
    assert result["applied"]["generation"] == 2 and result["applied"]["restartedAt"] is not None
    after = ClusterState(state_file).current(SERVICE)
    assert after["ready"] == 3 and all(p["phase"] == "Running" and p["restarts"] == 0 for p in after["pods"])
    assert writer.verify(None, {"name": "restart_deployment", "args": {"service": SERVICE}}, {})["ok"] is True


def test_the_write_is_seen_by_w2_get_pod_status(state_file, monkeypatch):
    monkeypatch.setenv("CLUSTER_STATE_FILE", str(state_file))
    import importlib
    importlib.reload(fakes)
    assert fakes.pod_status(SERVICE)["ready"] == 2, "deployed state before any write"
    Writer(FakeApprovals(), state_file).restart_deployment({"service": SERVICE}, "APR-1", trace_id="run-1")
    status = fakes.pod_status(SERVICE)
    assert status["ready"] == 3 and status["desired"] == 3, "W2's read sees the writer's change"
    monkeypatch.delenv("CLUSTER_STATE_FILE")
    importlib.reload(fakes)


def test_a_restart_of_a_scheduling_fault_does_not_heal(state_file):
    writer = Writer(FakeApprovals(), state_file)
    writer.restart_deployment({"service": "document-ocr"}, "APR-2", trace_id="run-2")
    verify = writer.verify(None, {"name": "restart_deployment", "args": {"service": "document-ocr"}}, {})
    assert verify["ok"] is False and verify["pending"] == 1, "document-ocr's Pending pod is a scheduling constraint"


def test_a_scale_within_capacity_passes_and_past_capacity_fails(state_file):
    writer = Writer(FakeApprovals(), state_file)
    up = writer.scale_deployment({"service": "billing-worker", "replicas": 6}, "APR-3", trace_id="run-3")
    assert up["applied"] == {"replicas": 6, "ready": 6, "capacity": 10}
    assert writer.verify(None, {"name": "scale_deployment", "args": {"service": "billing-worker"}}, {})["ok"] is True
    over = writer.scale_deployment({"service": "fraud-scoring", "replicas": 6}, "APR-4", trace_id="run-4")
    assert over["applied"]["ready"] == 4, "fraud-scoring's capacity is four"
    assert writer.verify(None, {"name": "scale_deployment", "args": {"service": "fraud-scoring"}}, {})["ok"] is False


def test_a_scale_outside_the_bounds_is_a_bad_argument(state_file):
    writer = Writer(FakeApprovals(), state_file)
    with pytest.raises(ValueError, match="between 1 and 8"):
        writer.scale_deployment({"service": SERVICE, "replicas": 20}, "APR-5", trace_id="run-5")
    with pytest.raises(ValueError):
        writer.scale_deployment({"service": SERVICE, "replicas": True}, "APR-6", trace_id="run-6")


def test_a_write_the_approval_does_not_cover_does_not_run(state_file):
    approvals = FakeApprovals(covers=False, reason="the approval is for another call")
    writer = Writer(approvals, state_file)
    with pytest.raises(ApprovalNotCovered, match="another call"):
        writer.restart_deployment({"service": SERVICE}, "APR-7", trace_id="run-7")
    assert approvals.applied_ids == [], "no apply mark and no change when the approval does not cover"
    assert ClusterState(state_file).current(SERVICE)["generation"] == 1


def test_a_write_whose_approval_cannot_be_checked_does_not_run(state_file):
    class Unreachable(FakeApprovals):
        def check(self, approval_id, *, tool, args, trace_id):
            raise ConnectionError("the approval service is down")

    approvals = Unreachable()
    writer = Writer(approvals, state_file)
    with pytest.raises(ApprovalUnchecked, match="could not be checked"):
        writer.restart_deployment({"service": SERVICE}, "APR-11", trace_id="run-11")
    assert approvals.applied_ids == [], "no apply mark when the service could not be asked"
    assert ClusterState(state_file).current(SERVICE)["generation"] == 1


def test_a_write_whose_apply_mark_fails_does_not_run(state_file):
    class NoMark(FakeApprovals):
        def applied(self, approval_id):
            raise ConnectionError("the approval service went away after the check")

    writer = Writer(NoMark(), state_file)
    with pytest.raises(ApprovalUnchecked, match="could not be marked applied"):
        writer.scale_deployment({"service": SERVICE, "replicas": 4}, "APR-12", trace_id="run-12")
    assert ClusterState(state_file).current(SERVICE)["desired"] == 3, "the mark comes before the write"


def test_a_restart_names_no_state_to_return_to_and_a_scale_names_its_count(state_file):
    writer = Writer(FakeApprovals(), state_file)
    restart = writer.restart_deployment({"service": SERVICE}, "APR-13", trace_id="run-13")
    assert restart["previous"] is None, "a restart has nothing a rollback could return to (W3-D8)"
    assert restart["replaced"]["generation"] == 1 and restart["applied"]["generation"] == 2
    scale = writer.scale_deployment({"service": SERVICE, "replicas": 5}, "APR-14", trace_id="run-14")
    assert scale["previous"]["replicas"] == 3


def test_the_writer_marks_the_approval_applied(state_file):
    approvals = FakeApprovals()
    Writer(approvals, state_file).restart_deployment({"service": SERVICE}, "APR-8", trace_id="run-8")
    assert approvals.applied_ids == ["APR-8"]


def test_the_rollback_scales_back_to_the_recorded_count(state_file):
    writer = Writer(FakeApprovals(), state_file)
    writer.scale_deployment({"service": "fraud-scoring", "replicas": 6}, "APR-9", trace_id="run-9")
    write = {"result": {"previous": {"replicas": 2}}}
    rolled = writer.rollback(None, {"name": "scale_deployment", "args": {"service": "fraud-scoring"}}, write, "APR-9")
    assert rolled["scaled_back_to"] == 2
    assert ClusterState(state_file).current("fraud-scoring")["desired"] == 2


def test_recent_changes_carries_the_planted_ticket():
    result = changes.recent_changes(SERVICE, minutes=changes.MAX_WINDOW_MINUTES)
    assert result["count"] == 2 and result["changes"][0]["number"] == "CHG0030052"
    planted = next(c for c in result["changes"] if c["description"] == fakes.PLANTED["ticket"])
    assert planted["type"] == "normal" and "larkspur-prod" in planted["description"]
    assert changes.recent_changes("policy-admin", minutes=1440)["count"] == 0
    with pytest.raises(changes.fakes.UnknownService):
        changes.recent_changes("no-such-service", minutes=60)
    with pytest.raises(ValueError):
        changes.recent_changes(SERVICE, minutes=changes.MAX_WINDOW_MINUTES + 1)


def test_the_change_record_is_written_once_with_servicenow_fields(tmp_path):
    store = tmp_path / "servicenow.json"
    record = changes.record_change(approval_id="APR-10", service=SERVICE, step="restart_deployment",
                                   args={"service": SERVICE}, trace_id="run-abcdef12", requester="sam",
                                   approver="tomasz", justification="runbook rb-pod-crashloop step 3",
                                   planned_start="2026-11-02T13:00:00Z", planned_end="2026-11-02T13:15:00Z",
                                   backout_plan="a restart has no backout; verification is the record", path=store)
    assert record["type"] == "emergency" and record["state"] == "Implement"
    for field in ("number", "short_description", "justification", "implementation_plan", "backout_plan",
                  "planned_start_date", "requested_by", "configuration_item", "approved_by"):
        assert record[field], field
    again = changes.record_change(approval_id="APR-10", service=SERVICE, step="restart_deployment",
                                  args={"service": SERVICE}, trace_id="run-abcdef12", requester="sam",
                                  approver="tomasz", justification="x", planned_start="x", planned_end="x",
                                  backout_plan="x", path=store)
    assert again["number"] == record["number"], "idempotent on the approval's number"
    assert len(json.loads(store.read_text(encoding="utf-8"))) == 1
    closed = changes.close_change("APR-10", close_code="Successful", close_notes="ready at 3 of 3", path=store)
    assert closed["state"] == "Closed" and closed["close_code"] == "Successful"


def test_the_harness_runs_the_real_writer_end_to_end(approval_http, store_path, parts, state_file):
    """The approval service, the writer, and the cluster state together: triage proposes a restart, a person
    approves, the writer runs it under the approval and heals the deployment, the verification passes."""
    url, client = approval_http
    parts["approvals"] = client
    writer = Writer(client, state_file)
    parts["writer"] = _WriterAdapter(writer, trace_holder := {})
    parts["verifier"] = writer
    look = reply(call("get_pod_status", {"service": SERVICE}, "c1"))
    restart = reply(call("restart_deployment", {"service": SERVICE}, "c2"), reasoning="runbook step 3")
    first = harness_over(store_path, ScriptedModel([look, restart]), parts, with_rollback=True)
    trace_holder["trace_id"] = "run-writer-1"
    run = first.start(f"{SERVICE} is paging", USERS[ENGINEER], trace_id="run-writer-1")
    approval_id = first.machine.payload("run-writer-1", State.AWAITING_APPROVAL)["approval_id"]
    import httpx
    httpx.post(f"{url}/requests/{approval_id}/decisions", json={"approved": True},
               headers={"X-Larkspur-Actor": approver_token("incident.responder")}).raise_for_status()
    run = first.resume("run-writer-1")
    assert run.state is State.DONE
    assert client.get(approval_id)["applied_at"] is not None, "the writer marked the approval applied"
    assert ClusterState(state_file).current(SERVICE)["ready"] == 3
    done = first.machine.payload("run-writer-1", State.DONE)
    assert done["verification"]["ok"] is True and done["step"] == "restart_deployment"


def _approved_run(approval_http, store_path, parts, state_file, proposal, trace_id):
    """The real approval service, writer, and cluster state under the harness: propose, approve, resume."""
    url, client = approval_http
    parts["approvals"] = client
    writer = Writer(client, state_file)
    parts["writer"] = _WriterAdapter(writer, {"trace_id": trace_id})
    parts["verifier"] = writer
    service = proposal["tool_calls"][0]["args"]["service"]
    look = reply(call("get_pod_status", {"service": service}, "c1"))
    harness = harness_over(store_path, ScriptedModel([look, proposal]), parts, with_rollback=True)
    harness.start(f"{service} is paging", USERS[ENGINEER], trace_id=trace_id)
    approval_id = harness.machine.payload(trace_id, State.AWAITING_APPROVAL)["approval_id"]
    import httpx
    httpx.post(f"{url}/requests/{approval_id}/decisions", json={"approved": True},
               headers={"X-Larkspur-Actor": approver_token("incident.responder")}).raise_for_status()
    return harness, harness.resume(trace_id), approval_id


def test_a_restart_that_does_not_heal_ends_done_with_the_real_writer(approval_http, store_path, parts, state_file):
    """document-ocr's Pending pod is a scheduling fault a restart cannot heal: the run ends done with the failed
    verification as its record, and no rollback is reserved or run (W3-D8)."""
    restart = reply(call("restart_deployment", {"service": "document-ocr"}, "c2"), reasoning="runbook step 3")
    harness, run, approval_id = _approved_run(approval_http, store_path, parts, state_file, restart, "run-writer-2")
    assert run.state is State.DONE
    done = harness.machine.payload("run-writer-2", State.DONE)
    assert done["verification"]["ok"] is False and done["rollback"] is None and done["step"] == "restart_deployment"
    from store import Store
    assert Store(store_path).applied(f"{approval_id}:rollback") is None, "no rollback was reserved"
    assert ClusterState(state_file).current("document-ocr")["generation"] == 2, "the restart ran once"


def test_a_scale_past_capacity_is_rolled_back_with_the_real_writer(approval_http, store_path, parts, state_file):
    """fraud-scoring can run four pods: a scale to six fails its verification and returns to the recorded count."""
    before = ClusterState(state_file).current("fraud-scoring")["desired"]
    scale = reply(call("scale_deployment", {"service": "fraud-scoring", "replicas": 6}, "c2"), reasoning="saturation")
    harness, run, approval_id = _approved_run(approval_http, store_path, parts, state_file, scale, "run-writer-3")
    assert run.state is State.ROLLED_BACK
    rolled = harness.machine.payload("run-writer-3", State.ROLLED_BACK)
    assert rolled["verification"]["ok"] is False and rolled["rollback"]["result"]["scaled_back_to"] == before
    assert ClusterState(state_file).current("fraud-scoring")["desired"] == before


class _WriterAdapter:
    """Turns the Writer's (args, approval_id, trace_id) tools into triage's (args, approval_id) WriteTool."""

    def __init__(self, writer, trace_holder):
        self.writer, self.trace_holder = writer, trace_holder

    def tools(self):
        def restart(args, approval_id):
            return self.writer.restart_deployment(args, approval_id, trace_id=self.trace_holder["trace_id"])

        def scale(args, approval_id):
            return self.writer.scale_deployment(args, approval_id, trace_id=self.trace_holder["trace_id"])

        return {"restart_deployment": restart, "scale_deployment": scale}
