"""The provisioned calculator: prices only from the dated table, the units with the fact sheet's words, each kind of
unit sized and priced as its cloud describes it, the break-even and the cost ratio agreeing, and the committed
calculator.json reproduced."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

import calculator as calc
import price

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-03" / "capacity"


@pytest.fixture(scope="module")
def units():
    return calc.load_units()


@pytest.fixture(scope="module")
def priced():
    return price.load()


def product(units, product_id):
    return next(p for p in units["products"] if p["id"] == product_id)


def profile(busy_in: float, busy_out: float, duty: str, runs: float = 60) -> calc.Profile:
    """A made-up workflow whose busy hour is `runs` runs of the given tokens a minute."""
    return calc.Profile(workflow="w-test", name="t", busy_hour_runs=runs, runs_per_month=0,
                        input_per_run=Decimal(str(busy_in)), output_per_run=Decimal(str(busy_out)),
                        duty_cycle=Decimal(duty), per_month_usd=Decimal(100), direct_month_usd=Decimal(1))


def test_every_term_takes_its_price_from_the_dated_table_and_this_step_added_none(units, priced):
    committed = {e["id"] for e in priced["committed"]}
    for p in units["products"]:
        for term in p["terms"]:
            assert term["price"] in committed, (p["id"], term)
    assert len(price.entries(priced)) == 49, "the table step 2 wrote, unchanged"


def test_each_product_carries_the_fact_sheets_words_and_a_comparator_or_a_reason(units, priced):
    deployments = {d["id"] for d in priced["deployments"]}
    assert [p["id"] for p in units["products"]] == ["bedrock-reserved-sonnet-4.5-cac1", "bedrock-pt-nova-lite-use1",
                                                    "azure-ptu-gpt-5.5-regional-canadaeast", "google-gsu-gemini-3.6-flash"]
    for p in units["products"]:
        assert p["facts"] and all(f["quote"] and str(f["section"]) and f["date"] for f in p["facts"]), p["id"]
        if p["on_demand"]:
            assert p["on_demand"] in deployments and p.get("on_demand_stand_in"), p["id"]
        else:
            assert "section 8.8" in p["on_demand_reason"], p["id"]


def test_the_reserved_tier_buys_its_minimum_input_and_output_apart(units, priced):
    p = product(units, "bedrock-reserved-sonnet-4.5-cac1")
    w = profile(6_000, 600, "0.25")  # 6,000 input and 600 output tokens a minute in the busy hour
    line = calc.compute(p, p["terms"][0], w, priced, Decimal(730))
    assert line.units_the_busy_hour_needs == 6 + 1 and line.units_bought == 100 + 10
    assert line.hourly_usd == pytest.approx(100 * 0.198 + 10 * 0.99)
    assert line.busy_hour_fills == pytest.approx(0.06), "the input side fills first: 6,000 of 100,000"
    assert line.utilization == pytest.approx(0.25 * 0.06)
    assert line.break_even_utilization is None and "on-demand rate" in line.lacks
    three = calc.compute(p, p["terms"][1], w, priced, Decimal(730))
    assert three.hourly_usd == pytest.approx(0.9 * line.hourly_usd), "three months cost nine tenths of one"


def test_a_regional_ptu_deployment_rounds_up_to_fifty(units, priced):
    p = product(units, "azure-ptu-gpt-5.5-regional-canadaeast")
    w = profile(6_000, 1_000, "0.5")  # normalized: 6,000 + 6 x 1,000 = 12,000 a minute, ten PTUs' worth
    hourly, monthly, yearly = (calc.compute(p, t, w, priced, Decimal(730)) for t in p["terms"])
    assert hourly.units_the_busy_hour_needs == 10 and hourly.units_bought == 50
    assert hourly.busy_hour_fills == pytest.approx(0.2) and hourly.utilization == pytest.approx(0.1)
    assert hourly.hourly_usd == pytest.approx(50 * 2.36)
    assert monthly.hourly_usd == pytest.approx(50 * 338 / 730) and yearly.hourly_usd == pytest.approx(50 * 3444 / 8760)
    big = calc.compute(p, p["terms"][0], profile(73_000, 0, "1"), priced, Decimal(730))
    assert big.units_the_busy_hour_needs == 61 and big.units_bought == 100, "past the minimum, in steps of fifty"


def test_gsus_burn_output_at_five_times_input(units, priced):
    p = product(units, "google-gsu-gemini-3.6-flash")
    w = profile(30_000, 3_000, "1")  # 30,000 + 5 x 3,000 = 45,000 a minute; one GSU carries 675 x 60 = 40,500
    line = calc.compute(p, p["terms"][1], w, priced, Decimal(730))
    assert line.units_the_busy_hour_needs == 2 and line.units_bought == 2
    assert line.busy_hour_fills == pytest.approx(45_000 / 81_000)
    assert line.hourly_usd == pytest.approx(2 * 4.068493151) and line.endpoint == "non-global"


def test_a_model_unit_of_unknown_size_still_gives_the_volume_it_must_carry(units, priced):
    p = product(units, "bedrock-pt-nova-lite-use1")
    w = profile(6_000, 1_000, "0.3")
    line = calc.compute(p, p["terms"][2], w, priced, Decimal(730))
    assert line.units_bought == 1 and line.utilization is None and "tokens a minute one unit carries" in line.lacks
    busy_hour = 60 * (6_000 * 0.06 + 1_000 * 0.24) / 1e6
    assert line.busy_hours_to_break_even == pytest.approx(30.25 / busy_hour, rel=1e-5)
    assert line.on_demand_over_committed == pytest.approx(0.3 * busy_hour / 30.25, rel=1e-5)
    assert line.on_demand == "nova-lite-us" and "us-east-2" in line.on_demand_stand_in


@pytest.mark.parametrize("duty", ["0.05", "0.3", "0.9", "1"])
def test_the_commitment_wins_exactly_when_utilization_passes_break_even(units, priced, duty):
    for product_id in ("bedrock-reserved-sonnet-4.5-cac1", "azure-ptu-gpt-5.5-regional-canadaeast",
                       "google-gsu-gemini-3.6-flash"):
        p = product(units, product_id)
        line = calc.compute(p, p["terms"][0], profile(400_000, 40_000, duty), priced, Decimal(730), given=(3.0, 15.0))
        assert line.lacks is None and line.on_demand == "given"
        wins = line.on_demand_over_committed > 1
        assert wins == (line.utilization > line.break_even_utilization), (product_id, duty, line)
        # both are rounded to six significant digits, so near u = 1 the difference is good to a millionth
        assert line.discount_needed == pytest.approx(1 - line.utilization, abs=1e-6)


def test_the_profiles_come_from_the_ledger_and_the_stated_busy_hours():
    ledger = json.loads((LAB / "results" / "2026-11-03" / "ledger.json").read_text(encoding="utf-8"))
    profiles = calc.load_profiles()
    w2, w3 = profiles["w2"], profiles["w3"]
    p2, p3 = ledger["month"]["profiles"]["w2"], ledger["month"]["profiles"]["w3"]
    assert float(w2.busy_input_tpm) == pytest.approx(200 * p2["input"] / 60)
    assert float(w3.busy_input_tpm) == pytest.approx(10 * (p3["input"] - p3["restricted_input"]) / 60), \
        "W3's Restricted calls go to the self-hosted alias, never to a commitment"
    assert float(w2.duty_cycle) == pytest.approx(43029.93 / (730 * 200), rel=1e-6)
    assert float(w3.duty_cycle) == pytest.approx(300 / (730 * 10))


def test_the_committed_calculator_json_is_what_the_calculator_writes():
    committed = json.loads((RESULTS / "calculator.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(calc.report())) == committed
    assert len(committed["lines"]) == 2 * (2 + 3 + 3 + 8)


def test_the_cli_takes_the_on_demand_rate_the_table_lacks(capsys):
    assert calc.main(["--workflow", "w2", "--product", "azure-ptu-gpt-5.5-regional-canadaeast",
                      "--on-demand-input", "5", "--on-demand-output", "30"]) == 0
    lines = json.loads(capsys.readouterr().out)
    assert len(lines) == 3 and all(line["break_even_utilization"] is not None for line in lines)
    with pytest.raises(SystemExit):
        calc.main(["--workflow", "w2", "--on-demand-input", "5"])
