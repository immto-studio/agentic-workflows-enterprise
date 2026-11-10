"""W3's state machine: the states a run passes through, the edges between them, and the rule that a
transition is written to the store before the step it names runs.

Chapter 12, W3-D2. A run is triggered by an alert or an engineer's request, triages with reads,
proposes one runbook step, waits for a person's approval, executes the step, verifies it, and ends
in one of four terminal states: done, rolled back, dropped (the approval timed out), or refused
(the step was outside the runbook or the manifest, the approver said no, or a read was refused).
The harness that drives the machine holds no state a restart loses: `Machine.load` rebuilds a run
from the store, and `Machine.resumable` lists the runs a restarted harness has to pick up.

The write-before-act rule, in one place (`advance`): the store records the new state and its
payload, and only then does the caller do what the state says. If the process dies in between, a
resumed harness finds the run in the new state with the payload that explains it, and continues
from there; nothing before the transition is repeated, because the store says it happened.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from store import RunRow, Store, Transition


class State(str, Enum):
    TRIGGERED = "triggered"
    TRIAGING = "triaging"
    PROPOSING = "proposing"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    DONE = "done"
    ROLLED_BACK = "rolled_back"
    DROPPED = "dropped"
    REFUSED = "refused"


TERMINAL = frozenset({State.DONE, State.ROLLED_BACK, State.DROPPED, State.REFUSED})

# The edges. A run that ends without a step (the triage answered the question, or found no runbook
# step to propose) goes from triaging to done; a declined approval and a step outside the runbook or
# the manifest go to refused; an approval that expired goes to dropped.
EDGES: dict[State, frozenset[State]] = {
    State.TRIGGERED: frozenset({State.TRIAGING, State.REFUSED}),
    State.TRIAGING: frozenset(
        {State.PROPOSING, State.DONE, State.REFUSED}),
    State.PROPOSING: frozenset({State.AWAITING_APPROVAL, State.REFUSED}),
    State.AWAITING_APPROVAL: frozenset(
        {State.EXECUTING, State.DROPPED, State.REFUSED}),
    State.EXECUTING: frozenset({State.VERIFYING}),
    State.VERIFYING: frozenset({State.DONE, State.ROLLED_BACK}),
}

# The states a restarted harness picks up. A run in triaging or proposing is restarted from the
# trigger (its reads are cheap and idempotent); a run waiting for approval waits in the store; a
# run in executing or verifying continues from the store's apply-once records.
RESUMABLE = frozenset({State.TRIGGERED, State.TRIAGING, State.PROPOSING, State.AWAITING_APPROVAL,
                       State.EXECUTING, State.VERIFYING})


class IllegalTransition(Exception):
    pass


@dataclass(frozen=True)
class Run:
    trace_id: str
    workflow: str
    requester: str
    question: str
    state: State
    service: str | None = None

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL


class Machine:
    """The machine over a store. One instance per harness process; any number of runs."""

    def __init__(self, store: Store, workflow: str = "w3-incident") -> None:
        self.store = store
        self.workflow = workflow

    def start(self, trace_id: str, *, requester: str, question: str, service: str | None = None,
              **payload: Any) -> Run:
        """A new run in `triggered`, recorded before anything is read."""
        self.store.create_run(trace_id, workflow=self.workflow, requester=requester, question=question,
                              state=State.TRIGGERED.value, service=service, payload=payload)
        return Run(trace_id, self.workflow, requester, question, State.TRIGGERED, service)

    def advance(self, run: Run, to: State, **payload: Any) -> Run:
        """Record the transition, then act: the caller does what the new
        state says after this returns."""
        if to not in EDGES.get(run.state, frozenset()):
            raise IllegalTransition(
                f"{run.trace_id}: {run.state.value} -> {to.value}")
        service = payload.pop("service", None)
        self.store.record_transition(run.trace_id, run.state.value,
                                     to.value, payload, service=service)
        return replace(run, state=to, service=service or run.service)

    def load(self, trace_id: str) -> Run:
        row = self.store.run(trace_id)
        if row is None:
            raise KeyError(trace_id)
        return self._run(row)

    def history(self, trace_id: str) -> list[Transition]:
        return self.store.transitions(trace_id)

    def payload(self, trace_id: str, state: State) -> dict[str, Any] | None:
        """The payload of the last transition into `state`, or None if the run never entered it."""
        found = None
        for transition in self.store.transitions(trace_id):
            if transition.to_state == state.value:
                found = transition.payload
        return found

    def resumable(self) -> list[Run]:
        """Every run a restarted harness has to pick up, oldest first."""
        return [self._run(row) for row in self.store.runs_in(*(s.value for s in RESUMABLE))]

    @staticmethod
    def _run(row: RunRow) -> Run:
        return Run(row.trace_id, row.workflow, row.requester, row.question, State(row.state), row.service)
