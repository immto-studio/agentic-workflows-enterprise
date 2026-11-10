"""The error-budget policy applied to a month: the freezes, the rungs down, and the record each one leaves.

Chapter 16, step 6 (companion #14, O-D12). policy.yaml holds the policy. For each workflow and each SLI with a target,
the budget in events is 1 minus the target times the valid events the SLI expects in the window (simulate.expected).
Walking the month's real runs in time order, a budget is spent at the bad event that reaches it. The first budget a
workflow spends freezes changes to its prompts and models; spending the outcome SLI's budget also moves it down a
rung, through step 4's rung switch in a dry run: budget/oncall.lower_rung writes the override and the change line
into a temporary state folder, and budget/rungs.plan reads the override back as the harness would before its next
run. A breach of a control is an incident and spends nothing (slis.incidents).
"""

from __future__ import annotations

import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "ledger", LAB / "budget", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import costlines  # noqa: E402,F401  the ledger's reader, which puts chapter 15's registry on sys.path
import oncall  # noqa: E402  step 4's levers, each with its change record
import registry  # noqa: E402
import rungs  # noqa: E402  step 4's rung switch
import simulate  # noqa: E402
import slis  # noqa: E402

POLICY = HERE / "policy.yaml"


def load(path: Path = POLICY) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def budgets(slos: dict[str, Any], expected: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Each SLI's error budget for the window, in events."""
    out: dict[str, dict[str, float]] = {}
    for workflow in slis.WORKFLOWS:
        spec = slos["workflows"][workflow]["slis"]
        out[workflow] = {sli: (1.0 - float(spec[sli]["target"])) * expected[workflow][sli]
                         for sli in slis.SLI_NAMES if spec[sli].get("target") is not None}
    return out


def spent(events: list[slis.RunEvent], sli: str, budget: float, threshold_s: float | None,
          begin: float = 0.0, end: float | None = None) -> dict[str, Any]:
    """When the budget was spent, if it was: the time of the bad event that reached it, walking real runs in order.

    An event counts at the time it becomes known (slis.placed): a run when it ends, an outcome when a person decides,
    and only the events placed in [begin, end) count. So the lead-in's runs, which end before the month, spend no
    budget of it, a decision made inside the month on one of their proposals does, and a decision made after the
    month's end spends the next month's."""
    rows = []
    for e in events:
        if e.probe or not slis.in_window(e, sli, begin, end):
            continue
        verdict = slis.classify(e, sli, threshold_s)
        if verdict is None:
            continue
        rows.append((slis.placed(e, sli), verdict, e.injected, e.run_id))
    rows.sort(key=lambda r: (r[0], r[3]))
    bad, valid, at, causes, at_causes = 0, 0, None, {}, None
    for when, verdict, tag, _ in rows:
        valid += 1
        if not verdict:
            bad += 1
            causes[tag or "baseline"] = causes.get(tag or "baseline", 0) + 1
            if at is None and bad >= budget:
                at = when
                at_causes = dict(causes)
    return {"budget_events": round(budget, 3), "bad": bad, "valid": valid,
            "consumed": None if not budget else round(bad / budget, 4), "spent_at": at,
            "causes_when_spent": at_causes, "causes": dict(sorted(causes.items()))}


def apply(month: simulate.Month, slos: dict[str, Any], policy: dict[str, Any],
          state_dir: Path | None = None) -> dict[str, Any]:
    """The policy's actions over the month, in time order, with every budget's account."""
    budget = budgets(slos, month.expected)
    accounts: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    lead = policy["on_call_lead"]
    temp = None
    if state_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="slo-policy-")
        state_dir = Path(temp.name)
    end = month.config["days"] * simulate.DAY
    try:
        changes = 0
        for workflow in slis.WORKFLOWS:
            mine = month.real(workflow)
            accounts[workflow] = {}
            for sli, events_budget in budget[workflow].items():
                threshold = slis.threshold(slos, workflow) if sli == "latency" else None
                account = spent(mine, sli, events_budget, threshold, end=end)
                account["spent_at_clock"] = (None if account["spent_at"] is None
                                             else simulate.clock(month.config, account["spent_at"]))
                accounts[workflow][sli] = account
            spent_now = sorted((a["spent_at"], sli) for sli, a in accounts[workflow].items() if a["spent_at"] is not None)
            if not spent_now:
                continue
            manifest = registry.manifest(workflow)
            people = [manifest["owner"], manifest["sponsor"]]
            first_at, first_sli = spent_now[0]
            actions.append(_freeze(month, workflow, first_sli, accounts[workflow][first_sli], first_at, people))
            for at, sli in spent_now[1:]:
                actions.append({"action": "budget spent", "workflow": workflow, "sli": sli, "at_s": round(at, 1),
                                "at": simulate.clock(month.config, at), "already": "frozen since "
                                + simulate.clock(month.config, first_at), **_account(accounts[workflow][sli]),
                                "told": people, "simulated": True})
            outcome = accounts[workflow].get("outcome")
            if outcome and outcome["spent_at"] is not None:
                changes += 1
                actions.append(_rung_down(month, workflow, manifest, outcome, lead, f"EC-SIM-{changes:02d}",
                                          state_dir))
    finally:
        if temp is not None:
            temp.cleanup()
    actions.sort(key=lambda a: (a["at_s"], a["workflow"], a["action"]))
    return {"simulated": True, "budgets": {w: {s: round(v, 3) for s, v in b.items()} for w, b in budget.items()},
            "accounts": accounts, "actions": actions}


def _account(a: dict[str, Any]) -> dict[str, Any]:
    return {"budget_events": a["budget_events"], "bad_when_spent": a["causes_when_spent"],
            "bad_in_month": a["bad"], "consumed_in_month": a["consumed"]}


def _freeze(month: simulate.Month, workflow: str, sli: str, account: dict[str, Any], at: float,
            people: list[str]) -> dict[str, Any]:
    return {"action": "freeze", "workflow": workflow, "sli": sli, "at_s": round(at, 1),
            "at": simulate.clock(month.config, at), "what": "changes to the workflow's prompts and models",
            **_account(account), "decided_by": "the policy, agreed in advance", "told": people,
            "lifts": "when the 30-day window's bad events fall back under every budget", "simulated": True}


def _rung_down(month: simulate.Month, workflow: str, manifest: dict[str, Any], account: dict[str, Any], lead: str,
               change: str, state_dir: Path) -> dict[str, Any]:
    """Step 4's rung switch, in a dry run: the override and the change line in state_dir, read back as a harness would."""
    at = account["spent_at"]
    moment = simulate.start_of(month.config) + timedelta(seconds=at)
    rung = int(manifest["rung"])
    reason = (f"the outcome SLI's budget of {account['budget_events']:g} events was spent "
              f"({account['causes_when_spent']}); error-budget policy, simulated month")
    line = oncall.lower_rung(manifest["workflow"], rung - 1, manifest_rung=rung, by=lead, change=change,
                             reason=reason, folder=state_dir, now=moment)
    plan = rungs.plan(manifest, state_dir / "rungs")
    return {"action": "rung down", "workflow": workflow, "sli": "outcome", "at_s": round(at, 1),
            "at": simulate.clock(month.config, at), **_account(account), "decided_by": f"the on-call lead ({lead})",
            "dry_run": True, "change_record": line,
            "plan": {"manifest_rung": plan.manifest_rung, "rung": plan.rung, "dropped": list(plan.dropped),
                     "note": plan.note},
            "simulated": True}
