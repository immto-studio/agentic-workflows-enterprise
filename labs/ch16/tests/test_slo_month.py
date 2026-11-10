"""Step 6's simulated month: marked simulated, seeded and reproducible, drawn from the kept runs at the ledger's
volumes, with each injected event shaped as month.yaml says."""

from __future__ import annotations

import copy
from datetime import timedelta
import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

import simulate
import slis

LAB = Path(__file__).resolve().parents[1]
DAY, HOUR = 86400.0, 3600.0


def inside(month, name: str, t: float) -> bool:
    begin, end = month.shapes["windows"][name]
    return begin <= t < end


def started(e: slis.RunEvent) -> float:
    return e.at - (e.seconds or 0.0)


def test_the_month_says_it_is_simulated_and_refuses_to_build_otherwise(kept_slo):
    config = simulate.load()
    assert config["simulated"] is True
    assert "SIMULATED" in simulate.MONTH.read_text(encoding="utf-8").splitlines()[0]
    with pytest.raises(ValueError, match="simulated"):
        simulate.build({**config, "simulated": False}, kept=kept_slo)


def test_the_month_is_seeded_and_the_same_every_time(month, kept_slo):
    again = simulate.build(kept=kept_slo)
    assert again.events == month.events and again.probes == month.probes and again.records == month.records
    other = copy.deepcopy(simulate.load())
    other["seed"] += 1
    assert simulate.build(other, kept=kept_slo).events != month.events


def test_each_workflows_runs_come_at_the_ledgers_volume(month):
    ledger = json.loads(simulate.LEDGER_MONTH.read_text(encoding="utf-8"))["month"]
    hours = month.config["days"] * 24
    for row in ledger["rows"]:
        if row["workflow"] == "w5":
            continue
        expected = row["runs_per_month"] / ledger["month_hours"] * hours
        runs = sum(1 for e in month.real(row["workflow"]) if e.unit == "run" and started(e) >= 0)
        assert abs(runs - expected) <= 4 * expected ** 0.5, row["workflow"]  # four Poisson deviations
    nights = [e for e in month.real("w5") if e.unit == "run" and e.reason == "schedule" and started(e) >= 0]
    assert len(nights) == month.config["days"]
    assert {round(started(e) % DAY) for e in nights} == {2 * HOUR}  # 02:00 ET (ch14:13)


def test_every_run_is_one_of_the_kept_runs_month_yaml_names(month):
    config = month.config
    allowed = {w: set(config["pools"]["baseline"][w]) for w in slis.WORKFLOWS}
    for item in config["injected"]:
        for w, pool in (item.get("pools") or {}).items():
            allowed[w] |= set(pool)
    for e in month.events:
        if e.unit != "run":
            continue
        model, rest = e.source.split(" ", 1)
        assert model == config["pools"]["reference_model"]
        assert rest.rsplit(" ", 1)[0] in allowed[e.workflow], e.source


def test_the_shapes_come_from_step_5s_files():
    assert simulate.outage_timeout_s() == 5.0  # capacity/litellm.outage-canada.yaml's deployment timeout
    assert simulate.outage_cooldown_s() == 30.0  # and its router's cooldown_time, the retry-after its 429 names
    shape = simulate.throttle_shape()
    assert (shape["requests"], shape["refused_at_first_attempt"], shape["served"], shape["never"]) == (80, 34, 75, 5)
    assert shape["p_never"] == 5 / 80 and shape["p_waited"] == 29 / 80
    assert simulate.w3_time_budget_s() == 120.0
    assert simulate.w5_opened() == 1


def test_the_outage_costs_every_managed_call_its_timeout_and_w4s_probe_its_answer(month):
    hit = [e for e in month.events if e.injected == "provider-outage"]
    assert hit and {e.workflow for e in hit} <= {"w1", "w2", "w3"}
    assert all(e.end in slis.GOOD for e in hit)  # the fallback in Canada answered (step 5b)
    fallbacks = [r for r in month.records if r["injected"] == "provider-outage" and r["kind"] == "fallback"]
    assert {r["served_by"] for r in fallbacks} == {"larkspur-chat-restricted"}
    # with this seed no W4 or W5 run starts inside the 45 minutes, which month.yaml and the README say
    assert not [e for e in month.events if e.workflow in ("w4", "w5") and e.unit == "run"
                and inside(month, "provider-outage", started(e))]


def test_a_w4_run_in_the_outage_waits_the_timeout_and_one_cooldown_and_keeps_its_pack(month):
    """month.yaml's shape for a workflow with no fallback hop, driven on a run of its own since the month has none."""
    import random
    builder = simulate.Builder(month.config, simulate.Month(month.config), 1)
    begin = month.shapes["windows"]["provider-outage"][0]
    draw = simulate.Draw("w4", "gpt-oss-20b 2026-11-02", "w4-01", "proposal", 8.0, 1, 0, 7.0)
    event = builder.run(random.Random(1), draw, begin + 60.0, "w4:test")
    assert (event.end, event.injected, event.seconds) == ("proposal", "provider-outage", 8.0 + 5.0 + 30.0)
    record = builder.month.records[-1]
    assert record["kind"] == "failed" and "one wait of the cooldown's retry-after" in record["why"]
    probe = builder.run(random.Random(1), draw, begin + 60.0, "probe:w4:test", probe=True)
    assert (probe.end, probe.seconds) == ("error", 7.0 + 5.0)  # the probe waits out no 429
    w4 = [p for p in month.probes if p.workflow == "w4" and inside(month, "provider-outage", started(p))]
    assert [p.end for p in w4] == ["error"]  # no fallback hop for W4's alias
    w1 = [p for p in month.probes if p.workflow == "w1" and inside(month, "provider-outage", started(p))]
    assert [p.end for p in w1] == ["answer"]


def test_the_throttled_hour_fails_calls_and_records_the_429s(month):
    records = [r for r in month.records if r["injected"] == "throttled-hour"]
    assert {r["kind"] for r in records} == {"provider_429"}
    assert len({r["workflow"] for r in records}) >= 2
    for e in month.events:
        if e.injected == "throttled-hour" and e.end in slis.BAD:
            assert e.end == ("unavailable" if e.workflow == "w3" else "error")
            assert e.workflow not in ("w4", "w5")  # their seams write the stub sentence


def test_the_weekend_without_the_self_hosted_path_fails_restricted_runs_and_leaves_the_probes_green(month):
    hit = [e for e in month.events if e.injected == "self-hosted-down"]
    assert {e.workflow for e in hit} == {"w1", "w3"} and all(e.restricted for e in hit)
    assert Counter((e.workflow, e.end) for e in hit) == Counter({("w1", "error"): 53, ("w3", "unavailable"): 5})
    probes = [p for p in month.probes if inside(month, "self-hosted-down", started(p))]
    assert len(probes) == 3 * 48 and {p.end for p in probes} == {"answer"}


def test_the_day_of_refused_records_fails_every_w4_run_and_not_its_probe(month):
    runs = [e for e in month.real("w4") if e.unit == "run" and inside(month, "w4-records-refused", started(e))]
    assert runs and {e.end for e in runs} == {"error"} and {e.injected for e in runs} == {"w4-records-refused"}
    probes = [p for p in month.probes if p.workflow == "w4" and inside(month, "w4-records-refused", started(p))]
    assert len(probes) == 24 and {p.end for p in probes} == {"answer"}


def test_the_regression_draws_w2_and_w5_from_their_earlier_kept_runs(month):
    begin = month.shapes["windows"]["model-regression"][0]
    w2_after = [e for e in month.real("w2") if started(e) >= begin]
    assert {e.source.split(" ", 1)[1].rsplit(" ", 1)[0] for e in w2_after} == {"2026-11-02 run1"}
    assert {e.injected for e in w2_after} == {"model-regression"}
    w2_before = [e for e in month.real("w2") if 0 <= started(e) < begin]
    assert not any(e.end == "budget_stop" for e in w2_before)  # none of the baseline pool's runs stopped at its budget
    assert sum(1 for e in w2_after if e.end == "budget_stop") / len(w2_after) == pytest.approx(5 / 20, abs=0.02)


def test_no_run_outside_a_window_carries_an_injected_event(month):
    for e in month.events + month.probes:
        if e.injected and e.unit == "run":
            assert inside(month, e.injected, started(e)), (e.run_id, e.injected)


def test_decisions_follow_month_yamls_assumptions(month):
    w3 = [e for e in month.real("w3") if e.end == "proposal" and started(e) >= 0]
    assert all(e.decided_at is None or e.decided_at - e.at <= 30 * 60 for e in w3)
    w4 = [e for e in month.real("w4") if e.decision]
    for e in w4:
        moment = simulate.start_of(month.config) + timedelta(seconds=e.decided_at)
        assert (moment.weekday(), moment.hour, moment.minute) == (3, 14, 0)  # Thursday 14:00 ET (ch13:18)
    decisions = yaml.safe_load(simulate.MONTH.read_text(encoding="utf-8"))["decisions"]
    assert "assumption" in decisions["basis"]


def test_the_expected_events_are_the_pools_shares_at_the_ledgers_volume(month):
    exp = month.expected
    assert exp["w5"]["success"] == pytest.approx(30 + 4 / 730 * 720)
    assert exp["w5"]["outcome"] == pytest.approx(30 * 1 * 0.6)
    assert exp["w1"]["success"] == pytest.approx(6000 / 730 * 720)
    assert exp["w3"]["latency"] < exp["w3"]["success"]
