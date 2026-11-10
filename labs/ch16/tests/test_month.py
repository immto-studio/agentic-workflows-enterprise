"""The month: a source for every volume, the month's cost against per_month_usd, and the allocation, whose
parts add up to the whole on every reading of the restricted alias's tenants."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

import month as months
import registry

LAB_ASSUMPTION = "lab assumption, not in the book"
BOOK_LINE = re.compile(r"^ch\d\d:\d+$")


def _sourced(v: dict) -> None:
    if v["source"] == LAB_ASSUMPTION:
        assert v.get("basis"), v
    else:
        assert BOOK_LINE.match(v["source"]) and v.get("words"), v


def test_every_volume_has_a_source_from_the_book_or_says_it_is_an_assumption() -> None:
    volumes = months.load_volumes()
    assert set(volumes["workflows"]) == set(months.WORKFLOWS)
    for w, v in volumes["workflows"].items():
        for part in (v["parts"].values() if "parts" in v else [v]):
            _sourced(part)
    for w in ("w1", "w3"):
        assert "searched" in volumes["workflows"][w]  # chapters 1 to 14 were searched before assuming
    for w, proxy in volumes["tokens_proxy"].items():
        assert proxy["source"] == LAB_ASSUMPTION and proxy["basis"]
    for item in volumes["platform"]["fixed"]:
        assert item["source"] == LAB_ASSUMPTION and item["basis"] or BOOK_LINE.match(item["source"]) \
            or item["source"].startswith("labs/"), item


@pytest.fixture(scope="module")
def month(runs, table) -> dict:
    return months.month(runs, table, months.load_volumes(), {"input": 1.3638, "output": 0.5381})


def test_the_month(month) -> None:
    rows = {r["workflow"]: r for r in month["rows"]}
    assert rows["w2"]["tokens_per_month"] == 100_000_000
    assert (rows["w1"]["runs_per_month"], rows["w3"]["runs_per_month"], rows["w4"]["runs_per_month"],
            rows["w5"]["runs_per_month"]) == (6000, 300, 200, 34)
    for w, r in rows.items():
        budget = registry.manifest(w)["budget"]["per_month_usd"]
        assert r["per_month_usd"] == budget
        assert r["direct_pct_of_month"] == pytest.approx(r["direct_usd"] / budget * 100, abs=1e-6)
        lo, hi = r["direct_pct_range_over_kept_runs"]
        assert lo <= r["direct_pct_of_month"] + 1e-9 and r["direct_pct_of_month"] <= hi + 1e-9
    assert rows["w3"]["basis"] == "measured on the 24 of 48 runs with tokens"  # step 3b's runs alone kept tokens
    assert rows["w4"]["basis"] == "measured on the 8 of 32 runs with tokens"
    assert {w for w, r in rows.items() if r["basis"] == "measured"} == {"w1", "w2", "w5"}
    assert rows["w2"]["restricted_tokens_per_month"] == 0 and rows["w3"]["restricted_tokens_per_month"] > 0


def test_step_2_s_month_comes_back_from_chapter_15_s_runs_alone(runs, table) -> None:
    """Without step 3b's runs the ledger is step 2's: W3 and W4 at their proxies, the month as step 2 printed it."""
    import costlines

    before = months.month([r for r in runs if not costlines.is_traced(r)], table, months.load_volumes(),
                          {"input": 1.3638, "output": 0.5381})
    rows = {r["workflow"]: r for r in before["rows"]}
    assert rows["w3"]["basis"] == "proxy: W2's tokens per call" and rows["w4"]["basis"] == "proxy: W5's tokens per call"
    assert (rows["w2"]["runs_per_month"], rows["w3"]["tokens_per_month"], rows["w4"]["tokens_per_month"]) == (
        42160.61, 1_918_095, 344_209)  # step 2's ledger.json, committed in #107
    assert (rows["w3"]["direct_pct_of_month"], rows["w4"]["direct_pct_of_month"]) == (0.032105, 0.031771)


def test_the_gpu_hours_split_into_tenants_and_idle(month, table) -> None:
    gpu = months.gpu(month, table, months.load_volumes())
    assert gpu["usd"] == pytest.approx(2 * 730 * 1.861)
    assert set(gpu["readings"]) == {"chapter 9", "manifests and chapter 10"}
    for name, r in gpu["readings"].items():
        assert r["used_usd"] + r["idle_usd"] == pytest.approx(gpu["usd"])
        assert sum(s["usd"] for s in r["split"].values()) == pytest.approx(r["used_usd"], abs=1e-6)
        assert sum(s["without_idle_line_usd"] for s in r["split"].values()) == pytest.approx(gpu["usd"], abs=1e-6)
        assert r["split"]["w2"]["usd"] == 0  # W2 sent the alias nothing
        assert r["idle_share"] > 0.999
    assert gpu["readings"]["chapter 9"]["tenants"] == ["w2", "w3"]
    assert gpu["readings"]["manifests and chapter 10"]["tenants"] == ["w1", "w2", "w3"]


def test_the_fixed_costs_add_up_and_the_parameters_stay_out(month, table) -> None:
    fixed = months.fixed(month, table, months.load_volumes())
    priced = [line for line in fixed["lines"] if not line["parameter"]]
    assert fixed["priced_usd"] == pytest.approx(sum(line["usd"] for line in priced))
    assert fixed["parameters"] == ["chapter 7's Private Service Connect endpoint", "chapter 8's private endpoints",
                                   "LiteLLM's enterprise license", "Langfuse's enterprise features"]
    assert all(line["usd"] is None for line in fixed["lines"] if line["parameter"])
    endpoints = next(line for line in fixed["lines"] if line["item"] == "chapter 6's interface endpoints")
    assert Decimal(str(endpoints["usd"])) == Decimal("128.48")  # the cost sheet's own idle month
    for basis, split in fixed["splits"].items():
        assert sum(s["usd"] for s in split.values()) == pytest.approx(fixed["priced_usd"], abs=1e-6), basis
        assert sum(s["share"] for s in split.values()) == pytest.approx(1.0)
