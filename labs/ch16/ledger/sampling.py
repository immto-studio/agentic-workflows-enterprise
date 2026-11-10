"""How far a month's cost, estimated from sampled traces, drifts from the cost lines' total.

Chapter 16, step 2 (companion #14, O-D5, O-D3). The cost lines are never sampled; traces may be. A month
of runs is drawn from each workflow's kept runs, with a fixed seed and as many runs as volumes.yaml's
month gives it, each run priced by its cost lines at chapter 6's design. The cost lines' total is the
month's truth. Then, over many seeds:

- Head sampling keeps each run's trace with probability p, decided when the run starts, and the estimate
  is the kept runs' cost over p. At p = 1 the estimate is the truth.
- Tail sampling keeps every failed and every over-budget run, and a share q of the rest. Scaled naively,
  by the kept share of runs, the estimate leans toward what the failed runs cost; weighted, each kept run
  counting 1/q or 1, it doesn't.

A failed run is one whose output failed its golden check: the kept runs record no span status, so the
stored verdict stands in for the error status a tail sampler reads. No kept run costs more than its
manifest's per_run_usd at these prices, so over budget adds nothing here, and the summary says so.

W3 and W4 kept no tokens, so their months aren't sampled. Every number comes from numpy's PCG64 with the
seeds below, which gives the same draws on every platform.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import costlines  # noqa: E402
import price  # noqa: E402
import registry  # noqa: E402

MONTH_SEED = 20261103
SAMPLE_SEED = 16
SEEDS = 1000
HEAD_RATES = (0.01, 0.10, 0.50, 1.0)
TAIL_SHARES = (0.01, 0.10)
SAMPLED = ("w1", "w2", "w5")


def population(runs: list[costlines.Run], table: dict[str, Any], workflow: str) -> dict[str, np.ndarray]:
    """Every kept run of the workflow on every model: its cost, and whether a tail sampler keeps it."""
    mine = [r for r in runs if r.workflow == workflow]
    budget = Decimal(str(registry.manifest(workflow)["budget"]["per_run_usd"]))
    costs = [price.run_cost(table, r) for r in mine]
    return {"cost": np.array([float(c) for c in costs]),
            "failed": np.array([r.passed is False for r in mine]),
            "over_budget": np.array([c > budget for c in costs])}


def draw_month(pop: dict[str, np.ndarray], n: int, index: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng([MONTH_SEED, index])
    picks = rng.integers(0, len(pop["cost"]), size=n)
    return {key: values[picks] for key, values in pop.items()}


def _summary(errors: np.ndarray) -> dict[str, float]:
    return {"mean": round(float(errors.mean()), 6), "std": round(float(errors.std()), 6),
            "p5": round(float(np.quantile(errors, 0.05)), 6), "p95": round(float(np.quantile(errors, 0.95)), 6),
            "max_abs": round(float(np.abs(errors).max()), 6)}


def head(month: dict[str, np.ndarray], rate: float, index: int) -> dict[str, Any]:
    costs = month["cost"]
    truth = costs.sum()
    errors, unknown, empty = np.empty(SEEDS), np.empty(SEEDS), 0
    for seed in range(SEEDS):
        keep = np.random.default_rng([SAMPLE_SEED, index, seed]).random(costs.size) < rate
        errors[seed] = costs[keep].sum() / rate / truth - 1
        unknown[seed] = 1 - keep.mean()
        empty += not keep.any()
    return {"rate": rate, "error": _summary(errors), "unknown_share": round(float(unknown.mean()), 6),
            "seeds_with_no_trace": empty}


def tail(month: dict[str, np.ndarray], q: float, index: int) -> dict[str, Any]:
    costs = month["cost"]
    always = month["failed"] | month["over_budget"]
    truth = costs.sum()
    naive, weighted, kept_share = np.empty(SEEDS), np.empty(SEEDS), np.empty(SEEDS)
    for seed in range(SEEDS):
        drawn = np.random.default_rng([SAMPLE_SEED, index, 1000 + seed]).random(costs.size) < q
        keep = always | drawn
        naive[seed] = costs[keep].sum() * costs.size / keep.sum() / truth - 1 if keep.any() else -1.0
        weighted[seed] = (costs[always].sum() + costs[drawn & ~always].sum() / q) / truth - 1
        kept_share[seed] = keep.mean()
    return {"share_of_the_rest": q, "kept_share": round(float(kept_share.mean()), 6),
            "unknown_share": round(float(1 - kept_share.mean()), 6),
            "naive": _summary(naive), "weighted": _summary(weighted)}


def experiment(runs: list[costlines.Run], table: dict[str, Any], runs_per_month: dict[str, float]) -> dict[str, Any]:
    out = {}
    for index, workflow in enumerate(SAMPLED):
        pop = population(runs, table, workflow)
        n = int(round(runs_per_month[workflow]))
        month = draw_month(pop, n, index)
        failed = month["failed"]
        out[workflow] = {
            "kept_runs_drawn_from": int(pop["cost"].size), "runs": n, "truth_usd": round(float(month["cost"].sum()), 8),
            "failed_share": round(float(failed.mean()), 6), "over_budget": int(month["over_budget"].sum()),
            "mean_cost_failed_usd": round(float(month["cost"][failed].mean()), 10) if failed.any() else None,
            "mean_cost_rest_usd": round(float(month["cost"][~failed].mean()), 10) if (~failed).any() else None,
            "head": [head(month, rate, index) for rate in HEAD_RATES],
            "tail": [tail(month, q, index) for q in TAIL_SHARES],
        }
    return {"month_seed": MONTH_SEED, "sample_seed": SAMPLE_SEED, "seeds": SEEDS, "workflows": out}
