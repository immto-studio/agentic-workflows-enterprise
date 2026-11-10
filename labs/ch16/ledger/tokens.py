"""How the token counts differ across models on the same cases: W1's golden set on three models.

Chapter 16, step 2 (companion #14, O-D5; book D-033, companion #55 and #100). The kept runs counted
tokens on gpt-oss-20b and Gemma 4 12B, and the ledger prices them at Nova Lite's price, so every priced
estimate carries the question of how Nova Lite would have counted the same work. W1's golden set ran on
all three. This compares them on the cases all three answered:

- A case is compared when each model's run of it ended in the model's own answer: not the harness's
  refusal when the step budget ran out, and not a failed search (W1's harness constants).
- A case is left out when any run of it sent a call to larkspur-chat-restricted. In the Nova Lite run
  that alias was gpt-oss-20b (the run's gateway_models), so those calls are not Nova Lite's count.
- Input and output are compared apart, per case (the sum over the case's calls) and on the first call,
  whose prompt is the same text on every model (the system prompt, the tools, and the question), so its
  ratio is the tokenizer and the chat template alone.

The ratios are the model on the left's count over the model on the right's; the median of the per-case
ratios, and the ratio of the totals.
"""

from __future__ import annotations

import statistics
import sys
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import costlines  # noqa: E402  (puts chapter 15's layers on sys.path)
import registry  # noqa: E402

MODELS = ("gpt-oss-20b", "gemma4-12b", "nova-lite")
PAIRS = (("nova-lite", "gpt-oss-20b"), ("nova-lite", "gemma4-12b"), ("gemma4-12b", "gpt-oss-20b"))


def _ratio(a: float, b: float) -> float | None:
    return None if not b else round(float(Decimal(a) / Decimal(b)), 4)


def harness_endings() -> set[str]:
    """W1's answers the harness writes in the model's place."""
    with registry.loaded("w1") as mods:
        answer = mods.answer
        return {answer.REFUSAL, answer.SEARCH_FAILED, answer.BUDGET_EXHAUSTED}


def answers() -> dict[str, dict[str, str]]:
    """W1's final answer per model and case, from the kept runs."""
    out: dict[str, dict[str, str]] = {}
    for kept in registry.kept_runs("w1"):
        out[kept.model] = {case: o["answer"] for case, o in registry.outputs(kept).items()}
    return out


def compare(runs: Iterable[costlines.Run]) -> dict[str, Any]:
    w1 = {}
    for run in runs:
        if run.workflow == "w1":
            w1.setdefault(run.model, {})[run.case] = run
    if set(w1) != set(MODELS):
        raise ValueError(f"W1's kept runs are on {sorted(w1)}, not {list(MODELS)}")
    endings = harness_endings()
    finals = answers()
    cases = sorted(set.intersection(*(set(w1[m]) for m in MODELS)))
    restricted = [c for c in cases
                  if any(line.alias == costlines.RESTRICTED_ALIAS for m in MODELS for line in w1[m][c].lines)]
    unanswered = {m: [c for c in cases if finals[m][c] in endings] for m in MODELS}
    left_out = set(restricted) | {c for cs in unanswered.values() for c in cs}
    compared = [c for c in cases if c not in left_out]

    per_case = []
    for c in compared:
        row: dict[str, Any] = {"case": c}
        for m in MODELS:
            run = w1[m][c]
            tin, tout = run.tokens()
            row[m] = {"calls": run.model_calls, "input": tin, "output": tout,
                      "first_input": run.lines[0].input_tokens}
        per_case.append(row)

    def summary(left: str, right: str, field: str) -> dict[str, Any]:
        ratios = [_ratio(r[left][field], r[right][field]) for r in per_case]
        ratios = [x for x in ratios if x is not None]
        return {"median": round(statistics.median(ratios), 4) if ratios else None,
                "min": min(ratios, default=None), "max": max(ratios, default=None),
                "of_totals": _ratio(sum(r[left][field] for r in per_case), sum(r[right][field] for r in per_case))}

    ratios = {f"{left}/{right}": {field: summary(left, right, field) for field in ("input", "output", "first_input")}
              for left, right in PAIRS}
    same_calls = [r["case"] for r in per_case if len({r[m]["calls"] for m in MODELS}) == 1]
    totals = {m: {"input": sum(r[m]["input"] for r in per_case), "output": sum(r[m]["output"] for r in per_case),
                  "calls": sum(r[m]["calls"] for r in per_case)} for m in MODELS}
    return {"cases": len(cases), "compared": len(compared), "left_out_restricted": restricted,
            "left_out_unanswered": {m: cs for m, cs in unanswered.items() if cs}, "same_number_of_calls": len(same_calls),
            "totals": totals, "ratios": ratios, "per_case": per_case}
