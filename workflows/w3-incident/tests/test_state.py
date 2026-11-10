"""The store and the machine: a transition is on disk before the step runs, the edges hold, a new process reads the
run back, and a side effect behind a key runs once."""

from __future__ import annotations

import pytest
from machine import EDGES, RESUMABLE, TERMINAL, IllegalTransition, Machine, State
from store import AlreadyApplied, Store

from conftest import ENGINEER


def test_a_transition_is_written_before_the_step_runs(store_path):
    machine = Machine(Store(store_path))
    run = machine.start("t1", requester=ENGINEER, question="claims-api is paging", alert="HighErrorRate")
    assert run.state is State.TRIGGERED
    run = machine.advance(run, State.TRIAGING)
    # Another connection sees the new state at once: the write is committed, not buffered.
    other = Store(store_path)
    assert other.run("t1").state == "triaging"
    history = other.transitions("t1")
    assert [t.to_state for t in history] == ["triggered", "triaging"]
    assert history[0].payload == {"alert": "HighErrorRate"} and history[0].from_state is None
    assert history[1].from_state == "triggered" and history[1].seq == 2


def test_an_edge_the_machine_lacks_is_refused(store_path):
    machine = Machine(Store(store_path))
    run = machine.start("t2", requester=ENGINEER, question="q")
    with pytest.raises(IllegalTransition):
        machine.advance(run, State.DONE)
    assert machine.load("t2").state is State.TRIGGERED, "a refused transition writes nothing"


def test_a_stale_run_object_cannot_move_the_row(store_path):
    """Two harnesses holding the same run: the second one's transition is refused by the store's state check."""
    machine = Machine(Store(store_path))
    run = machine.start("t3", requester=ENGINEER, question="q")
    stale = run
    machine.advance(run, State.TRIAGING)
    with pytest.raises(ValueError):
        machine.advance(stale, State.TRIAGING)


def test_every_state_has_a_way_out_or_is_terminal():
    for state in State:
        assert state in TERMINAL or EDGES[state], state
    for state, nexts in EDGES.items():
        assert state not in TERMINAL
        assert nexts <= set(State)
    assert TERMINAL.isdisjoint(RESUMABLE)
    assert TERMINAL | RESUMABLE == set(State)


def test_a_new_process_reads_the_run_back(store_path):
    first = Machine(Store(store_path))
    run = first.start("t4", requester=ENGINEER, question="q")
    run = first.advance(run, State.TRIAGING)
    run = first.advance(run, State.PROPOSING, proposal={"name": "restart_deployment", "args": {"service": "claims-api"}},
                        service="claims-api")
    first.store.close()
    second = Machine(Store(store_path))
    loaded = second.load("t4")
    assert loaded.state is State.PROPOSING and loaded.service == "claims-api"
    assert second.payload("t4", State.PROPOSING)["proposal"]["name"] == "restart_deployment"
    assert second.payload("t4", State.DONE) is None
    assert [r.trace_id for r in second.resumable()] == ["t4"]


def test_a_side_effect_behind_a_key_runs_once(store_path):
    store = Store(store_path)
    Machine(store).start("t5", requester=ENGINEER, question="q")
    store.reserve("apr-001:restart_deployment", "t5")
    with pytest.raises(AlreadyApplied) as started:
        store.reserve("apr-001:restart_deployment", "t5")
    assert started.value.finished is False and started.value.result is None
    assert store.applied("apr-001:restart_deployment") == (False, None)
    store.complete("apr-001:restart_deployment", {"applied": {"restartedAt": "now"}})
    with pytest.raises(AlreadyApplied) as finished:
        store.reserve("apr-001:restart_deployment", "t5")
    assert finished.value.finished is True and finished.value.result == {"applied": {"restartedAt": "now"}}
    assert store.applied("apr-002:restart_deployment") is None, "another approval is another key"


def test_resumable_lists_the_runs_a_restarted_harness_picks_up(store_path):
    machine = Machine(Store(store_path))
    waiting = machine.start("w", requester=ENGINEER, question="q")
    waiting = machine.advance(waiting, State.TRIAGING)
    waiting = machine.advance(waiting, State.PROPOSING, proposal={"name": "scale_deployment", "args": {}})
    machine.advance(waiting, State.AWAITING_APPROVAL, approval_id="apr-001", proposal={})
    done = machine.start("d", requester=ENGINEER, question="q")
    done = machine.advance(done, State.TRIAGING)
    machine.advance(done, State.DONE, answer="healthy")
    assert [r.trace_id for r in machine.resumable()] == ["w"]
    assert machine.load("d").terminal
