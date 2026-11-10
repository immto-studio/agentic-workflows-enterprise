"""The three SLIs of each workflow, each a ratio of good events to valid events, over runs of one shape.

Chapter 16, step 6 (companion #14, O-D12). A run, kept or simulated, becomes one `RunEvent`: how it ended, how
long it took, and, where a person decided on what it proposed, what they decided. The SLIs read nothing else:

- success: runs that end in an answer, a refusal the harness made by rule (a correct refusal, as opposed to a
  failure the harness words as one), or a proposal, over valid runs. A budget stop, a timeout, the model
  unavailable, and an error are bad. A run the workflow's own monthly budget or request rate refused is the
  control holding (ch05:498): it is not valid, and it shows on the workflow's budget and 429 panels instead.
- latency: runs whose time is under the workflow's threshold, over the runs that were good for success, so a
  failure is not counted twice.
- outcome: proposals a person accepted (W3's actions approved and not reverted, W4's risk class kept by the board,
  W5's pull requests merged) over the proposals a person decided. A proposal nobody decided is not valid yet.

An event counts at the time it becomes known (`placed`): a run when it ends (`at`), an outcome when a person
decides (`decided_at`). A month, a budget and a burn-rate window all take the events placed inside them
(`in_window`), so a proposal made in one month and decided in the next counts for success in the first and for
outcome in the second, and a decision made inside the month on a proposal from the lead-in counts, as any rolling
window would see it (slos.yaml, `in_the_month`).

The controls (residency, the never-list, the budgets) get no error budget. A run that breached one carries
`violation`, and `incidents` lists it; no SLI reads the field, so a breach is never budget spent, whatever the
run's end (tests/test_slo_slis.py holds it).

The kept runs' events come from what each workflow kept (`kept_events`): the answer text against the harness's
fixed sentences for W1 and W2, imported from the harnesses, the run's state and triage for W3, the pack for W4,
and the night's record, log and ledger for W5. slos.yaml says, for each SLI of each workflow, what makes a run
valid, which file, field, or span attribute each event comes from, and what the kept runs can't supply.
"""

from __future__ import annotations

import statistics
import sys
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "ledger", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import costlines  # noqa: E402  the ledger's reader of every kept run, which imports chapter 15's registry
import registry  # noqa: E402

SLOS = HERE / "slos.yaml"
WORKFLOWS = ("w1", "w2", "w3", "w4", "w5")
GOOD = ("answer", "refusal", "proposal")
BAD = ("budget_stop", "timeout", "unavailable", "error")
INVALID = ("own_limit",)
ENDS = GOOD + BAD + INVALID
DECISIONS = ("accepted", "rejected", "reverted")
CONTROLS = ("residency", "never_list", "budget")
SLI_NAMES = ("success", "latency", "outcome")


@dataclass(frozen=True)
class RunEvent:
    """One run of a workflow as the SLIs see it. `at` and `decided_at` are seconds from the month's start, None
    for a kept run; `probe` marks the hourly probe's runs, which only the alerts count."""
    workflow: str
    run_id: str
    end: str
    seconds: float | None
    at: float | None = None
    decision: str | None = None
    decided_at: float | None = None
    probe: bool = False
    restricted: bool = False
    violation: str | None = None
    injected: str | None = None
    source: str = ""
    reason: str = ""
    unit: str = "run"           # "run", or "decision": a person's decision on one of a run's proposals (W5)

    def __post_init__(self) -> None:
        if self.end not in ENDS:
            raise ValueError(f"{self.run_id}: end {self.end!r} is not one of {ENDS}")
        if self.decision is not None and self.decision not in DECISIONS:
            raise ValueError(f"{self.run_id}: decision {self.decision!r} is not one of {DECISIONS}")
        if self.unit not in ("run", "decision"):
            raise ValueError(f"{self.run_id}: unit {self.unit!r} is not run or decision")
        if self.violation is not None and self.violation not in CONTROLS:
            raise ValueError(f"{self.run_id}: violation {self.violation!r} is not one of {CONTROLS}")


@dataclass(frozen=True)
class Ratio:
    good: int
    valid: int

    @property
    def value(self) -> float | None:
        return None if not self.valid else self.good / self.valid

    @property
    def bad(self) -> int:
        return self.valid - self.good


def load(path: Path = SLOS) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --- the SLIs ---------------------------------------------------------------------------------------------

def success_valid(e: RunEvent) -> bool:
    return e.unit == "run" and e.end not in INVALID


def success_good(e: RunEvent) -> bool:
    return e.end in GOOD


def latency_valid(e: RunEvent) -> bool:
    return success_valid(e) and success_good(e) and e.seconds is not None


def latency_good(e: RunEvent, threshold_s: float) -> bool:
    return e.seconds is not None and e.seconds <= threshold_s


def outcome_valid(e: RunEvent) -> bool:
    return e.decision is not None


def outcome_good(e: RunEvent) -> bool:
    return e.decision == "accepted"


def classify(e: RunEvent, sli: str, threshold_s: float | None = None) -> bool | None:
    """True for a good event, False for a bad one, None when the run is not valid for the SLI."""
    if sli == "success":
        return success_good(e) if success_valid(e) else None
    if sli == "latency":
        if threshold_s is None:
            raise ValueError("the latency SLI needs the workflow's threshold")
        return latency_good(e, threshold_s) if latency_valid(e) else None
    if sli == "outcome":
        return outcome_good(e) if outcome_valid(e) else None
    raise ValueError(f"no SLI {sli!r}")


def placed(e: RunEvent, sli: str) -> float | None:
    """When the event counts for the SLI: a run when it ends, an outcome when a person decides."""
    return e.decided_at if sli == "outcome" else e.at


def in_window(e: RunEvent, sli: str, begin: float | None, end: float | None) -> bool:
    """Whether the event is placed in [begin, end) for the SLI; an open bound is None, and an unplaced event is out."""
    when = placed(e, sli)
    return when is not None and (begin is None or when >= begin) and (end is None or when < end)


def ratio(events: Iterable[RunEvent], sli: str, threshold_s: float | None = None, begin: float | None = None,
          end: float | None = None) -> Ratio:
    """Good over valid events for the SLI, over the events placed in [begin, end) when a bound is given."""
    good = valid = 0
    for e in events:
        if (begin is not None or end is not None) and not in_window(e, sli, begin, end):
            continue
        verdict = classify(e, sli, threshold_s)
        if verdict is not None:
            valid += 1
            good += bool(verdict)
    return Ratio(good, valid)


def incidents(events: Iterable[RunEvent]) -> list[RunEvent]:
    """Every run that breached a control: an incident each, outside every error budget."""
    return [e for e in events if e.violation is not None]


def threshold(slos: dict[str, Any], workflow: str) -> float:
    return float(slos["workflows"][workflow]["slis"]["latency"]["threshold_s"])


def measured(events: list[RunEvent], slos: dict[str, Any], workflow: str, begin: float | None = None,
             end: float | None = None) -> dict[str, Ratio | None]:
    """The three SLIs of one workflow over its events, or over those placed in [begin, end); None for an SLI the
    workflow doesn't have."""
    spec = slos["workflows"][workflow]["slis"]
    out: dict[str, Ratio | None] = {}
    for sli in SLI_NAMES:
        if spec[sli].get("target") is None:
            out[sli] = None
            continue
        out[sli] = ratio(events, sli, threshold(slos, workflow) if sli == "latency" else None, begin, end)
    return out


# --- the kept runs ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Sentences:
    """The fixed sentences each harness ends a run with, imported from the harnesses themselves."""
    w1_budget: str
    w1_search_failed: str
    w1_refusal_words: str
    w2_budget: str
    w2_read_failed: str
    w2_refusal_words: str
    w2_refusal: str
    w2_max_reads: int
    w3_budget: str
    w3_unavailable: str


def sentences() -> Sentences:
    with registry.isolated(("workflows/w1-knowledge-assistant/harness",)):
        import answer as w1
        one = (w1.BUDGET_EXHAUSTED, w1.SEARCH_FAILED, w1.REFUSAL_WORDS)
    with registry.isolated(("workflows/w2-ops-assistant/harness",)):
        import answer as w2
        two = (w2.BUDGET_EXHAUSTED, w2.READ_FAILED, w2.REFUSAL_WORDS, w2.REFUSAL, w2.MAX_READS)
    with registry.isolated(("workflows/w3-incident/harness",)):
        import loop
        three = (loop.BUDGET_EXHAUSTED, loop.MODEL_UNAVAILABLE)
    return Sentences(*one, *two, *three)


def _answer_end(text: str, budget: str, failed: str, refusal_words: str) -> tuple[str, str]:
    text = (text or "").strip()
    if text == budget:
        return "budget_stop", "the harness's step-budget sentence"
    if text == failed:
        return "error", "the harness's failure sentence"
    if refusal_words in text.lower():
        return "refusal", "the harness's refusal sentence"
    return "answer", ""


def w2_budget_stop(record: dict[str, Any], s: Sentences) -> bool:
    """W2's harness words a step-budget stop as its own refusal (answer.finish) and marks it larkspur.refused, so the
    text can't tell it from a refusal by rule. The run's calls can: the harness's exact refusal after MAX_READS reads
    and one model call more, the call that asked for another read. Production has the same count in the cost lines
    and the span tree of the trace id."""
    return (record["answer"].startswith(s.w2_refusal) and len(record.get("read_events") or []) == s.w2_max_reads
            and len(record.get("model_calls") or []) == s.w2_max_reads + 1)


W3_PROPOSED = ("awaiting_approval", "executing", "verifying", "done", "rolled_back", "dropped")


def _w3_end(record: dict[str, Any], s: Sentences) -> tuple[str, str, str | None]:
    triage, state = (record.get("triage") or "").strip(), record.get("state")
    decision = None
    if record.get("proposal"):
        if state == "rolled_back":
            decision = "reverted"
        elif record.get("approved") and record.get("executed") and state == "done":
            decision = "accepted"
        elif state == "refused" and record.get("approved") is False and record.get("denied"):
            decision = "rejected"
    if triage == s.w3_budget:
        return "budget_stop", "the step-budget sentence", decision
    if triage == s.w3_unavailable:
        return "unavailable", "the model-unavailable sentence", decision
    if state == "refused":
        return "refusal", "a refusal by the harness's rules", decision
    if record.get("proposal") and state in W3_PROPOSED:
        return "proposal", f"a proposal, the run in {state}", decision
    if state == "done":
        return "answer", "", decision
    return "error", f"the run ended in {state!r}", decision


def _restricted(run: costlines.Run) -> bool:
    return any(line.alias == costlines.RESTRICTED_ALIAS for line in run.lines)


def _main_records(kept: registry.Run) -> dict[str, dict[str, Any]]:
    data = registry.read_json(registry.path(kept.main))
    if kept.workflow in ("w1", "w2"):
        key = (lambda r: f"{r['id']}/{r['persona']}") if kept.workflow == "w1" else (lambda r: r["id"])
        return {key(r): r for r in data["results"]}
    if kept.workflow == "w3":
        return {r["id"]: r for r in data["records"]}
    return data


def _kept_of(workflow: str) -> list[registry.Run]:
    return registry.kept_runs(workflow) + costlines.traced_runs(workflow)


def _w5_outcomes(kept: registry.Run, run_name: str) -> list[RunEvent]:
    """One event per pull request a person decided, from the kept run's ledger: merged is accepted, closed without
    a merge rejected; an open one nobody has decided yet."""
    ledger = registry.path(kept.folder) / f"nights-{kept.model}" / "ledger.json"
    if not ledger.exists():
        return []
    out = []
    for key, row in sorted(registry.read_json(ledger)["findings"].items()):
        pr = row.get("pull_request") or {}
        decision = {"merged": "accepted", "closed": "rejected"}.get(pr.get("state"))
        if decision:
            out.append(RunEvent("w5", f"{run_name}:{key}", "proposal", None, decision=decision,
                                source=f"{kept.folder}/nights-{kept.model}/ledger.json",
                                reason=f"pull request {pr.get('number')} {pr.get('state')}", unit="decision"))
    return out


def kept_events(s: Sentences | None = None) -> dict[str, list[RunEvent]]:
    """Every kept run of W1 to W5 as RunEvents, keyed by "<workflow> <model> <label>". W5's pull requests that a
    person decided are events of their own under the same key, for the outcome SLI only."""
    s = s or sentences()
    runs = {(r.workflow, r.kept_run, r.case): r for r in costlines.collect(WORKFLOWS)}
    out: dict[str, list[RunEvent]] = {}
    for workflow in WORKFLOWS:
        for kept in _kept_of(workflow):
            name = f"{kept.model} {kept.label}"
            key = f"{workflow} {name}"
            events: list[RunEvent] = []
            if workflow == "w5":
                for case, night in registry.outputs(kept).items():
                    record, log = night["record"], night["events"] or []
                    run = runs[(workflow, name, case)]
                    done = any(e.get("event") == "night_done" for e in log)
                    if record.get("stopped"):
                        end, why = "refusal", "the night's check refused it"
                    elif done:
                        end, why = "proposal", "the night ran to night_done"
                    else:
                        end, why = "error", "no night_done line"
                    events.append(RunEvent(workflow, run.run_id, end, record.get("duration_s"), source=kept.main,
                                           reason=why))
                events += _w5_outcomes(kept, name)
                out[key] = events
                continue
            for case, record in _main_records(kept).items():
                run = runs[(workflow, name, case)]
                decision, seconds = None, run.seconds
                if workflow == "w1":
                    end, why = _answer_end(record["answer"], s.w1_budget, s.w1_search_failed, s.w1_refusal_words)
                elif workflow == "w2":
                    end, why = _answer_end(record["answer"], s.w2_budget, s.w2_read_failed, s.w2_refusal_words)
                    if end == "refusal" and w2_budget_stop(record, s):
                        end, why = "budget_stop", "the harness's refusal after the read budget's last read and one more call"
                elif workflow == "w3":
                    end, why, decision = _w3_end(record, s)
                else:
                    end, why = ("proposal", "the pack written") if record.get("written") else ("error", "no pack")
                events.append(RunEvent(workflow, run.run_id, end, seconds, decision=decision,
                                       restricted=_restricted(run), source=kept.main, reason=why))
            out[key] = events
    return out


def pooled(kept: dict[str, list[RunEvent]], workflow: str) -> list[RunEvent]:
    return [e for key, events in kept.items() if key.split(" ", 1)[0] == workflow for e in events]


def measured_table(kept: dict[str, list[RunEvent]], slos: dict[str, Any]) -> dict[str, Any]:
    """The SLIs on the kept runs: per kept run and pooled per workflow, with the ends counted."""
    rows, pools = [], {}
    for key, events in kept.items():
        workflow, name = key.split(" ", 1)
        rows.append({"workflow": workflow, "kept_run": name, "runs": sum(1 for e in events if e.unit == "run"),
                     "ends": _ends(events), "slis": _as_json(measured(events, slos, workflow))})
    for workflow in WORKFLOWS:
        events = pooled(kept, workflow)
        secs = [e.seconds for e in events if e.seconds is not None and latency_valid(e)]
        pools[workflow] = {"ends": _ends(events), "slis": _as_json(measured(events, slos, workflow)),
                           "seconds_median": round(statistics.median(secs), 3) if secs else None,
                           "seconds_max": max(secs) if secs else None,
                           "decided": sum(1 for e in events if e.decision is not None)}
    return {"rows": rows, "pooled": pools}


def _ends(events: Iterable[RunEvent]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in events:
        if e.unit != "run":
            continue
        counts[e.end] = counts.get(e.end, 0) + 1
    return {end: counts[end] for end in ENDS if end in counts}


def _as_json(slis: dict[str, Ratio | None]) -> dict[str, Any]:
    return {name: None if r is None else {"good": r.good, "valid": r.valid,
                                          "value": None if r.value is None else round(r.value, 6)}
            for name, r in slis.items()}


def with_violation(e: RunEvent, control: str) -> RunEvent:
    return replace(e, violation=control)
