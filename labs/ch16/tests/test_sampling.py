"""The sampling drift: exact at full sampling, unbiased by head sampling, biased by naive scaling of a
tail-sampled set and unbiased when weighted; on synthetic months, so each property is visible alone."""

from __future__ import annotations

import numpy as np
import pytest

import sampling


def synthetic(n: int = 5000, failed_share: float = 0.2, failed_costs_more: float = 3.0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    failed = rng.random(n) < failed_share
    cost = rng.lognormal(mean=-8.5, sigma=0.5, size=n) * np.where(failed, failed_costs_more, 1.0)
    return {"cost": cost, "failed": failed, "over_budget": np.zeros(n, dtype=bool)}


def test_full_sampling_gives_the_cost_lines_total_exactly() -> None:
    result = sampling.head(synthetic(), 1.0, 0)
    assert result["error"] == {"mean": 0.0, "std": 0.0, "p5": 0.0, "p95": 0.0, "max_abs": 0.0}
    assert result["unknown_share"] == 0 and result["seeds_with_no_trace"] == 0


def test_head_sampling_is_unbiased_and_its_unknown_share_is_the_rest() -> None:
    month = synthetic()
    for rate in (0.01, 0.1, 0.5):
        result = sampling.head(month, rate, 0)
        assert abs(result["error"]["mean"]) < 3 * result["error"]["std"] / np.sqrt(sampling.SEEDS), rate
        assert result["unknown_share"] == pytest.approx(1 - rate, abs=0.01)
    assert sampling.head(month, 0.01, 0)["error"]["std"] > sampling.head(month, 0.1, 0)["error"]["std"]


def test_naive_scaling_of_a_tail_sampled_set_is_biased_and_weighting_is_not() -> None:
    month = synthetic(failed_costs_more=3.0)
    for q in sampling.TAIL_SHARES:
        result = sampling.tail(month, q, 0)
        assert result["naive"]["mean"] > 0.2, q  # the failed runs cost more, and naive scaling spreads them
        assert abs(result["weighted"]["mean"]) < 3 * result["weighted"]["std"] / np.sqrt(sampling.SEEDS), q
    same = sampling.tail(synthetic(failed_costs_more=1.0), 0.1, 0)
    assert abs(same["naive"]["mean"]) < 0.05  # when failed runs cost what the rest do, naive is near right


def test_over_budget_runs_are_always_kept() -> None:
    month = synthetic(failed_share=0.0)
    month["over_budget"][:10] = True
    month["cost"][:10] *= 50
    result = sampling.tail(month, 0.01, 0)
    assert result["kept_share"] >= 10 / month["cost"].size
    assert abs(result["weighted"]["mean"]) < 0.05


def test_the_experiment_on_the_kept_runs_is_reproducible(runs, table) -> None:
    per_month = {"w1": 600, "w2": 4000, "w5": 34}
    first = sampling.experiment(runs, table, per_month)
    assert first == sampling.experiment(runs, table, per_month)
    w5 = first["workflows"]["w5"]
    assert w5["runs"] == 34 and w5["over_budget"] == 0
    assert next(h for h in w5["head"] if h["rate"] == 1.0)["error"]["max_abs"] == 0.0
    assert next(h for h in w5["head"] if h["rate"] == 0.01)["seeds_with_no_trace"] > 500  # 34 nights at 1 percent
