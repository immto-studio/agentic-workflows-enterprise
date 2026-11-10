"""The harness end to end over fakes, and the test the plan names (W3-D2): kill the harness between any two
states, start it again, and the run resumes from the store with the same approval, and nothing executes twice."""

from __future__ import annotations

import pytest
from machine import Machine, State
from store import Store

from conftest import APPROVER, ENGINEER, KillSwitch, ScriptedModel, answer, call, harness_over, reply, states

SERVICE = "claims-api"
RESTART = reply(call("restart_deployment", {"service": SERVICE}, "c2"), reasoning="runbook step 3: restart")
LOOK = reply(call("get_pod_status", {"service": SERVICE}, "c1"), reasoning="look first")


def test_a_triage_that_answers_without_a_step_ends_done(store_path, parts):
    harness = harness_over(store_path, ScriptedModel([LOOK, answer("healthy, nothing to do")]), parts)
    run = harness.start(f"is {SERVICE} healthy", ENGINEER, trace_id="t-answer")
    assert run.state is State.DONE and run.terminal
    assert harness.machine.payload("t-answer", State.DONE) == {"answer": "healthy, nothing to do", "reads": 1, "step": None}
    assert parts["approvals"].requests == {} and parts["writer"].calls == []


def test_a_run_waits_in_the_store_and_a_new_harness_executes_it(store_path, parts):
    first = harness_over(store_path, ScriptedModel([LOOK, RESTART]), parts)
    run = first.start(f"{SERVICE} is paging", ENGINEER, trace_id="t1")
    assert run.state is State.AWAITING_APPROVAL and run.service == SERVICE
    approval_id = parts["approvals"].last()
    assert parts["approvals"].requests[approval_id][1]["name"] == "restart_deployment"
    assert parts["writer"].calls == [], "nothing is written while the approval is pending"
    first.machine.store.close()  # the process is gone

    # A new process; the approval service is outside it and still holds the request.
    second = harness_over(store_path, ScriptedModel([]), parts)
    assert second.resume("t1").state is State.AWAITING_APPROVAL, "no decision yet: still waiting"
    parts["approvals"].decide(approval_id, approved=True)
    run = second.resume("t1")
    assert run.state is State.DONE
    assert parts["writer"].calls == [("restart_deployment", {"service": SERVICE}, approval_id)]
    assert states(second, "t1") == ["triggered", "triaging", "proposing", "awaiting_approval", "executing",
                                    "verifying", "done"]
    verifying = second.machine.payload("t1", State.VERIFYING)
    assert verifying["write"]["status"] == "applied" and verifying["write"]["repeat"] is False
    assert second.machine.payload("t1", State.EXECUTING)["by"] == APPROVER
    assert second.resume("t1").state is State.DONE and len(parts["writer"].calls) == 1, "a terminal run stays put"


def test_a_harness_that_dies_after_the_write_does_not_write_twice(store_path, parts):
    first = harness_over(store_path, ScriptedModel([LOOK, RESTART]), parts)
    first.start(f"{SERVICE} is paging", ENGINEER, trace_id="t2")
    approval_id = parts["approvals"].last()
    parts["approvals"].decide(approval_id, approved=True)
    parts["writer"].kill_after.add("restart_deployment")
    with pytest.raises(KillSwitch):
        first.resume("t2")  # the restart was sent; the process died before recording the result
    assert parts["writer"].calls == [("restart_deployment", {"service": SERVICE}, approval_id)]
    assert Store(store_path).applied(f"{approval_id}:restart_deployment") == (False, None)

    parts["writer"].kill_after.clear()
    second = harness_over(store_path, ScriptedModel([]), parts)
    assert second.machine.load("t2").state is State.EXECUTING
    run = second.resume("t2")
    assert run.state is State.DONE
    assert len(parts["writer"].calls) == 1, "the resumed harness verified instead of restarting again"
    write = second.machine.payload("t2", State.VERIFYING)["write"]
    assert write == {"status": "started", "result": None, "repeat": True}
    assert len(parts["verifier"].calls) == 1


def test_a_harness_that_dies_after_recording_the_write_verifies_without_acting(store_path, parts):
    first = harness_over(store_path, ScriptedModel([LOOK, RESTART]), parts)
    first.start(f"{SERVICE} is paging", ENGINEER, trace_id="t3")
    approval_id = parts["approvals"].last()
    parts["approvals"].decide(approval_id, approved=True)
    # The same moment, by hand: the transition to executing and the completed write are on disk, the
    # transition to verifying is not.
    machine = first.machine
    run = machine.advance(machine.load("t3"), State.EXECUTING, approval_id=approval_id, by=APPROVER)
    machine.store.reserve(f"{approval_id}:restart_deployment", "t3")
    machine.store.complete(f"{approval_id}:restart_deployment", {"previous": None, "applied": {"restartedAt": "x"}})
    second = harness_over(store_path, ScriptedModel([]), parts)
    run = second.resume("t3")
    assert run.state is State.DONE and parts["writer"].calls == []
    write = second.machine.payload("t3", State.VERIFYING)["write"]
    assert write["status"] == "applied" and write["repeat"] is True and write["result"]["applied"] == {"restartedAt": "x"}


def test_a_harness_that_dies_while_triaging_triages_again(store_path, parts):
    machine = Machine(Store(store_path))
    run = machine.start("t4", requester=ENGINEER, question=f"{SERVICE} is paging")
    machine.advance(run, State.TRIAGING)  # the reads began; the process died before any proposal
    harness = harness_over(store_path, ScriptedModel([LOOK, RESTART]), parts)
    run = harness.resume("t4")
    assert run.state is State.AWAITING_APPROVAL
    assert states(harness, "t4") == ["triggered", "triaging", "proposing", "awaiting_approval"]


def test_a_harness_that_dies_after_proposing_files_the_request_once(store_path, parts):
    machine = Machine(Store(store_path))
    run = machine.start("t5", requester=ENGINEER, question="q")
    run = machine.advance(run, State.TRIAGING)
    machine.advance(run, State.PROPOSING, proposal=call("restart_deployment", {"service": SERVICE}), service=SERVICE)
    harness = harness_over(store_path, ScriptedModel([]), parts)
    run = harness.resume("t5")
    assert run.state is State.AWAITING_APPROVAL
    assert len(parts["approvals"].requests) == 1


def test_an_expired_approval_drops_the_run(store_path, parts):
    harness = harness_over(store_path, ScriptedModel([LOOK, RESTART]), parts)
    harness.start(f"{SERVICE} is paging", ENGINEER, trace_id="t6")
    parts["approvals"].expired_ids.add(parts["approvals"].last())
    run = harness.resume("t6")
    assert run.state is State.DROPPED and parts["writer"].calls == []
    assert "expired" in harness.machine.payload("t6", State.DROPPED)["reason"]
    parts["approvals"].decide(parts["approvals"].last(), approved=True)  # a late yes
    assert harness.resume("t6").state is State.DROPPED and parts["writer"].calls == []


def test_a_declined_approval_refuses_the_run(store_path, parts):
    harness = harness_over(store_path, ScriptedModel([LOOK, RESTART]), parts)
    harness.start(f"{SERVICE} is paging", ENGINEER, trace_id="t7")
    parts["approvals"].decide(parts["approvals"].last(), approved=False, reason="not during the batch window")
    run = harness.resume("t7")
    assert run.state is State.REFUSED and parts["writer"].calls == []
    assert harness.machine.payload("t7", State.REFUSED)["reason"] == "declined: not during the batch window"


def test_a_failed_verification_rolls_a_scale_back_once(store_path, parts):
    scale = reply(call("scale_deployment", {"service": SERVICE, "replicas": 6}, "c2"), reasoning="saturation")
    parts["verifier"].ok = False
    harness = harness_over(store_path, ScriptedModel([LOOK, scale]), parts)
    harness.start(f"{SERVICE} is saturated", ENGINEER, trace_id="t8")
    approval_id = parts["approvals"].last()
    parts["approvals"].decide(approval_id, approved=True)
    run = harness.resume("t8")
    assert run.state is State.ROLLED_BACK
    assert parts["writer"].calls == [("scale_deployment", {"service": SERVICE, "replicas": 6}, approval_id)]
    assert parts["verifier"].rollbacks[0][2] == approval_id, "the rollback runs under the same approval"
    rolled = harness.machine.payload("t8", State.ROLLED_BACK)
    assert rolled["rollback"]["result"] == {"replicas": 3} and rolled["verification"]["ok"] is False
    assert Store(store_path).applied(f"{approval_id}:rollback")[0] is True
    # Resumed again, by another process: terminal, nothing moves.
    again = harness_over(store_path, ScriptedModel([]), parts)
    assert again.resume("t8").state is State.ROLLED_BACK and len(parts["verifier"].rollbacks) == 1


def test_a_failed_verification_of_a_restart_is_its_record(store_path, parts):
    parts["verifier"].ok = False
    harness = harness_over(store_path, ScriptedModel([LOOK, RESTART]), parts)
    harness.start(f"{SERVICE} is paging", ENGINEER, trace_id="t9")
    parts["approvals"].decide(parts["approvals"].last(), approved=True)
    run = harness.resume("t9")
    assert run.state is State.DONE
    done = harness.machine.payload("t9", State.DONE)
    assert done["verification"]["ok"] is False and done["rollback"] is None and done["step"] == "restart_deployment"
    assert parts["verifier"].rollbacks == []


def test_a_write_the_tool_refuses_is_recorded_as_failed_and_never_retried(store_path, parts):
    """A write tool that could not check its approval answers with an error and does not act (over MCP the
    harness sees the tool's error as its result). The harness records the write as failed, verifies, ends the
    run with that record, and a resumed harness does not call the tool again."""
    calls = []

    def refuses(args, approval_id):
        calls.append((args, approval_id))
        return {"error": "the approval service could not be asked, so the step was not taken"}

    parts["verifier"].ok = False
    harness = harness_over(store_path, ScriptedModel([LOOK, RESTART]), parts)
    harness.services.writes["restart_deployment"] = refuses
    harness.start(f"{SERVICE} is paging", ENGINEER, trace_id="t10")
    approval_id = parts["approvals"].last()
    parts["approvals"].decide(approval_id, approved=True)
    run = harness.resume("t10")
    assert run.state is State.DONE and len(calls) == 1
    write = harness.machine.payload("t10", State.VERIFYING)["write"]
    assert write["status"] == "failed" and "step was not taken" in write["result"]["error"]
    done = harness.machine.payload("t10", State.DONE)
    assert done["verification"]["ok"] is False and done["rollback"] is None
    assert parts["verifier"].rollbacks == [], "a write that did not act has nothing to roll back"
    again = harness_over(store_path, ScriptedModel([]), parts)
    again.services.writes["restart_deployment"] = refuses
    assert again.resume("t10").state is State.DONE and len(calls) == 1


def test_a_refused_read_during_triage_refuses_the_run(store_path, parts):
    parts["reads"].errors["get_pod_status"] = "Error executing tool get_pod_status: fraud-scoring is not among the ones you can ask about."
    harness = harness_over(store_path, ScriptedModel([reply(call("get_pod_status", {"service": "fraud-scoring"}))]), parts)
    run = harness.start("what is wrong with fraud-scoring", ENGINEER, trace_id="t10")
    assert run.state is State.REFUSED
    assert harness.machine.payload("t10", State.REFUSED)["reason"] == "a server refused a read"


def test_resume_all_picks_up_every_waiting_run(store_path, parts):
    harness = harness_over(store_path, ScriptedModel([LOOK, RESTART, LOOK, RESTART]), parts)
    harness.start("a", ENGINEER, trace_id="a")
    harness.start("b", ENGINEER, trace_id="b")
    for approval_id in list(parts["approvals"].requests):
        parts["approvals"].decide(approval_id, approved=True)
    fresh = harness_over(store_path, ScriptedModel([]), parts)
    assert [r.state for r in fresh.resume_all()] == [State.DONE, State.DONE]
    assert len(parts["writer"].calls) == 2 and fresh.resume_all() == []
