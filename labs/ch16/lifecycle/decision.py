"""The decision at the end of the upgrade path (chapter 16, step 8, O-D14): promotion, a remap back, or a longer
canary, from the gate's verdict and the canary's SLIs.

The rule, in the order it is applied:

1. The gate. Chapter 15's live job ran the candidate on the workflow's golden set and set it against the accepted
   baseline check by check (labs/ch15/ci/gate.py). A check that lost more cases than its threshold allows is a
   regression, and one regression ends the path: remap back. The pins are not part of this rule, since a remap
   changes the alias map by design and the baseline holds no digest yet (chapter 15, step 7); they are listed
   beside the verdict for the review that accepts the new baseline.
2. Enough events. The candidate's arm must have served at least `min_runs` valid runs for the success SLI, or the
   canary is extended: nothing is decided on a handful of runs.
3. The SLIs, candidate against control over the runs each arm served (canary.py's touched runs). For each SLI
   with a target, the candidate's ratio must not be below the control's. Equal is enough: the canary asks whether
   the candidate is no worse on the same traffic, and the SLO's error budget, not the canary, judges the level.
   The latency SLI is read from the key the caller names: `latency` as measured, or `latency_without_loads`,
   the run's seconds less the model loads the one shared server paid for, which stands for the production shape
   where each model has replicas of its own (canary.py says how the loads are measured). The decision records
   which key it read.

The outcome is one of `promote`, `remap back`, and `extend`, with every number it read.
"""

from __future__ import annotations

from typing import Any

MIN_RUNS = 20
SLIS = ("success", "latency")
PROMOTE, BACK, EXTEND = "promote", "remap back", "extend"


def regressions(gate_rows: list[dict[str, Any]]) -> list[str]:
    return [row["check"] for row in gate_rows if row.get("verdict") == "regressed"]


def _value(arm: dict[str, Any], key: str) -> tuple[float | None, int, int]:
    ratio = (arm.get("runs_touched") or {}).get(key) or {}
    return ratio.get("value"), ratio.get("good", 0), ratio.get("valid", 0)


def decide(gate_rows: list[dict[str, Any]], by_arm: dict[str, dict[str, Any]], min_runs: int = MIN_RUNS,
           control: str = "control", candidate: str = "candidate", latency_key: str = "latency") -> dict[str, Any]:
    """The decision and what it rests on."""
    lost = regressions(gate_rows)
    gate = {"checks": len(gate_rows), "regressed": lost,
            "held": sum(1 for r in gate_rows if r.get("verdict") == "held"),
            "not_gated": sum(1 for r in gate_rows if r.get("verdict") == "not gated")}
    keys = {"success": "success", "latency": latency_key}
    compared = {}
    for sli in SLIS:
        c_value, c_good, c_valid = _value(by_arm.get(control, {}), keys[sli])
        k_value, k_good, k_valid = _value(by_arm.get(candidate, {}), keys[sli])
        compared[sli] = {"read": keys[sli], "control": {"good": c_good, "valid": c_valid, "value": c_value},
                         "candidate": {"good": k_good, "valid": k_valid, "value": k_value},
                         "candidate_not_below_control": (k_value is not None and c_value is not None and k_value >= c_value)}
    valid = compared["success"]["candidate"]["valid"]
    because: list[str] = []
    if lost:
        decision = BACK
        because.append(f"the gate: {', '.join(lost)} regressed past the threshold")
    elif valid < min_runs:
        decision = EXTEND
        because.append(f"the candidate served {valid} valid runs, under the {min_runs} the rule asks for")
    else:
        worse = [s for s in SLIS if not compared[s]["candidate_not_below_control"]]
        if worse:
            decision = BACK
            for s in worse:
                because.append(f"{s}: the candidate's {compared[s]['candidate']['value']} is below the control's "
                               f"{compared[s]['control']['value']}")
        else:
            decision = PROMOTE
            because.append("no check regressed in the gate")
            for s in SLIS:
                k, c = compared[s]["candidate"], compared[s]["control"]
                because.append(f"{s}: the candidate's {k['good']} of {k['valid']} is not below the control's "
                               f"{c['good']} of {c['valid']}")
    return {"decision": decision, "because": because, "rule": {"min_runs": min_runs, "slis": list(SLIS),
                                                               "latency_read_from": latency_key,
                                                               "counted_over": "the runs each arm served (touched)"},
            "gate": gate, "slis": compared}
