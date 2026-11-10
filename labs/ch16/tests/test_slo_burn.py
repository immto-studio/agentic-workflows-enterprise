"""Step 6's alerts: the burn rate as the fact sheet defines it, the workbook's low-traffic numbers, episodes, the
designs, W5's nights and the platform's 429s."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import burn
import slis

LAB = Path(__file__).resolve().parents[1]
ALERTS = yaml.safe_load((LAB / "slo" / "alerts.yaml").read_text(encoding="utf-8"))
HOUR = 3600.0
RULES = {r["name"]: r for r in ALERTS["burn_rate"]["rules"]}
LONG_ONLY = {**RULES["fast-burn-1h"], "short_window_hours": None}  # the hour's rule without its five minutes


def runs(spec: list[tuple[float, str]], workflow: str = "w2", **more) -> list[slis.RunEvent]:
    return [slis.RunEvent(workflow, f"{workflow}-{i}", end, 1.0, at=at, **more) for i, (at, end) in enumerate(spec)]


def test_the_rules_are_the_workbooks_table_as_the_fact_sheet_quotes_it():
    assert [(r["burn_rate"], r["long_window_hours"], r["budget_share"], r["action"]) for r in ALERTS["burn_rate"]["rules"]] \
        == [(14.4, 1, 0.02, "page"), (6, 6, 0.05, "page"), (1, 72, 0.10, "ticket")]
    # the budget share each rule spends is its burn rate times its window over the 30-day window
    for r in ALERTS["burn_rate"]["rules"]:
        assert r["burn_rate"] * r["long_window_hours"] / (30 * 24) == pytest.approx(r["budget_share"], rel=0.01)
    # the same table's short windows (fact sheet 9.4): 5 minutes, 30 minutes and 6 hours, a twelfth of each long window
    assert [r["short_window_hours"] * HOUR for r in ALERTS["burn_rate"]["rules"]] == [300.0, 1800.0, 21600.0]
    for r in ALERTS["burn_rate"]["rules"]:
        assert r["short_window_hours"] == pytest.approx(r["long_window_hours"] / 12)
    assert ALERTS["burn_rate"]["page_slis"] == ["success", "latency"]


def test_the_burn_rate_is_the_bad_share_over_one_minus_the_target():
    events = runs([((i + 1) * 60.0, "error" if i < 3 else "answer") for i in range(60)])
    stream = burn.Stream.of("w2", "success", 0.99, events)
    assert stream.burn(HOUR, 1) == pytest.approx((3 / 60) / 0.01)  # the window (end - 1 h, end]
    assert stream.burn(60.0, 1) == pytest.approx(100.0)  # the first run alone, and it failed
    assert burn.Stream.of("w2", "success", 0.99, []).burn(HOUR, 1) == 0.0


def test_the_workbooks_ten_requests_an_hour():
    """Fact sheet 8.9: at 10 requests an hour and a 99.9% SLO a single failure "consumed 13.9% of the 30-day error
    budget" and the month allows "only seven failed requests". By the burn-rate definition the sheet quotes, the hour's
    10 percent over 0.1 percent is a burn of 100; the workbook's sentence says 1,000x, which the fact check should read."""
    hour = runs([(i * 360.0 + 1, "error" if i == 0 else "answer") for i in range(10)])
    assert burn.Stream.of("w2", "success", 0.999, hour).burn(HOUR, 1) == pytest.approx(100.0)
    budget = (1 - 0.999) * 10 * 24 * 30
    assert budget == pytest.approx(7.2) and 1 / budget == pytest.approx(0.139, abs=0.001)


def test_a_low_target_leaves_the_page_unable_to_fire():
    """Fact sheet 8.9, at 90 percent: "a 100% outage consumes only 1.4% of the budget in that hour, this alert could
    never fire". W3's measured 83 percent would be worse; its 95 percent lets a total outage page."""
    outage = runs([((i + 1) * 60.0, "error") for i in range(60)])
    at_90 = burn.Stream.of("w3", "success", 0.90, outage).burn(HOUR, 1)
    assert at_90 == pytest.approx(10.0) and at_90 < 14.4
    assert (1 / (30 * 24)) / 0.10 == pytest.approx(0.0139, abs=0.0001)
    # at the kept runs' 40 of 48 a total outage burns at 6: the 1-hour page could never fire, and the 6-hour one
    # only on six hours of nothing but failures
    assert 1 / (1 - 40 / 48) == pytest.approx(6.0) and 1 / (1 - 40 / 48) < 14.4
    at_95 = burn.Stream.of("w3", "success", 0.95, outage).burn(HOUR, 1)
    assert at_95 == pytest.approx(20.0) and at_95 >= 14.4


def test_an_episode_runs_while_the_rule_holds_and_continues_inside_its_window():
    events = runs([(10 * HOUR + i, "error") for i in range(3)] + [(t * 60.0, "answer") for t in range(0, 30 * 60, 5)])
    stream = burn.Stream.of("w2", "success", 0.995, events)
    found = burn.episodes(stream, LONG_ONLY, "own-traffic", 0, 24 * HOUR, 300)
    # the evaluation at 10:00 holds the first error; the one at 11:05 is the first whose hour holds none
    assert len(found) == 1 and (found[0].start, found[0].end) == (10 * HOUR, 11 * HOUR + 300)
    again = events + runs([(11 * HOUR + 1200 + i, "error") for i in range(3)], workflow="w2")
    again = [slis.RunEvent("w2", f"e{i}", e.end, 1.0, at=e.at) for i, e in enumerate(again)]
    merged = burn.episodes(burn.Stream.of("w2", "success", 0.995, again), LONG_ONLY, "x", 0, 24 * HOUR, 300)
    assert len(merged) == 1  # fired again 20 minutes after it ended: the same page
    # with the workbook's five minutes the first page ends at 10:10, and the same burst at 11:20, 70 minutes after that
    # end, comes after the hour's window: a second page
    short = burn.episodes(stream, RULES["fast-burn-1h"], "own-traffic", 0, 24 * HOUR, 300)
    assert len(short) == 1 and (short[0].start, short[0].end) == (10 * HOUR, 10 * HOUR + 600)
    twice = burn.episodes(burn.Stream.of("w2", "success", 0.995, again), RULES["fast-burn-1h"], "x", 0, 24 * HOUR, 300)
    assert [(a.start, a.end) for a in twice] == [(10 * HOUR, 10 * HOUR + 600), (11 * HOUR + 1200, 11 * HOUR + 1800)]


def test_a_short_window_when_one_is_given_must_burn_as_well():
    """The workbook's five minutes for the hour, "ceasing to fire five minutes later, rather than one hour later" (fact
    sheet 9.4), against no short window at all; 0.25 hours is a value made for this test, between the two."""
    events = runs([(HOUR + i, "error") for i in range(3)] + [(t * 60.0, "answer") for t in range(0, 4 * 60, 2)])
    stream = burn.Stream.of("w2", "success", 0.995, events)
    plain = burn.episodes(stream, LONG_ONLY, "x", 0, 4 * HOUR, 300)
    quarter = burn.episodes(stream, {**LONG_ONLY, "short_window_hours": 0.25}, "x", 0, 4 * HOUR, 300)
    workbook = burn.episodes(stream, RULES["fast-burn-1h"], "x", 0, 4 * HOUR, 300)
    assert len(plain) == len(quarter) == len(workbook) == 1
    assert plain[0].start == quarter[0].start == workbook[0].start
    assert plain[0].end - plain[0].start > quarter[0].end - quarter[0].start > workbook[0].end - workbook[0].start
    assert workbook[0].end - workbook[0].start == 300  # the first evaluation whose five minutes hold no error ends it


def test_an_alert_is_put_down_to_the_injection_behind_most_of_its_bad_events():
    events = [slis.RunEvent("w2", f"a{i}", "error", 1.0, at=100.0 + i, injected="throttled-hour") for i in range(3)]
    events += [slis.RunEvent("w2", "b", "error", 1.0, at=50.0)]
    stream = burn.Stream.of("w2", "success", 0.99, events)
    assert stream.attribution(200, 1) == ("throttled-hour", {"baseline": 1, "throttled-hour": 3})
    tied = burn.Stream.of("w2", "success", 0.99, events[:1] + events[3:])
    assert tied.attribution(200, 1)[0] == "baseline"


def test_the_designs_count_the_probe_in_success_alone_and_the_group_at_its_lowest_target():
    slos = slis.load()
    real = runs([(10.0, "answer")], workflow="w3") + runs([(20.0, "answer")], workflow="w1")
    probes = [slis.RunEvent("w3", "p", "answer", 1.0, at=30.0, probe=True)]
    with_probe = {(s.scope, s.sli): s for s in burn.streams("with-probe", ALERTS["designs"]["with-probe"], real, probes, slos)}
    assert len(with_probe[("w3", "success")].times) == 2 and len(with_probe[("w3", "latency")].times) == 1
    own = {(s.scope, s.sli): s for s in burn.streams("own-traffic", ALERTS["designs"]["own-traffic"], real, probes, slos)}
    assert len(own[("w3", "success")].times) == 1
    grouped = {(s.scope, s.sli): s for s in burn.streams("grouped", ALERTS["designs"]["grouped"], real, probes, slos)}
    assert grouped[("group:w1+w3+w4", "success")].target == 0.95 and ("w3", "success") not in grouped
    assert ("w5", "success") not in own  # W5 goes by nights


def test_w5_tickets_a_failed_night_and_never_pages():
    nights = [slis.RunEvent("w5", f"n{i}", "error" if i in (3, 9, 20) else "proposal", 60.0, at=i * 86400.0 + 7200,
                            reason="schedule") for i in range(30)]
    found = burn.night_alerts(nights, ALERTS["w5_failed_nights"], 0.9, 21600.0, 3.0, "with-probe")
    assert [a.rule for a in found] == ["failed-night", "failed-night", "failed-night", "nights-budget-spent"]
    assert {a.action for a in found} == {"ticket"}
    # the month's budget is 3.4 failed runs: three fit inside it and the fourth spends it (slos.yaml, alerts.yaml)
    four = [slis.RunEvent("w5", f"n{i}", "error" if i in (3, 9, 20, 25) else "proposal", 60.0, at=i * 86400.0 + 7200,
                          reason="schedule") for i in range(30)]
    found = burn.night_alerts(four, ALERTS["w5_failed_nights"], 0.9, 21600.0, 3.395, "x")
    assert [a.rule for a in found] == ["failed-night"] * 4 + ["nights-budget-spent"] and found[-1].peak == 4
    assert found[-1].start == 25 * 86400.0 + 7200
    late = [slis.RunEvent("w5", "late", "proposal", 30000.0, at=7200.0 + 30000)]
    assert [a.rule for a in burn.night_alerts(late, {}, 0.9, 21600.0, 3.0, "x")] == ["late-night"]


def test_the_platform_rules_say_which_burn_py_evaluates():
    rules = ALERTS["platform"]["rules"]
    assert [r["name"] for r in rules if r["evaluated"]] == ["provider-429-across-workflows"]
    for r in rules:
        if not r["evaluated"]:
            assert r["not_evaluated_because"], r["name"]
    assert burn.platform_alerts([{"at": 1.0, "workflow": "w2", "kind": "own_limit", "injected": None}]) == []


def test_the_platform_is_paged_when_the_providers_429s_reach_two_workflows():
    one = [{"at": 10.0 + i, "workflow": "w2", "kind": "provider_429", "injected": None} for i in range(5)]
    assert burn.platform_alerts(one) == []
    two = one + [{"at": 100.0, "workflow": "w1", "kind": "provider_429", "injected": "throttled-hour"}]
    found = burn.platform_alerts(two)
    assert [(a.scope, a.action, a.start) for a in found] == [("platform", "page", 100.0)]
    apart = two + [{"at": 100.0 + 2 * HOUR, "workflow": w, "kind": "provider_429", "injected": None} for w in ("w1", "w2")]
    assert len(burn.platform_alerts(apart)) == 2


def test_the_outcome_sli_opens_tickets_and_never_pages(month):
    slos = slis.load()
    budgets = {w: {"success": 1.0} for w in slis.WORKFLOWS}
    found = burn.evaluate(month, ALERTS, slos, budgets)
    assert any(a.sli == "outcome" for a in found["own-traffic"])
    assert all(a.action == "ticket" for d in found.values() for a in d if a.sli == "outcome")
