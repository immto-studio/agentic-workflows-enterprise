"""Run W3's golden incidents through the harness end to end on a local model, score, and record.

Step 5's second half (W3-D14), in W2's shape (eval/answer_eval.py). For each incident the runner opens
the three W2 read servers, the writer, and the ServiceNow server under their identities, runs the W3
harness as the incident's persona, and when a run reaches awaiting_approval, approves it as a second
eligible person from the approvers group so the write executes; between incidents the cluster-state and
ServiceNow-state files are reset, so every run starts from the deployed namespace. Each run is recorded
in the scorer's shape (triage, proposal, executed, approved, labels, reads, hidden_reads) and scored by
eval/score.py.

The pure helpers (triage_text, make_record, eligible_approver) are tested without a model; main() wires
the real servers and the gateway and needs Ollama and the gateway up.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
W3 = HERE.parent
for folder in (W3 / "state", W3 / "harness", W3 / "approval", W3 / "servers",
               W3.parent / "w1-knowledge-assistant" / "knowledge-server"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from access import issue  # noqa: E402
from machine import Machine, State  # noqa: E402


# --- assembling the record the scorer reads -------------------------------------------------------

def triage_text(machine: Machine, trace_id: str) -> str:
    """The prose a right triage would be scored on: the model's answer or its proposal reasoning, plus the
    verification and any refusal text, gathered from the run's transitions."""
    parts: list[str] = []
    for transition in machine.history(trace_id):
        payload = transition.payload
        for key in ("answer", "reasoning", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        verification = payload.get("verification")
        if isinstance(verification, dict):
            parts.append(f"verification ready {verification.get('ready')} of {verification.get('desired')}")
    return " ".join(dict.fromkeys(parts))  # de-duplicated, in order


def _service_of(event: dict[str, Any]) -> str | None:
    """The service a read event named, from its args or its own field."""
    args = event.get("args")
    if isinstance(args, dict) and args.get("service"):
        return args["service"]
    return event.get("service")


def proposal_of(machine: Machine, trace_id: str) -> dict[str, Any] | None:
    payload = machine.payload(trace_id, State.PROPOSING)
    if not payload or not payload.get("proposal"):
        return None
    call = payload["proposal"]
    return {"tool": call["name"], "args": call["args"]}


def make_record(machine: Machine, run: Any, trace_id: str, labels: list[tuple[str, str]],
                read_events: list[dict[str, Any]], hidden: set[str]) -> dict[str, Any]:
    """The scorer's shape for one finished run."""
    # A write the tool refused (status failed) reached verifying without acting, so it did not execute.
    verifying = machine.payload(trace_id, State.VERIFYING)
    acted = verifying is not None and (verifying.get("write") or {}).get("status") != "failed"
    executed = acted or run.state is State.ROLLED_BACK
    approved = machine.payload(trace_id, State.EXECUTING) is not None
    reads = [e["tool"] for e in read_events if e.get("event") == "tool_call" and e.get("ok") and "tool" in e]
    # A leak is a read that SUCCEEDED on a service the persona may not see; a read the server refused is the
    # control working, not a leak (the scorer's reads_ok fails only on a successful hidden read).
    hidden_reads = sorted({_service_of(e) for e in read_events
                           if e.get("event") == "tool_call" and e.get("ok") and _service_of(e) in hidden})
    return {
        "id": run.trace_id,
        "triage": triage_text(machine, trace_id),
        "proposal": proposal_of(machine, trace_id),
        "executed": bool(executed),
        "approved": bool(approved),
        "labels": [[c, a] for c, a in labels],
        "reads": reads,
        "hidden_reads": [h for h in hidden_reads if h],
        "state": run.state.value,
    }


# --- auto-approval: a second eligible person approves so the write executes ------------------------

def eligible_approver(members_by_user: dict[str, set[str]], group: str, requester_oid: str,
                      oid_of: dict[str, str]) -> str | None:
    """A user who holds the approvers group and is not the requester; None when none exists (the
    self-approval case, where the only group member is the requester)."""
    for user, groups in members_by_user.items():
        oid = oid_of.get(user)
        if group in groups and oid and oid != requester_oid:
            return user
    return None


def approve_as(decide: Callable[[str, str], Any], approval_id: str, approver_token: str) -> None:
    """Post a yes with the approver's token (the service, or the HTTP bot, does the rest)."""
    decide(approval_id, approver_token)


# --- the per-incident run (used by main; the test drives the harness in-process) -----------------

def run_one(incident: dict[str, Any], harness: Any, model: Any, *, trace_id: str, requester_oid: str,
            read_log: list[dict[str, Any]], hidden: set[str], approve: Callable[[str], bool]) -> dict[str, Any]:
    """Start the run, approve it if it waits, and record it. `approve(approval_id)` returns whether a
    second eligible person approved (False for the self-approval case)."""
    run = harness.start(incident["question"], requester_oid, trace_id=trace_id)
    if run.state is State.AWAITING_APPROVAL:
        approval_id = harness.machine.payload(trace_id, State.AWAITING_APPROVAL)["approval_id"]
        if approve(approval_id):
            run = harness.resume(trace_id)
    record = make_record(harness.machine, run, trace_id, list(getattr(model, "labels", [])), read_log, hidden)
    record["id"] = incident["id"]
    return record


def readme_table(summaries: dict[str, dict[str, Any]]) -> str:
    """A table for the README: one column per model, the scorer's headline counts."""
    models = list(summaries)
    rows = [("Cases passed", lambda s: f"{s['passed']} of {s['cases']}"),
            ("Key facts stated", lambda s: f"{s['facts'][0]} of {s['facts'][1]}"),
            ("Step proposed correctly", lambda s: f"{s['steps'][0]} of {s['steps'][1]}"),
            ("Nothing outside the runbook", lambda s: f"{s['runbook'][0]} of {s['runbook'][1]}"),
            ("Injection cases failed", lambda s: f"{s['injection_cases'] - s['injections_ok']} of {s['injection_cases']}"),
            ("Writes without an approval", lambda s: str(s['writes_without_approval'])),
            ("Writes recommended in prose, none proposed", lambda s: f"{s['writes_in_prose']} of {s['cases']}"),
            ("Labels correct", lambda s: f"{s['labels_ok']} of {s['cases']}")]
    head = "|Check |" + " |".join(models) + " |"
    sep = "|" + "---|" * (len(models) + 1)
    lines = [head, sep]
    for label, fn in rows:
        lines.append("|" + label + " |" + " |".join(fn(summaries[m]) for m in models) + " |")
    return "\n".join(lines)


# issue() is re-exported so the live wiring (eval/lab.py, which starts the five MCP servers, the approval
# service, and the gateway, and runs run_one over each incident on a model) can mint persona tokens. The
# recorded runs on gpt-oss-20b and Gemma 4 12B are produced there and stored under results/2026-11-02.
__all__ = ["triage_text", "proposal_of", "make_record", "eligible_approver", "run_one", "readme_table", "issue"]
