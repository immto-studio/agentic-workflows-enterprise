"""W3's harness: the state machine driven end to end, from the trigger to a terminal state, resumable at every
state from the store.

Chapter 12, W3-D2, W3-D5, W3-D7, W3-D8. The harness is given its parts (`Services`): the model, the
read tools with their allowlist, the write tools, the verification read, the rollback, and the
approval service. In the lab's tests they are fakes; later steps supply W2's servers, the writer,
and the approval service. The harness itself holds nothing between calls: `start` runs a trigger to
its first stop (a terminal state, or awaiting approval) and `resume` picks any run up from the store,
which is what a restarted process, or the approval service's callback, calls.

Every step acts after its transition is recorded (machine.advance), and every side effect that may
run once (the write, the rollback) is reserved in the store before it runs and completed after it,
so a harness that dies between the two leaves a mark a resumed harness reads: it does not act again,
it verifies. A write tool that refuses, because the approval does not cover the call or could not be
checked, answers with an error; the harness records the write as failed, never calls it again, and
lets the verification read close the run.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

HERE = Path(__file__).resolve().parent
W3 = HERE.parent
for folder in (W3 / "state", W3 / "harness"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from loop import MAX_READS, Outcome, run_steps  # noqa: E402
from machine import Machine, Run, State  # noqa: E402
from store import AlreadyApplied  # noqa: E402

# (args, approval_id) -> the write's result. Its `previous` is the state a rollback returns to, None when
# the step has none (a restart); a tool that did not act answers {"error": reason}.
WriteTool = Callable[[dict[str, Any], str], dict[str, Any]]
Verify = Callable[[Run, dict[str, Any], dict[str, Any]], dict[str, Any]]  # (run, proposal, write) -> {"ok": bool, ...}
Rollback = Callable[[Run, dict[str, Any], dict[str, Any], str], dict[str, Any]]  # (run, proposal, write, approval_id)


class Approvals(Protocol):
    """What the harness needs from the approval service (W3-D5). The service of a later step implements it."""

    def request(self, trace_id: str, call: dict[str, Any], requester: str) -> str:
        """File the request; return the approval's number."""

    def decision(self, approval_id: str) -> dict[str, Any] | None:
        """{"approved": bool, "by": object id, "reason": str} once decided; None while pending."""

    def expired(self, approval_id: str) -> bool:
        """True once the request's expiry has passed without a decision."""


@dataclass
class Services:
    model: Callable[[list[dict[str, str]]], dict[str, Any]]
    tools: dict[str, Callable[..., dict]]
    allowed: dict[str, set[str]]
    writes: dict[str, WriteTool]
    verify: Verify
    approvals: Approvals
    rollback: Rollback | None = None
    max_reads: int = MAX_READS


def _status(result: Any, finished: bool = True) -> str:
    """What the store says of a side effect: started (reserved, never completed), failed (the tool
    answered with an error and did not act), or applied."""
    if not finished:
        return "started"
    return "failed" if isinstance(result, dict) and "error" in result else "applied"


class Harness:
    def __init__(self, machine: Machine, services: Services) -> None:
        self.machine = machine
        self.services = services

    # --- entry points -----------------------------------------------------------------------------

    def start(self, question: str, requester: str, *, trace_id: str | None = None,
              service: str | None = None) -> Run:
        run = self.machine.start(trace_id or uuid.uuid4().hex, requester=requester, question=question,
                                 service=service)
        return self._triage(run)

    def resume(self, trace_id: str) -> Run:
        """Pick a run up where the store left it. Safe to call any number of times."""
        run = self.machine.load(trace_id)
        if run.state in (State.TRIGGERED, State.TRIAGING):
            return self._triage(run)
        if run.state is State.PROPOSING:
            return self._await(run, self.machine.payload(run.trace_id, State.PROPOSING)["proposal"])
        if run.state is State.AWAITING_APPROVAL:
            return self._decide(run)
        if run.state is State.EXECUTING:
            return self._execute(run)
        if run.state is State.VERIFYING:
            return self._verify(run)
        return run  # terminal

    def resume_all(self) -> list[Run]:
        return [self.resume(run.trace_id) for run in self.machine.resumable()]

    # --- the states -------------------------------------------------------------------------------

    def _triage(self, run: Run) -> Run:
        if run.state is State.TRIGGERED:
            run = self.machine.advance(run, State.TRIAGING)
        s = self.services
        outcome: Outcome = run_steps(run.question, s.model, s.tools, s.allowed, set(s.writes), max_reads=s.max_reads)
        if outcome.kind == "answer":
            return self.machine.advance(run, State.DONE, answer=outcome.text, reads=outcome.reads, step=None)
        if outcome.kind != "proposal":
            # answer's other ends, an unavailable model among them, all end the run before any write (W3-D10).
            return self.machine.advance(run, State.REFUSED, reason=outcome.reason, text=outcome.text,
                                        reads=outcome.reads)
        call = outcome.call or {}
        run = self.machine.advance(run, State.PROPOSING, proposal=call, reasoning=outcome.reasoning,
                                   reads=outcome.reads, service=call.get("args", {}).get("service"))
        return self._await(run, call)

    def _await(self, run: Run, proposal: dict[str, Any]) -> Run:
        approval_id = self.services.approvals.request(run.trace_id, proposal, run.requester)
        return self.machine.advance(run, State.AWAITING_APPROVAL, approval_id=approval_id, proposal=proposal)

    def _decide(self, run: Run) -> Run:
        waiting = self.machine.payload(run.trace_id, State.AWAITING_APPROVAL) or {}
        approval_id = waiting["approval_id"]
        decision = self.services.approvals.decision(approval_id)
        if decision is None:
            if self.services.approvals.expired(approval_id):
                return self.machine.advance(run, State.DROPPED, approval_id=approval_id,
                                            reason="the approval expired before anyone decided")
            return run  # still waiting; the state is in the store
        if not decision.get("approved"):
            return self.machine.advance(run, State.REFUSED, approval_id=approval_id, by=decision.get("by"),
                                        reason=f"declined: {decision.get('reason', '')}".rstrip(": "))
        run = self.machine.advance(run, State.EXECUTING, approval_id=approval_id, by=decision.get("by"))
        return self._execute(run)

    def _execute(self, run: Run) -> Run:
        executing = self.machine.payload(run.trace_id, State.EXECUTING) or {}
        proposal = (self.machine.payload(run.trace_id, State.PROPOSING) or {})["proposal"]
        approval_id = executing["approval_id"]
        key = f"{approval_id}:{proposal['name']}"
        store = self.machine.store
        try:
            store.reserve(key, run.trace_id)
        except AlreadyApplied as earlier:
            # The write ran before, or started and the process died: never a second time (W3-D4).
            write = {"status": _status(earlier.result, earlier.finished), "result": earlier.result, "repeat": True}
        else:
            result = self.services.writes[proposal["name"]](proposal["args"], approval_id)
            store.complete(key, result)
            write = {"status": _status(result), "result": result, "repeat": False}
        run = self.machine.advance(run, State.VERIFYING, write=write, approval_id=approval_id)
        return self._verify(run)

    def _verify(self, run: Run) -> Run:
        verifying = self.machine.payload(run.trace_id, State.VERIFYING) or {}
        proposal = (self.machine.payload(run.trace_id, State.PROPOSING) or {})["proposal"]
        write = verifying["write"]
        check = self.services.verify(run, proposal, write)
        if check.get("ok"):
            return self.machine.advance(run, State.DONE, verification=check, step=proposal["name"])
        previous = (write.get("result") or {}).get("previous") if isinstance(write.get("result"), dict) else None
        if self.services.rollback is None or previous is None:
            # A step with nothing to return to (a restart): the verification is its record (W3-D8).
            return self.machine.advance(run, State.DONE, verification=check, step=proposal["name"], rollback=None)
        key = f"{verifying['approval_id']}:rollback"
        store = self.machine.store
        try:
            store.reserve(key, run.trace_id)
        except AlreadyApplied as earlier:
            rollback = {"status": _status(earlier.result, earlier.finished), "result": earlier.result, "repeat": True}
        else:
            result = self.services.rollback(run, proposal, write, verifying["approval_id"])
            store.complete(key, result)
            rollback = {"status": _status(result), "result": result, "repeat": False}
        return self.machine.advance(run, State.ROLLED_BACK, verification=check, step=proposal["name"],
                                    rollback=rollback)
