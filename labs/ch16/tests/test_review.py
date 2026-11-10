"""Step 9's generator over a fixture month: what the review computes itself (the budget left, the window, W5's
shares through W5's own summary, the priced cost to find), the marking of every section, the month's filter on the
records, the controls it says it did not evaluate, an unmapped event that stops it, a month with no W5 night, a page
and its JSON written together or not at all, and the page's shape. The committed results are
tests/test_review_results.py's."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import shutil
from pathlib import Path

import pytest
import yaml

import judge_lines
import monthly_review as review

LAB = Path(__file__).resolve().parents[1]
ON = dt.date(2026, 11, 9)
MONTH = "2026-11"
START = "2027-01-05T00:00:00-05:00"   # the fixture's simulated month, as step 6's
ZERO = {"prompt": 0, "completion": 0, "total": 0}


def describe(median: float, p95: float) -> dict:
    return {"median": median, "p95": p95, "mean": (median + p95) / 2}


def per_run(workflow: str, model: str, runs: int, cost: tuple[float, float], budget: float, calls=(2.0, 3.0)) -> dict:
    return {"workflow": workflow, "model": model, "kept_runs": 1, "runs": runs, "runs_with_tokens": runs,
            "model_calls": describe(*calls), "tool_calls": describe(1.0, 2.0),
            "cost_usd": describe(*cost), "per_run_usd": budget,
            "cost_pct_of_run_budget": describe(cost[0] / budget * 100, cost[1] / budget * 100)}


def month_row(workflow: str, runs: float, unit: str, source: str, cost: float, budget: float, basis="measured",
              kept: int = 1, spread: list[float] | None = None) -> dict:
    direct = runs * cost
    pct = direct / budget * 100
    return {"workflow": workflow, "volume": {"runs": runs, "unit": unit, "source": source}, "sources": [source],
            "basis": basis, "kept_runs": [f"gpt-oss-20b run{i}" for i in range(kept)], "runs_in_profile": 10,
            "runs_per_month": runs, "calls_per_run": 2.0, "calls_per_month": 2 * runs, "tokens_per_month": round(runs * 1000),
            "restricted_tokens_per_month": 0, "cost_per_run_usd": cost, "direct_usd": direct, "per_month_usd": budget,
            "direct_pct_of_month": pct, "direct_pct_range_over_kept_runs": spread or [pct] * 2,
            "recounted_as_nova_lite_usd": direct * 1.1, "recounted_pct_of_month": pct * 1.1,
            "guardrail_usd": direct * 10, "guardrail_pct_of_month": pct * 10, "guardrail_over_tokens": 10}


def judge_row(workflow: str, judge: str, basis: str, judge_tokens: tuple[int, int], judged_tokens: tuple[int, int],
              judgments: int, completion_over: int, total_over: int) -> dict:
    jt = {"prompt": judge_tokens[0], "completion": judge_tokens[1], "total": sum(judge_tokens)}
    ot = {"prompt": judged_tokens[0], "completion": judged_tokens[1], "total": sum(judged_tokens)}
    block = {"judgments": judgments, "judge_tokens": jt, "judged_tokens": ot,
             "ratio": {k: round(jt[k] / ot[k], 4) for k in jt}, "completion_over": completion_over, "total_over": total_over}
    empty = {"judgments": 0, "judge_tokens": ZERO, "judged_tokens": ZERO, "ratio": None, "completion_over": 0, "total_over": 0}
    return {"workflow": workflow, "judge": judge, "judgments": judgments, "judge_tokens": jt, basis: block,
            "stand-in" if basis == "measured" else "measured": empty}


def judge_section() -> dict:
    """The ledger's judge section for a fixture in which one judge thinks and the other doesn't, so the page's
    sentences come out mixed: gpt-oss-20b writes more than the output in W2 and Gemma 4 12B in W5 alone."""
    rows = [judge_row("w2", "gemma4-12b", "measured", (1000, 100), (2000, 400), 2, 0, 0),
            judge_row("w2", "gpt-oss-20b", "measured", (300, 900), (800, 200), 1, 1, 1),
            judge_row("w5", "gemma4-12b", "stand-in", (500, 50), (200, 20), 1, 1, 1)]
    sentence = []
    for r in rows:
        basis = "measured" if r["measured"]["judgments"] else "stand-in"
        sentence.append({"workflow": r["workflow"], "judge": r["judge"], "basis": basis, "judgments": r["judgments"],
                         "ratio": r[basis]["ratio"], "completion_over": r[basis]["completion_over"],
                         "total_over": r[basis]["total_over"]})
    thinking = {"gemma4-12b": False, "gpt-oss-20b": "model default"}
    return {"calls": 4, "prompt_tokens": 1800, "completion_tokens": 1050, "layout": [{"run": "v1"}], "thinking": thinking,
            "by_workflow": rows, "conclusion": judge_lines.conclusion(sentence, thinking)}


def account(budget: float, bad: int, valid: int, spent_at: str | None, causes: dict, seconds: float = 1.0) -> dict:
    return {"budget_events": budget, "bad": bad, "valid": valid, "consumed": round(bad / budget, 4),
            "spent_at": seconds if spent_at else None, "causes_when_spent": causes if spent_at else None,
            "causes": causes, "spent_at_clock": spent_at}


def change(number: str, lever: str, workflow: str, before, after, at: str) -> dict:
    return {"change": number, "kind": "emergency", "lever": lever, "workflow": workflow, "from": before, "to": after,
            "by": "oncall.lead@larkspur.example", "authority": "on-call lead", "at": at,
            "document_by": at.replace("2026-11-03", "2026-11-04").replace("2026-10-30", "2026-10-31")
                             .replace("2026-11-09", "2026-11-10"),
            "review": "the next board meeting", "reason": "test", "answer": {}}


def alert(received: str, event: str, kind: str, spend: float, soft, maximum: float, projected) -> dict:
    return {"received_at": received, "event": event, "kind": kind, "key_alias": "w2-ops-assistant", "spend": spend,
            "soft_budget": soft, "max_budget": maximum, "projected_spend": projected,
            "forwarded_to": ["owner@larkspur.example", "finops@larkspur.example"]}


@pytest.fixture(scope="module")
def sources(tmp_path_factory) -> review.Sources:
    root = tmp_path_factory.mktemp("review")
    ledger = {
        "lines": [{"workflow": "w2", "kept_runs": 2, "runs": 40}, {"workflow": "w5", "kept_runs": 1, "runs": 3}],
        "per_run": [per_run("w2", "gpt-oss-20b", 40, (0.0002, 0.0005), 0.5),
                    per_run("w2", "gemma4-12b", 20, (0.0001, 0.0009), 0.5),
                    per_run("w5", "gpt-oss-20b", 3, (0.003, 0.007), 1.0, calls=(14.0, 14.0))],
        "month": {"reference_model": "gpt-oss-20b", "month_hours": 730, "recount_ratios": {"input": 1.3, "output": 0.5},
                  "rows": [month_row("w2", 40000, "question", "ch09:405", 0.0002, 200),
                           month_row("w5", 34, "night or alarm", "lab assumption, not in the book", 0.003, 100,
                                     basis="measured on the 3 of 6 runs with tokens", kept=3, spread=[0.07, 0.15])]},
        "judge": judge_section(),
        "allocation": {
            "gpu": {"replicas": 2, "hours": 730, "price": "aws-g6e.xlarge-l40s", "per_hour": 1.861, "usd": 2717.06,
                    "capacity_seconds": 5256000, "sent": {},
                    "readings": {"manifests and chapter 10": {
                        "tenants": ["w2"], "busy_seconds": 10.0, "used_share": 0.0001, "used_usd": 0.27, "idle_usd": 2716.79,
                        "idle_share": 0.9999,
                        "split": {"w2": {"tokens": 1000, "token_share": 1.0, "usd": 0.27, "pct_of_month": 0.135,
                                         "without_idle_line_usd": 2717.06, "without_idle_line_pct_of_month": 1358.53}}}}},
            "fixed": {"lines": [], "priced_usd": 400.0, "stand_in_usd": 100.0, "parameters": ["a license"],
                      "splits": {"tokens": {"w2": {"share": 0.9, "usd": 360.0, "pct_of_month": 180.0},
                                            "w5": {"share": 0.1, "usd": 40.0, "pct_of_month": 40.0}},
                                 "gateway calls": {"w2": {"share": 0.95, "usd": 380.0, "pct_of_month": 190.0},
                                                   "w5": {"share": 0.05, "usd": 20.0, "pct_of_month": 20.0}}}}}}
    (root / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    slo = root / "slo"
    slo.mkdir()
    ratio = lambda good, valid: {"good": good, "valid": valid, "value": None if not valid else good / valid}  # noqa: E731
    (slo / "kept.json").write_text(json.dumps({
        "measured": True, "simulated": False,
        "targets": {"w2": {"success": 0.995, "latency": 0.95, "outcome": None},
                    "w5": {"success": 0.9, "latency": 0.9, "outcome": 0.8}},
        "thresholds_s": {"w2": 10.0, "w5": 21600.0},
        "pooled": {"w2": {"slis": {"success": ratio(38, 40), "latency": ratio(38, 38), "outcome": None}},
                   "w5": {"slis": {"success": ratio(3, 3), "latency": ratio(3, 3), "outcome": ratio(0, 0)}}},
        "incidents": []}), encoding="utf-8")
    (slo / "month.json").write_text(json.dumps({
        "simulated": True, "seed": 7, "start": START, "days": 30,
        "workflows": {"w2": {"slis": {"success": ratio(990, 1000), "latency": ratio(950, 990), "outcome": None}},
                      "w5": {"slis": {"success": ratio(34, 34), "latency": ratio(34, 34), "outcome": ratio(8, 10)}}},
        "injected": [{"id": "model-regression", "what": "a worse model", "start": "Wed 20 Jan 10:00", "start_s": 1332000.0,
                      "end": "Thu 04 Feb 00:00", "end_s": 2592000.0, "runs_changed": {"w2": 20403}, "bad_events": {"w2": 12500}},
                     {"id": "throttled-hour", "what": "a throttled hour", "start": "Wed 13 Jan 14:00", "start_s": 741600.0,
                      "end": "Wed 13 Jan 15:00", "end_s": 745200.0, "runs_changed": {"w2": 44}, "bad_events": {}}],
        "incidents": []}), encoding="utf-8")
    (slo / "policy.json").write_text(json.dumps({
        "simulated": True,
        "accounts": {"w2": {"success": account(212.0, 5432, 40000, "Sun 17 Jan 04:24",
                                               {"baseline": 261, "model-regression": 5171}, 1052694.7),
                            "latency": account(49.5, 40, 990, None, {"baseline": 40})},
                     "w5": {"success": account(3.4, 0, 34, None, {}), "latency": account(3.4, 0, 34, None, {}),
                            "outcome": account(2.0, 2, 10, "Fri 29 Jan 09:00", {"baseline": 2}, 2106000.0)}},
        "actions": [{"action": "freeze", "workflow": "w2", "sli": "success", "at": "Sun 17 Jan 04:24", "at_s": 1052694.7,
                     "bad_when_spent": {"baseline": 1, "model-regression": 9}, "decided_by": "the policy, agreed in advance"},
                    {"action": "rung down", "workflow": "w5", "sli": "outcome", "at": "Fri 29 Jan 09:00", "at_s": 2106000.0,
                     "bad_when_spent": {"baseline": 2}, "decided_by": "the on-call lead",
                     "change_record": {"change": "EC-SIM-01"}}]}), encoding="utf-8")
    (slo / "alerts.json").write_text(json.dumps({
        "simulated": True, "proposed": "with-probe",
        "by_event": {"model-regression": {"with-probe": {"action": "page", "first": {
            "scope": "w2", "sli": "success", "rule": "fast-burn-1h", "start": "Wed 20 Jan 10:30", "start_s": 1333800.0}}},
                     "throttled-hour": {"with-probe": {"action": "none", "first": None}}},
        "episodes": {"with-probe": [{"scope": "w2", "sli": "success", "rule": "fast-burn-1h", "action": "page",
                                     "cause": "model-regression"},
                                    {"scope": "w2", "sli": "success", "rule": "slow-burn-3d", "action": "ticket",
                                     "cause": "baseline"}],
                     "platform": [{"scope": "platform", "sli": None, "rule": "provider-429-across-workflows",
                                   "action": "page", "cause": "throttled-hour"}]}}), encoding="utf-8")
    drills = {"date": "2026-11-03",
              "alerts": [alert("2026-11-03T23:45:39.755+00:00", "threshold_crossed", "the month's pace projected past the soft budget",
                               159.751, None, 160.0, 1722.87),
                         alert("2026-11-03T23:45:41.851+00:00", "soft_budget_crossed", "the soft budget reached", 160.0004, 160.0,
                               200.0, None),
                         alert("2026-10-30T10:00:00.000+00:00", "soft_budget_crossed", "last month's", 160.0, 160.0, 200.0, None)],
              "stop": {"stop_status": 422, "stop_kind": "monthly_budget", "first_stopped_run": 5, "max_budget": 200.0,
                       "month_before_the_first_stop_usd": 199.754144, "spend_in_database_after_usd": 199.755632,
                       "short_of_the_budget_usd": 0.244368, "calls_made_by_stopped_runs": 4},
              "changes": [change("EC-DRILL-01", "kill switch, gateway half", "w2-ops-assistant", "open", "blocked",
                                 "2026-11-03T23:45:02.749+00:00"),
                          change("EC-DRILL-01", "kill switch released", "w2-ops-assistant", "blocked", "open",
                                 "2026-11-03T23:45:04.794+00:00"),
                          change("EC-OLD", "rung down", "w3-incident", "manifest (3)", 1, "2026-10-30T10:00:00.000+00:00")]}
    (root / "drills.json").write_text(json.dumps(drills), encoding="utf-8")
    remap = dict(change("CH-20261109-01", "alias remap, back", "w2-ops-assistant",
                        [{"id": "a", "model": "ollama_chat/a", "weight": 3}, {"id": "b", "model": "ollama_chat/b", "weight": 1}],
                        [{"id": "a", "model": "ollama_chat/a"}], "2026-11-09T11:54:11.440+00:00"), alias="larkspur-chat")
    (root / "changes.jsonl").write_text(json.dumps(remap) + "\n", encoding="utf-8")
    register = {
        "stages": {"aws": {"values": ["Active", "Legacy", "EOL"]}, "local": {"values": ["candidate", "serving", "retired"]}},
        "gateways": {"litellm": [], "terraform": []},
        "models": [
            {"id": "soon", "name": "Soon", "cloud": "aws", "pinned": True, "stage": "Legacy", "retires": dt.date(2026, 12, 9),
             "retires_no_earlier_than": None, "replacement": "Later", "legacy_from": dt.date(2026, 6, 9)},
            {"id": "review", "name": "Review", "cloud": "aws", "pinned": False, "stage": "Active", "retires": dt.date(2027, 2, 17),
             "retires_no_earlier_than": None, "replacement": None},
            {"id": "far", "name": "Far", "cloud": "aws", "pinned": True, "stage": "Active", "retires": dt.date(2027, 12, 14),
             "retires_no_earlier_than": None, "replacement": None},
            {"id": "gone", "name": "Gone", "cloud": "aws", "pinned": True, "stage": "EOL", "retires": dt.date(2026, 10, 30),
             "retires_no_earlier_than": None, "replacement": "Soon"},
            {"id": "local", "name": "Local", "cloud": "local", "pinned": True, "stage": "serving", "retires": None,
             "retires_no_earlier_than": dt.date(2026, 1, 1), "replacement": None}]}
    (root / "register.yaml").write_text(yaml.safe_dump(register), encoding="utf-8")
    w5 = {"findings": {
        "sandbox:vol-1:unattached_volume": {"kind": "unattached_volume", "workspace": "sandbox", "first_seen": "2026-11-02",
                                             "last_seen": "2026-11-02", "estimated_monthly_saving": 50.0,
                                             "realized_monthly_saving": 50.0, "realized_on": "2026-11-03", "suppressed_by": None,
                                             "pull_request": {"number": 1, "state": "merged", "merged": "2026-11-02"}},
        "sandbox:i-1:idle": {"kind": "idle", "workspace": "sandbox", "first_seen": "2026-11-02", "last_seen": "2026-11-03",
                             "estimated_monthly_saving": 30.0, "realized_monthly_saving": None, "realized_on": None,
                             "suppressed_by": None, "pull_request": {"number": 2, "state": "open"}},
        "sandbox:i-1:untagged": {"kind": "untagged", "workspace": "sandbox", "first_seen": "2026-11-02", "last_seen": "2026-11-03",
                                 "estimated_monthly_saving": None, "realized_monthly_saving": None, "realized_on": None,
                                 "suppressed_by": None, "pull_request": {"number": 3, "state": "open"}},
        "sandbox:i-2:untagged": {"kind": "untagged", "workspace": "sandbox", "first_seen": "2026-11-02", "last_seen": "2026-11-03",
                                 "estimated_monthly_saving": None, "realized_monthly_saving": None, "realized_on": None,
                                 "suppressed_by": "RITM1", "pull_request": None}},
        "nights": {
            "2026-11-02": {"night": "2026-11-02", "trigger": {"kind": "schedule"}, "workspaces": ["sandbox"], "duration_s": 60.0,
                           "gateway_calls": 10, "prompt_tokens": 6000, "completion_tokens": 3000, "refused": 0, "failed": 0,
                           "findings": 4, "by_kind": {}, "pull_requests": {"opened": 3, "updated": 0, "skipped": 0, "suppressed": 1},
                           "body_sources": {}, "refused_words": {}, "realized": [], "spend": {"a": 6000.0, "b": 4000.0}},
            "2026-11-03": {"night": "2026-11-03", "trigger": {"kind": "schedule"}, "workspaces": ["sandbox"], "duration_s": 40.0,
                           "gateway_calls": 8, "prompt_tokens": 4000, "completion_tokens": 2000, "refused": 0, "failed": 0,
                           "findings": 3, "by_kind": {}, "pull_requests": {"opened": 0, "updated": 2, "skipped": 0, "suppressed": 1},
                           "body_sources": {}, "refused_words": {}, "realized": ["sandbox:vol-1:unattached_volume"],
                           "spend": {"a": 6000.0, "b": 4000.0}}}}
    (root / "w5-ledger.json").write_text(json.dumps(w5), encoding="utf-8")
    return review.Sources(root / "ledger.json", slo, root / "drills.json", root / "changes.jsonl", root / "register.yaml",
                          LAB / "lifecycle" / "alerts.yaml", LAB / "playbook" / "playbook.yaml",
                          LAB / "ledger" / "volumes.yaml", LAB / "ledger" / "prices.yaml", root / "w5-ledger.json",
                          "fixture", ())


@pytest.fixture(scope="module")
def data(sources) -> dict:
    return review.build(MONTH, ON, sources)


@pytest.fixture(scope="module")
def page(data) -> str:
    return review.render(data)


def section_of(page: str, number: int) -> str:
    """The text of one numbered section of the page."""
    lines = page.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## {number}. "))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end])


def test_every_section_says_what_its_figures_are_and_where_they_come_from(data, page):
    assert list(data["legend"]) == ["measured", "priced", "estimated", "simulated", "recorded"]
    for name, section in data["sections"].items():
        marks = {k: v for k, v in section["basis"].items() if k != "note"}
        assert marks and section["basis"]["note"], name
        for mark in marks.values():
            assert mark in data["legend"] or mark in ("not evaluated", "listed"), (name, mark)
    headings = [line for line in page.splitlines() if line.startswith("## ")]
    assert len(headings) == 9 and headings[-1] == "## Sources"
    lines = page.splitlines()
    for heading in headings[:-1]:
        at = lines.index(heading)
        assert lines[at + 2].startswith("Basis: ") and "Source: `" in lines[at + 2], heading
    assert "in five words:" in page
    for word in ("measured", "priced", "estimated", "simulated", "recorded"):
        assert f"- {word}: " in page


def test_the_legend_and_the_opening_take_their_counts_and_dates_from_the_files(data, page):
    assert "30 days built from the kept runs with two injected events" in data["legend"]["simulated"]
    p = data["prices"]
    assert p["file"] == "labs/ch16/ledger/prices.yaml" and p["entries"] == p["dated"] == 49
    assert (p["first"], p["last"]) == ("2026-10-28", "2026-11-03")  # the dated table's own entries
    assert "49 entries, each with its source and its date, 28 October to 3 November 2026" in page
    assert "sections 6 and 8 read the records dated in November 2026" in page
    assert review.span("2026-10-28", "2026-11-03") == "28 October to 3 November 2026"
    assert review.span("2026-11-03", "2026-11-03") == "3 November 2026"
    assert review.span("2026-11-03", "2026-11-28") == "3 to 28 November 2026"
    assert review.span("2026-11-03", "2027-01-02") == "3 November 2026 to 2 January 2027"


def test_the_per_run_figures_are_priced_from_measured_tokens_and_the_volumes_are_estimates(data, page):
    r = data["sections"]["runs_and_cost_per_run"]
    assert r["reference_model"] == "gpt-oss-20b" and [w["workflow"] for w in r["rows"]] == ["w2", "w5"]
    w2 = r["rows"][0]
    assert w2["cost_per_run_usd"] == {"median": 0.0002, "p95": 0.0005} and w2["pct_of_per_run_usd"] == {"median": 0.04, "p95": 0.1}
    assert w2["runs_kept"] == 40 and w2["runs_a_month"] == 40000 and w2["volume_sources"] == ["ch09:405"]
    assert {k: v for k, v in r["basis"].items() if k != "note"} == {
        "runs_kept": "measured", "model_calls_a_run": "measured", "runs_a_month": "estimated", "cost_per_run": "priced",
        "judge_tokens": "measured"}
    assert r["highest_median"] == {"workflow": "w5", "pct": 0.3} and r["highest_p95"]["model"] == "gpt-oss-20b"
    assert "Basis: runs kept measured; model calls a run measured; runs a month estimated; cost per run priced;" in page
    assert "Cost per run, median / 95th (USD, priced from the gpt-oss-20b tokens)" in page
    assert "|W2|40|40,000|question|ch09:405|2 / 3|0.000200 / 0.000500|0.04% / 0.1%|0.5|" in page
    assert "the dollars are those tokens priced at chapter 6's design" in page
    assert "W5's per-run figures come from the runs that kept tokens, as the basis column of section 2 says" in page


def test_the_month_is_the_volume_times_the_mean_cost_and_the_page_gives_the_mean(data, page):
    m = data["sections"]["month_against_budget"]
    assert {k: v for k, v in m["basis"].items() if k != "note"} == {"month": "estimated", "mean_cost_per_run": "priced"}
    for row in m["rows"]:
        assert row["runs_a_month"] * row["mean_cost_per_run_usd"] == pytest.approx(row["direct_usd"])
    assert m["rows"][0]["pct_of_per_month_usd"] == pytest.approx(40000 * 0.0002 / 200 * 100)
    assert m["largest"]["workflow"] == "w2"
    section = section_of(page, 2)
    assert "Basis: month estimated; mean cost per run priced. The month is the estimated volume times the mean cost per run" in section
    assert "|Workflow|Runs a month (estimated)|Tokens a month (estimated)|Mean cost per run (USD, priced)|" in section
    assert "|W2|40,000|40,000,000|0.000200|8.00|200|4%|one kept run|4.4%|40%|measured|" in section
    # more than one kept run: the range, and the basis of a partly measured profile
    assert "|W5|34|34,000|0.00300|0.102|100|0.102%|0.07% to 0.15%|0.112%|1.02%|measured on the 3 of 6 runs with tokens|" in section


def test_the_judge_paragraph_is_derived_and_says_in_total_what_it_compares(data, page):
    jd = data["sections"]["runs_and_cost_per_run"]["judge"]
    assert (jd["calls"], jd["runs"], jd["prompt_tokens"], jd["completion_tokens"]) == (4, 1, 1800, 1050)
    assert [(r["workflow"], r["judge"], r["basis"]) for r in jd["rows"]] == [
        ("w2", "gemma4-12b", "measured"), ("w2", "gpt-oss-20b", "measured"), ("w5", "gemma4-12b", "stand-in")]
    assert jd["rows"][1]["ratio"] == {"prompt": 0.375, "completion": 4.5, "total": 1.2}
    assert jd["conclusion"]["not_judged_by"] == {"gpt-oss-20b": {"w5": ["gemma4-12b"]}, "gemma4-12b": {}}
    assert "|W2|gpt-oss-20b|1|300 / 900 / 1,200|800 / 200 / 1,000|0.38 / 4.50 / 1.20|1|measured|" in page
    assert "|W5|gemma4-12b|1|500 / 50 / 550|200 / 20 / 220|2.50 / 2.50 / 2.50|1|stand-in|" in page
    paragraph = next(line for line in page.splitlines() if line.startswith("Chapter 15's judge is in the ledger"))
    assert "Chapter 15 says (ch15:156) that a judge that thinks before it answers writes more tokens than the answer it judges." in paragraph
    assert ("In completion tokens, in total, gpt-oss-20b (thinking at the model's default) wrote more than the outputs it read "
            "in every workflow it judged: W2 (4.50). The sentence holds as written, for completion tokens, wherever that judge "
            "judged; W5 was judged by Gemma 4 12B alone.") in paragraph
    assert ("its total is above the output's for W2 (1.20); these are token figures and not prices.") in paragraph
    assert ("Gemma 4 12B (thinking off) wrote, in completion tokens and in total, more than the outputs it read in W5 and "
            "fewer in W2: W2 (0.25) and W5 (2.50, on the stand-in); in all tokens its total is above the output's for W5 "
            "(2.50, on the stand-in) and below it for W2 (0.46).") in paragraph
    # the claim is in tokens: no sentence says the judge costs more than what it judges, and none says "every output"
    assert "costs more than the answer" not in page and "than every output" not in page


def test_the_shared_lines_follow_o_d6_as_amended(data, page):
    sh = data["sections"]["shared_lines"]
    assert sh["tenants"] == ["w2"] and sh["fixed"]["split_by"] == "tokens" and sh["fixed"]["parameters"] == ["a license"]
    w2, w5 = sh["rows"]
    assert w2["tenant"] and w2["gpu_usd"] == 0.27 and w2["fixed_usd"] == 360.0 and w2["fixed_pct_of_per_month_usd"] == 180.0
    assert not w5["tenant"] and w5["gpu_usd"] == 0.0 and w5["fixed_usd"] == 40.0
    assert "|idle, the platform team||||2,716.79||||||" in page
    assert "never count against a workflow's budget" in page
    assert "; one line has no published price and stays a parameter outside the sum: a license." in page
    assert "one lines" not in page and "lines has" not in page


def test_the_budget_left_is_one_minus_the_share_spent_and_a_spent_budget_says_when_and_in_which_year(data, page):
    e = data["sections"]["error_budget"]
    by = {(a["workflow"], a["sli"]): a for a in e["simulated"]}
    assert by[("w2", "latency")]["left"] == pytest.approx(1 - 40 / 49.5, abs=1e-4) and by[("w2", "latency")]["spent_at"] is None
    assert by[("w2", "success")]["spent_at"] == "Sun 17 Jan 2027 04:24" and by[("w2", "success")]["spent_at_s"] == 1052694.7
    assert by[("w5", "outcome")]["spent_at"] == "Fri 29 Jan 2027 09:00"
    assert by[("w5", "success")]["left"] == 1.0
    assert [(a["workflow"], a["sli"]) for a in e["spent"]] == [("w2", "success"), ("w5", "outcome")]
    assert e["basis"] == {"slis_on_the_kept_runs": "measured", "budgets": "simulated", "note": e["basis"]["note"]}
    assert "Basis: SLIs on the kept runs measured; budgets simulated." in page
    measured = {(a["workflow"], a["sli"]): a for a in e["measured"]}
    assert measured[("w2", "success")]["value"] == 0.95 and ("w2", "outcome") not in measured
    assert measured[("w5", "outcome")]["valid"] == 0
    # one number format in a row: separators on the count of bad events, on the share used, and in the causes
    assert ("|W2|success|212|5,432|2,562%|spent, Sun 17 Jan 2027 04:24 (used 2,562%)|baseline 261, model-regression 5,171|"
            in page)
    assert "|W2|latency|49.5|40|80.81%|19.2%|baseline 40|" in page
    assert "|W5|outcome|80%||no events||" in page
    assert "Two budgets were spent in it: W2 success on Sun 17 Jan 2027 04:24; W5 outcome on Fri 29 Jan 2027 09:00." in page


def test_the_controls_are_not_evaluated_and_the_page_says_why(data, page):
    i = data["sections"]["incidents"]
    assert i["control_breaches"]["status"] == "not evaluated" and i["control_breaches"]["kept_runs"] == []
    assert i["basis"]["control_breaches"] == "not evaluated" and "measured" not in i["basis"].values()
    assert "Basis: events simulated; control breaches not evaluated." in page
    assert ("Control breaches (residency, the never-list, the budgets): not evaluated. Nothing in the lab checks a run against "
            "a control: a run's `violation` field is set by no kept run and no simulated run (slo/slis.py)") in page
    assert "The controls hold by refusal, and the gateway's refusal counts" in page
    assert "0 control breaches" not in page and "0 in the kept runs" not in page


def test_a_breach_that_something_lists_is_reported_as_listed(sources, tmp_path):
    slo = tmp_path / "slo"
    shutil.copytree(sources.slo, slo)
    kept = json.loads((slo / "kept.json").read_text(encoding="utf-8"))
    kept["incidents"] = ["w2:gpt-oss-20b:run:w2-01"]
    (slo / "kept.json").write_text(json.dumps(kept), encoding="utf-8")
    listed = dataclasses.replace(sources, slo=slo)
    built = review.build(MONTH, ON, listed)
    breaches = built["sections"]["incidents"]["control_breaches"]
    assert breaches["status"] == "listed" and breaches["kept_runs"] == ["w2:gpt-oss-20b:run:w2-01"]
    text = review.render(built)
    assert "Basis: events simulated; control breaches listed." in text
    assert "listed by `violation`: 1 run of the kept runs and 0 runs of the simulated month" in text


def test_the_incidents_read_the_playbook_and_carry_the_year_of_the_simulated_month(data, page):
    i = data["sections"]["incidents"]
    regression, other = i["events"]
    assert regression["symptom"] == "a model that changed under its alias"
    assert (regression["start"], regression["end"]) == ("Wed 20 Jan 2027 10:00", "Thu 04 Feb 2027 00:00")
    assert regression["first_alert"] == {"action": "page", "scope": "w2", "sli": "success", "rule": "fast-burn-1h",
                                         "start": "Wed 20 Jan 2027 10:30"}
    assert regression["policy"] == [{"workflow": "w2", "action": "freeze", "sli": "success", "at": "Sun 17 Jan 2027 04:24",
                                     "its_bad_events": 9, "bad_events_when_spent": 10}]
    assert other["symptom"] == review.NO_SYMPTOM and other["first_alert"] is None and other["policy"] == []
    assert i["alerts_by_scope"] == [{"scope": "w2", "pages": {"model-regression": 1}, "tickets": {"baseline": 1}},
                                    {"scope": "platform", "pages": {"throttled-hour": 1}, "tickets": {}}]
    assert [(a["at"], a["change"]) for a in i["policy_actions"]] == [("Sun 17 Jan 2027 04:24", None),
                                                                     ("Fri 29 Jan 2027 09:00", "EC-SIM-01")]
    assert "9 of the 10 bad events when spent" in page
    assert "|model-regression|Wed 20 Jan 2027 10:00 to Thu 04 Feb 2027 00:00|a model that changed under its alias|W2 20,403|W2 12,500|" in page
    assert "|Fri 29 Jan 2027 09:00|W5|rung down|outcome|the on-call lead|EC-SIM-01|" in page
    assert "The two events were injected into step 6's month" in page
    assert with_year_checks()


def with_year_checks() -> bool:
    assert review.with_year("Mon 11 Jan 10:00", START, 554400.0) == "Mon 11 Jan 2027 10:00"
    assert review.with_year("Thu 31 Dec 23:30", "2026-12-30T00:00:00-05:00", 86400.0 * 1.98) == "Thu 31 Dec 2026 23:30"
    assert review.with_year("Fri 01 Jan 00:30", "2026-12-30T00:00:00-05:00", 86400.0 * 2.02) == "Fri 01 Jan 2027 00:30"
    assert review.with_year(None, START, 1.0) is None and review.with_year("Mon 11 Jan 10:00", START, None) == "Mon 11 Jan 10:00"
    return True


def test_an_injected_event_with_no_reading_stops_the_review(sources, tmp_path):
    slo = tmp_path / "slo"
    shutil.copytree(sources.slo, slo)
    month = json.loads((slo / "month.json").read_text(encoding="utf-8"))
    month["injected"].append({"id": "a-new-shape", "what": "an event the playbook doesn't name", "start": "Mon 11 Jan 10:00",
                              "start_s": 554400.0, "end": "Mon 11 Jan 11:00", "end_s": 558000.0, "runs_changed": {},
                              "bad_events": {}})
    (slo / "month.json").write_text(json.dumps(month), encoding="utf-8")
    with pytest.raises(ValueError, match="a-new-shape.*SYMPTOM_OF"):
        review.incidents(slo, sources.playbook, ["w2", "w5"])
    # the throttled hour is in the table with no symptom, which is a reading and not a default
    assert "throttled-hour" in review.SYMPTOM_OF and review.SYMPTOM_OF["throttled-hour"] is None


def test_the_months_records_are_filtered_by_month_and_grouped_by_change(data, page):
    b = data["sections"]["budget_events_and_switches"]
    assert [a["event"] for a in b["alerts"]] == ["threshold_crossed", "soft_budget_crossed"]  # October's is left out
    assert b["alerts"][1]["spend_usd"] == 160.0004
    assert b["stop"]["status"] == 422 and b["stop"]["short_of_budget_usd"] == 0.244368
    assert [c["change"] for c in b["changes"]] == ["EC-DRILL-01", "CH-20261109-01"]  # EC-OLD is October's
    drill, remap = b["changes"]
    assert drill["lines"] == 2 and [s["lever"] for s in drill["steps"]] == ["kill switch, gateway half", "kill switch released"]
    assert drill["steps"][0] == {"lever": "kill switch, gateway half", "from": "open", "to": "blocked"}
    assert remap["workflow"] == "larkspur-chat" and remap["steps"][0]["from"] == "a (weight 3), b (weight 1)"
    assert remap["steps"][0]["to"] == "a" and remap["run"] == "the upgrade path, run once"
    section = section_of(page, 6)
    assert "## 6. Budget events and switches pulled in November 2026" in section
    assert "Two changes left 3 record lines in the month, each an emergency change by the on-call lead, to be documented " \
           "within 24 hours and reviewed at the next board meeting (ch02:163)." in section
    assert b["rule"] == {"kinds": ["emergency"], "authority": ["on-call lead"], "hours": [24], "review": ["the next board meeting"]}
    assert b["basis"]["records"] == "recorded" and b["basis"]["timings"] == "measured"
    # the counts in the basis come from the records the month holds
    assert ("the change records are the lines the levers left in November 2026: one kill-switch cycle as drills, and one "
            "alias remap in the upgrade path, run once") in section
    assert "Step 4's drills ran on 3 November 2026 (UTC)" in section
    # the projection alert has no soft budget of its own, and the page says why
    assert "One of the two alerts shows no soft budget: it is LiteLLM's projection alert, which passes the soft budget as " \
           "its max_budget (160 here) and adds a projected spend." in section
    assert "|2026-11-03T23:45:39|w2-ops-assistant|threshold_crossed|the month's pace projected past the soft budget|159.751||160|1,722.87|" in section


def test_the_window_holds_every_model_within_180_days_sorted_by_days_left(data, page):
    t = data["sections"]["retirement"]
    assert t["windows"] == {"alert_days": 90, "review_days": 180}
    assert [(r["model"], r["days_left"], r["state"]) for r in t["rows"]] == \
        [("Gone", -10, "retired"), ("Soon", 30, "alert"), ("Review", 100, "review")]
    fires = {r["model"]: r["fires"] for r in t["rows"]}
    assert fires["Gone"] == ["page"] and fires["Soon"] == ["ticket", "review", "ticket (Legacy notice)"] and fires["Review"] == ["review"]
    assert (t["pages"], t["tickets"], t["review_rows"]) == (1, 2, 2)
    assert t["unscheduled"] == [{"model": "Local", "cloud": "local", "pinned": True, "earliest": "2026-01-01", "earliest_passed": True}]
    assert "## 7. Models within 180 days of retirement on 9 November 2026" in page
    assert "Three models are inside the window, two of them behind a Larkspur alias (Gone, Soon)." in page
    assert "The rules fired 1 page, 2 tickets, and 2 review rows." in page
    assert ("One model has no published retirement date, and the provider's earliest possible date for it has passed (Local), "
            "so a notice can come any day.") in page
    assert t["basis"]["dates"] == "recorded"


def test_a_date_with_no_page_says_0_pages(sources):
    early = review.build(MONTH, dt.date(2026, 10, 1), sources)
    assert early["sections"]["retirement"]["pages"] == 0
    assert "The rules fired 0 pages, 3 tickets, and 3 review rows." in review.render(early)


def test_w5s_shares_are_its_own_ledgers_and_the_page_gives_shares_and_no_amount(data, page):
    v = data["sections"]["w5_savings"]
    savings = v["savings"]
    assert savings == {"proposed_share_of_spend": 0.008, "realized_share_of_spend": 0.005,
                       "realized_share_of_proposed": 0.625, "realized_findings": 1}  # 80 proposed, 50 realized, 10,000 spent
    assert v["findings"] == {"seen": 4, "by_kind": {"unattached_volume": 1, "idle": 1, "untagged": 2}, "suppressed": 1,
                             "with_estimate": 2}
    assert v["pull_requests"] == {"open": 2, "merged": 1, "closed": 0, "opened": 3, "updated": 2, "skipped": 0}
    assert v["nights"] == 2 and v["night_kinds"] == {"schedule": 2}
    assert v["agent"]["gateway_calls"] == 18 and v["agent"]["prompt_tokens"] == 10000 and v["agent"]["completion_tokens"] == 5000
    priced = 10000 * 0.064 / 1e6 + 5000 * 0.256 / 1e6  # larkspur-chat's deployment in the dated table, nova-lite-ca
    assert v["priced"]["deployment"] == "nova-lite-ca"
    assert v["priced"]["pct_of_per_month_usd"] == pytest.approx(priced / 100 * 100, abs=1e-6)  # W5's per_month_usd is 100
    assert v["priced"]["share_of_realized_saving"] == pytest.approx(priced / 50, abs=1e-8)
    assert v["range_over_kept_runs"] == {"runs": 1, "completion_tokens": [5000, 5000], "seconds": [100.0, 100.0]}
    # shares only: no amount of the cost to find, of the per-night cost, or of a saving is in the data or on the page
    assert set(v["priced"]) == {"deployment", "pct_of_per_month_usd", "share_of_realized_saving"}
    assert set(v["per_night"]) == {"model", "pct_of_per_run_usd"}
    section = section_of(page, 8)
    assert "USD" not in section and "dollars" not in section
    assert "|0.8%|open 2, merged 1, closed 0|0.5%|62.5%|1|4 seen, 2 with an estimate, 1 suppressed|2: 2 scheduled nights|" in section
    assert "|Gateway calls (measured)|Prompt tokens|Completion tokens|Seconds|Cost to find, of per_month_usd (priced at nova-lite-ca)|" in section
    assert {k: v for k, v in v["basis"].items() if k != "note"} == {"savings": "recorded", "calls_and_tokens": "measured",
                                                                    "cost_to_find": "priced"}
    assert "Basis: savings recorded; calls and tokens measured; cost to find priced." in section
    assert "the ledger realized 1 finding" in section and "when a later night found the resource gone" in section
    assert "of the two accounts' month" in section


def test_a_month_with_no_w5_night_says_so_and_the_page_is_still_written(sources, tmp_path):
    december = review.build("2026-12", ON, sources)
    v = december["sections"]["w5_savings"]
    assert v["nights"] == 0 and v["savings"]["proposed_share_of_spend"] is None and v["priced"]["share_of_realized_saving"] is None
    b = december["sections"]["budget_events_and_switches"]
    assert b["alerts"] == [] and b["stop"] is None and b["changes"] == [] and b["rule"] is None  # the drills' day was November
    page = review.render(december)
    assert "W5 ran no night and no alarm in December 2026" in section_of(page, 8)
    assert "No budget alert was received in December 2026." in page and "No budget stop is recorded for December 2026." in page
    assert "No change record is dated in December 2026." in page and "the month holds no change record" in page
    assert "## 6. Budget events and switches pulled in December 2026" in page
    for month in ("2026-10", "2026-12"):
        review.write(tmp_path / month, month, ON, sources)
        assert sorted(p.name for p in (tmp_path / month).iterdir()) == [f"review-{month}.json", f"review-{month}.md"]


def test_a_review_is_written_whole_or_not_at_all(sources, tmp_path, monkeypatch):
    out = tmp_path / "out"
    broken = dataclasses.replace(sources, slo=tmp_path / "no-such-folder")
    with pytest.raises(FileNotFoundError):
        review.write(out, MONTH, ON, broken)
    assert not out.exists()

    def refuse(_data):
        raise RuntimeError("the page cannot be made")

    monkeypatch.setattr(review, "render", refuse)
    with pytest.raises(RuntimeError):
        review.write(out, MONTH, ON, sources)
    assert not out.exists()  # the JSON waits for the page
    monkeypatch.undo()
    review.write(out, MONTH, ON, sources)
    assert sorted(p.name for p in out.iterdir()) == ["review-2026-11.json", "review-2026-11.md"]  # no temporary file left


def test_the_files_the_review_writes_and_the_paths_it_names(data, sources, tmp_path):
    review.write(tmp_path, MONTH, ON, sources)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["review-2026-11.json", "review-2026-11.md"]
    written = json.loads((tmp_path / "review-2026-11.json").read_text(encoding="utf-8"))
    assert written == data and written["month"] == MONTH and written["on"] == "2026-11-09"
    for key, value in data["sources"].items():
        for path in (value if isinstance(value, list) else [value]):
            assert "\\" not in path and ":" not in path, (key, path)  # a repository-relative path or a bare file name
    assert data["sources"]["ledger"] == "ledger.json" and data["sources"]["w5_ledger"] == "w5-ledger.json"
    assert data["sources"]["prices"] == "labs/ch16/ledger/prices.yaml"


def test_the_formats_and_the_words(data):
    assert review.usd(466.5416) == "466.54" and review.usd(2716.15) == "2,716.15" and review.usd(0.0002401) == "0.000240"
    assert review.usd(0.5) == "0.500" and review.usd(0.213) == "0.213" and review.usd(0) == "0" and review.usd(None) == ""
    assert review.usd(6.0992e-05) == "0.0000610" and review.usd(9.01251467) == "9.01"
    assert review.num(2560.0, 4) == "2,560" and review.num(182.5, 4) == "182.5" and review.num(5161) == "5,161"
    assert review.num(1234.5, 5) == "1,234.5" and review.num(0.0374) == "0.0374" and review.num(100000000) == "100,000,000"
    assert review.pct(2560.0, 4) == "2,560%" and review.pct(None) == ""
    assert review.counts({"model-regression": 5161, "baseline": 261}) == "model-regression 5,161, baseline 261"
    assert review.plural(0, "page") == "0 pages" and review.plural(1, "page") == "1 page"
    assert review.plural(5, "budget", lead=True) == "Five budgets" and review.plural(12, "budget", lead=True) == "12 budgets"
    assert review.plural(1, "entry", "entries") == "1 entry" and review.plural(49, "entry", "entries") == "49 entries"
    assert review.words(5) == "five" and review.words(11) == "11"
    assert review.month_name("2026-11") == "November 2026" and review.day_name(ON) == "9 November 2026"
    assert review.legend({"days": 30, "injected": list(range(5))}, data["prices"])["simulated"].startswith(
        "step 6's month, 30 days built from the kept runs with five injected events")
