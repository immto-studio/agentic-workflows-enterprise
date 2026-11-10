"""The cost crossover arithmetic, on a small hand-checked sheet and on the dated one."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cost"))

import crossover as cx  # noqa: E402

SHEET = {
    "hours_per_month": 100,
    "input_per_output": 3.0,
    "hosted": {"h": {"input_per_million": 1.0, "output_per_million": 5.0}},
    "gpu": {"g": {"per_hour": 2.0}},
}


def test_blended_price_weights_by_the_mix() -> None:
    assert cx.blended_price(SHEET["hosted"]["h"], 3.0) == pytest.approx(2.0)  # (3x1 + 5) / 4


def test_crossover_is_gpu_month_over_blended_price() -> None:
    r = cx.crossover(SHEET, "h", "g", replicas=2)
    assert r.gpu_cost_per_month == pytest.approx(400.0)                 # 2 x 2.0 x 100 h
    assert r.crossover_tokens_per_month == pytest.approx(200e6)        # 400 / 2.0 per million
    assert r.sustained_tokens_per_second == pytest.approx(200e6 / 360_000)
    assert r.sustained_output_tokens_per_second == pytest.approx(r.sustained_tokens_per_second / 4)


def test_overhead_moves_the_crossover_out_and_the_ratio_compares_bills() -> None:
    r = cx.crossover(SHEET, "h", "g", replicas=2, overhead_per_month=400.0, monthly_tokens=10e6)
    assert r.crossover_tokens_per_month == pytest.approx(400e6)
    assert r.hosted_cost_per_month == pytest.approx(20.0)
    assert r.self_hosted_over_hosted == pytest.approx(40.0)


def test_the_dated_sheet_loads_and_gives_the_chapter_its_numbers() -> None:
    sheet = cx.load_sheet()
    assert sheet["as_of"].isoformat() == "2026-10-28"
    r = cx.crossover(sheet, "bedrock-gpt-oss-120b-standard", "aws-p5.4xlarge-h100-on-demand",
                     replicas=2, monthly_tokens=100e6)
    # The relative statements the chapter makes, so a price change shows up here first.
    assert 40e9 < r.crossover_tokens_per_month < 50e9
    assert 15_000 < r.sustained_tokens_per_second < 19_000
    assert 400 < r.self_hosted_over_hosted < 500
