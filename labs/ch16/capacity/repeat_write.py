"""What stops a run repeated after a failover from repeating a write, shown with W3's own code.

Chapter 16, step 5 (companion #14, O-D10). The outage drill shows a run in flight losing its model: W3's
harness ends a triage whose model is unavailable before any write, and a run that fails is started again. If
the first run had already written, the second must not write again on its strength. W3 has three locks on that,
all in its own code, and this check drives each one with the real parts and changes nothing in W3:

- W3's store (`state/store.py`): a write is reserved in the run's store before it runs and completed after, so
  the same run, resumed by a new harness process after dying mid-write, finds the reservation and verifies
  instead of writing (W3-D4).
- The approval service (`approval/approval_service.py`): the write tool asks whether a recorded yes covers
  exactly this call in this run, within its time, not yet applied, and the apply mark is set once. An approval
  is bound to its run's trace id, so a second run can't borrow the first run's yes, and a harness that lost
  its store can't apply the first run's yes twice.
- A person: a second run files its own request, and nothing is written until someone approves it.

The approval service runs behind its own HTTP layer on 127.0.0.1, the writer is W3's `Writer` over a fresh
cluster-state file, and the harness is W3's `Harness` over a fresh store, driven by a scripted model. The
membership table and the approver's token come from W3's test fixtures (`workflows/w3-incident/tests/conftest.py`,
loaded under a name of its own), as W3's own tests build them.

Run (from labs/ch16):  python capacity/repeat_write.py      # prints the cases; run_drills.py records them
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
COMPANION = HERE.parents[2]
W3 = COMPANION / "workflows" / "w3-incident"
SERVICE = "claims-api"
SERVICE_KEY = "w3-approval-service-key-for-the-ch16-check"


def w3_fixtures() -> Any:
    """W3's test fixtures as a module: it puts W3's folders on the path and builds the table and tokens."""
    name = "w3_conftest_for_ch16"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, W3 / "tests" / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    for folder in (W3 / "servers", W3 / "approval", W3 / "state", W3 / "harness"):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    return module


class WriteTools:
    """W3's `Writer` as the harness's write tools (args, approval_id), with the run's trace id handed over the
    way W3's own test does it; `die_after` ends the process right after the write, before the harness records
    it, as a pod lost in a failover would."""

    def __init__(self, writer: Any, kill: type[BaseException]) -> None:
        self.writer, self.kill = writer, kill
        self.trace_id: str | None = None
        self.die_after = False
        self.calls: list[tuple[str, str]] = []

    def tools(self) -> dict[str, Any]:
        def restart(args: dict[str, Any], approval_id: str) -> dict[str, Any]:
            result = self.writer.restart_deployment(args, approval_id, trace_id=self.trace_id)
            self.calls.append((approval_id, self.trace_id))
            if self.die_after:
                raise self.kill()
            return result

        def scale(args: dict[str, Any], approval_id: str) -> dict[str, Any]:
            return self.writer.scale_deployment(args, approval_id, trace_id=self.trace_id)

        return {"restart_deployment": restart, "scale_deployment": scale}


@contextmanager
def w3_scope() -> Iterator[None]:
    """W3's folders on the path and the workflows' modules imported for as long as the check runs, none left after.

    W3's fixtures import W3's modules and W2's, and W3's `store` and W2's `answer` share their names with W1's,
    which the ledger's code imports by name, so a module of theirs left in `sys.modules` would be handed to the next
    importer of W1's.
    """
    path, before = list(sys.path), set(sys.modules)
    workflows = W3.parent.resolve()
    try:
        yield
    finally:
        sys.path[:] = path
        for name in set(sys.modules) - before:
            found = getattr(sys.modules[name], "__file__", None)
            if found and Path(found).resolve().is_relative_to(workflows):
                del sys.modules[name]


def check(work: Path | None = None) -> dict[str, Any]:
    """Every case: what the second attempt presented, whether the write ran, and what refused it."""
    with w3_scope():
        return _check(work)


def _check(work: Path | None) -> dict[str, Any]:
    c = w3_fixtures()
    from approval_client import ApprovalClient
    from approval_service import Service, serve
    from cluster_state import ClusterState
    from machine import State
    from writer import ApprovalNotCovered, Writer

    import httpx

    work = Path(work or tempfile.mkdtemp(prefix="ch16-repeat-"))
    work.mkdir(parents=True, exist_ok=True)
    log = io.StringIO()
    table = c.membership_table()
    service = Service(work / "approvals.sqlite", lambda: table, c.SECRET, c.APPROVERS, log)
    server = serve(service, SERVICE_KEY, port=c.free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    client = ApprovalClient(url, SERVICE_KEY, requester_upn=f"{c.ENGINEER}@larkspur.example")
    state_file = work / "cluster.json"
    writer = Writer(client, state_file)
    tools = WriteTools(writer, c.KillSwitch)
    parts = {"reads": c.Reads(), "writer": tools, "verifier": writer, "approvals": client}
    look = c.reply(c.call("get_pod_status", {"service": SERVICE}, "c1"), reasoning="look first")
    restart = c.reply(c.call("restart_deployment", {"service": SERVICE}, "c2"), reasoning="runbook step 3: restart")
    requester = c.USERS[c.ENGINEER]
    run_a, run_b = uuid.uuid4().hex, uuid.uuid4().hex
    store_a, store_b = work / "w3-state.sqlite", work / "w3-state-after-failover.sqlite"
    rows: list[dict[str, Any]] = []

    def generation() -> int:
        return ClusterState(state_file).current(SERVICE)["generation"]

    def approve(approval_id: str) -> None:
        httpx.post(f"{url}/requests/{approval_id}/decisions", json={"approved": True}, timeout=10,
                   headers={"X-Larkspur-Actor": c.approver_token(c.APPROVER)}).raise_for_status()

    def attempt(case: str, approval_id: str, trace_id: str, presented: str) -> None:
        before = generation()
        try:
            writer.restart_deployment({"service": SERVICE}, approval_id, trace_id=trace_id)
            refused = None
        except ApprovalNotCovered as exc:
            refused = str(exc)
        rows.append({"case": case, "presented": presented, "write_ran": generation() != before,
                     "generation_before": before, "generation_after": generation(),
                     "stopped_by": "the approval service" if refused else None, "reason": refused})

    try:
        # Run A: the incident triaged, the restart proposed, a person's yes, and the pod lost right after the write.
        first = c.harness_over(store_a, c.ScriptedModel([look, restart]), parts)
        tools.trace_id = run_a
        first.start(f"{SERVICE} is paging", requester, trace_id=run_a)
        approval_a = first.machine.payload(run_a, State.AWAITING_APPROVAL)["approval_id"]
        approve(approval_a)
        tools.die_after = True
        g0 = generation()
        try:
            first.resume(run_a)
            died = False
        except c.KillSwitch:
            died = True
        tools.die_after = False
        rows.append({"case": "run A writes under its approval, and its pod is lost before it records the result",
                     "presented": "run A's approval", "write_ran": generation() != g0, "generation_before": g0,
                     "generation_after": generation(), "stopped_by": None,
                     "reason": "the process died after the write" if died else "it didn't die"})
        first.machine.store.close()

        # The same run, resumed by a new harness process over the store that survived.
        resumed = c.harness_over(store_a, c.ScriptedModel([]), parts)
        before = generation()
        run = resumed.resume(run_a)
        verifying = resumed.machine.payload(run_a, State.VERIFYING) or {}
        rows.append({"case": "run A resumed by a new harness process, its store intact",
                     "presented": "run A's approval, reserved in run A's store", "write_ran": generation() != before,
                     "generation_before": before, "generation_after": generation(),
                     "stopped_by": "W3's store" if verifying.get("write", {}).get("repeat") else None,
                     "reason": f"the write is marked {verifying.get('write', {}).get('status')}; the run ended "
                               f"{run.state.value} after verifying"})
        resumed.machine.store.close()

        # Run B: the run failed during the outage and was started again, a new run for the same incident.
        second = c.harness_over(store_b, c.ScriptedModel([look, restart]), parts)
        tools.trace_id = run_b
        second.start(f"{SERVICE} is paging", requester, trace_id=run_b)
        approval_b = second.machine.payload(run_b, State.AWAITING_APPROVAL)["approval_id"]
        attempt("run B presents run A's approval", approval_a, run_b, "run A's approval, under run B's trace id")
        attempt("run A's approval presented again, by a harness that lost run A's store", approval_a, run_a,
                "run A's approval, under run A's trace id")
        attempt("run B presents its own approval before anyone has decided", approval_b, run_b,
                "run B's approval, pending")
        approve(approval_b)
        before = generation()
        run = second.resume(run_b)
        rows.append({"case": "a person approves run B's own request", "presented": "run B's approval, approved",
                     "write_ran": generation() != before, "generation_before": before,
                     "generation_after": generation(), "stopped_by": None,
                     "reason": f"a second restart, decided by a person; the run ended {run.state.value}"})
        second.machine.store.close()
    finally:
        server.shutdown()
        server.server_close()
    events = [json.loads(line) for line in log.getvalue().splitlines() if line.strip()]
    checks = [{"approval": "run A" if e.get("approval_id") == approval_a else "run B", "trace": (
        "run A" if e.get("trace_id") == run_a else "run B"), "covers": e.get("covers"), "reason": e.get("reason")}
        for e in events if e.get("event") == "approval_check"]
    return {"rows": rows, "approval_checks": checks,
            "approvals": {"run A": service.get(approval_a)["status"], "run B": service.get(approval_b)["status"]},
            "restarts": generation() - 1, "writes_called": len(tools.calls)}


def main() -> int:
    result = check()
    for row in result["rows"]:
        print(f"{row['case']}: write ran {row['write_ran']} ({row['generation_before']} -> {row['generation_after']})"
              f"{'; ' + row['stopped_by'] + ': ' + row['reason'] if row['stopped_by'] else ''}")
    print(f"restarts: {result['restarts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
