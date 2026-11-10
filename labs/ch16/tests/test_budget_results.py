"""Step 4's committed results: the smoke test, the drills, and the README's tables, as `budget/smoke.py` and
`budget/drills.py` wrote them on 3 November 2026.

These tests read files; they start nothing. The drills themselves need PostgreSQL and the scratch environment
with Prisma, so they run by hand (README, step 4), and what they found is held here.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import drills
import pytest

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-03" / "budget"
SMOKE = json.loads((RESULTS / "smoke.json").read_text(encoding="utf-8"))
DRILLS = json.loads((RESULTS / "drills.json").read_text(encoding="utf-8"))
STEP4 = "## Budgets and switches (step 4)"
W2_OWNER, FINOPS = "sam.okafor@larkspur.example", "finops@larkspur.example"


def test_the_summary_is_what_drills_writes_from_the_committed_files():
    summary = (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert summary == drills.summarize(DRILLS, SMOKE)


def test_the_readmes_step_4_tables_are_the_summarys():
    readme = (LAB / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    summary = (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    section, rows = "", []
    for line in readme.splitlines():
        if line.startswith("## "):
            section = line
        if section == STEP4 and line.startswith("|") and not line.startswith("|---"):
            rows.append(line)
    assert len(rows) >= 30
    for row in rows:
        assert row in summary, row


def test_the_smoke_test_found_lite_llms_database_working_on_windows():
    steps = {s["step"]: s for s in SMOKE["steps"]}
    assert steps["prisma generate"]["exit"] == 0
    assert (steps["readiness"]["db"], steps["readiness"]["status"]) == ("connected", "healthy")
    for name in ("call 1, master key", "call 2, master key", "call 3, the virtual key", "call 5, the key unblocked"):
        assert steps[name]["status"] == 200, name
    assert steps["key block"]["blocked"] is True
    assert steps["call 4, the blocked key"]["status"] == 401
    assert "Key is blocked" in steps["call 4, the blocked key"]["error"]
    assert SMOKE["engines"] and all(e["alive_when_the_script_stopped_the_proxy"] for e in SMOKE["engines"])
    assert any("Watching engine PID" in line and "os.kill polling" in line for line in SMOKE["proxy_log_watcher_lines"])
    assert (SMOKE["versions"]["litellm"], SMOKE["versions"]["prisma"], SMOKE["versions"]["python"]) == \
        ("1.106.6", "0.15.0", "3.12.9")
    assert SMOKE["postgres"] == "16.15-5"


def test_the_probe_shows_where_the_watchers_call_kills():
    seen = set()
    for probe in SMOKE["os_kill_probe"]:
        calls = {a["call"] for a in probe["attempts"]}
        last = probe["attempts"][-1]
        seen.add((probe["python"][:4], probe["mode"]))
        if probe["mode"] == "console":
            assert calls == {"returned"} and last["child_alive"], probe
        elif probe["python"].startswith("3.10"):
            assert last["child_alive"] is False and last["child_exit_code"] == 0, probe  # TerminateProcess(pid, 0)
            assert any("SystemError" in c for c in calls)
        else:
            assert calls == {"raised OSError (winerror 6)"} and last["child_alive"], probe
    assert {("3.12", "console"), ("3.12", "no-console"), ("3.10", "no-console")} <= seen


def test_each_key_resets_at_midnight_on_the_first_in_toronto():
    for workflow, key in DRILLS["keys"].items():
        assert key["key_alias"] == workflow and key["metadata"]["workflow"] == workflow
        assert key["budget_duration"] == "1mo" and key["soft_share"] == 0.8
        assert key["reset_matches_toronto"], workflow
        assert key["reset_in_toronto"].endswith("T00:00:00-05:00")


def test_the_kill_switch_refuses_the_next_call_and_lets_the_one_after_the_unblock_through():
    ks = DRILLS["kill_switch"]
    assert len(ks["cycles"]) == 5
    for cycle in ks["cycles"]:
        assert (cycle["block_answer"], cycle["unblock_answer"]) == (True, False)
        assert (cycle["call_right_after_block"], cycle["call_right_after_block_kind"]) == (401, "kill_switch")
        assert cycle["call_right_after_unblock"] == 200
        assert 0 < cycle["first_loop_refusal_s"] < 1 and 0 < cycle["first_loop_success_after_unblock_s"] < 1
    assert set(ks["loop_outcomes"]) == {"answered", "kill_switch"}


def test_the_80_percent_alert_reached_the_owner_and_finops():
    alert = DRILLS["alert"]["alert"]
    assert (alert["event"], alert["key_alias"]) == ("soft_budget_crossed", "w2-ops-assistant")
    assert alert["forwarded_to"] == [W2_OWNER, FINOPS]
    assert alert["spend"] >= DRILLS["alert"]["soft_budget"] == 160.0
    assert DRILLS["alert"]["alert_during_run"] > 1  # runs were answered before it came
    # what LiteLLM counted beyond the priced calls when it sent it: one call's reservation, near the estimate
    beyond, estimate = DRILLS["alert"]["alert_spend_beyond_the_month_usd"], DRILLS["reservation"]["estimate_usd"]
    assert abs(beyond - estimate) < 0.002


def test_every_alert_went_to_both_and_says_what_it_is():
    alerts = DRILLS["alerts"]
    assert [a["event"] for a in alerts].count("soft_budget_crossed") == 1
    for alert in alerts:
        assert alert["forwarded_to"] == [W2_OWNER, FINOPS]
        projected = alert["projected_spend"] is not None
        assert (alert["kind"] == "the month's pace projected past the soft budget") == projected
        if projected:  # LiteLLM's projection carries the soft budget as its max_budget
            assert alert["max_budget"] == 160.0 and "Projected Limit Exceeded" in alert["event_message"]


def test_a_spent_budget_is_a_422_the_harness_counts_as_a_stop_and_never_retries():
    stop = DRILLS["stop"]
    assert (stop["stop_status"], stop["stop_kind"]) == (422, "monthly_budget")
    assert "Budget has been exceeded!" in stop["stop_message"]
    assert stop["tally"]["answered"] >= 1 and stop["tally"]["monthly_budget"] >= 4
    for run in stop["runs"]:
        if run["stop"]:
            assert run["calls"] <= 1, run  # the 422 ended the run where it came
    # stopped about one reservation short of the budget, never over it
    assert 0 < stop["short_of_the_budget_usd"] < DRILLS["reservation"]["estimate_usd"]


def test_the_month_survived_a_restart_and_reset_on_time():
    restart = DRILLS["restart"]
    assert restart["spend_in_database_before_restart"] == restart["month_set_to_usd"] == 200.0
    assert restart["spend_litellm_reports_after_restart"] == 200.0
    for name in ("run_before_restart", "run_after_restart"):
        run = restart[name]
        assert (run["stop"], run["status"], run["calls"]) == ("monthly_budget", 422, 0), name
    reset = DRILLS["reset"]
    assert reset["spend_after_reset"] == 0 and reset["new_reset_matches_toronto"]
    assert reset["runs_until_answered"][-1]["answered"]


def test_the_key_is_bound_to_its_workflow():
    assert [(b["status"], b["kind"]) for b in DRILLS["binding"]] == [
        (200, "answered"), (400, "refused"), (400, "refused"), (400, "refused"), (200, "answered")]


def test_the_rung_down_refuses_the_write_before_it_is_called():
    cases = {r["case"]: r for r in DRILLS["rung"]}
    assert cases["no override; the model asks to restart"]["tool_calls"] == {"restart_deployment": 1}
    lowered = cases["lowered to rung 1; the model asks to restart"]
    assert lowered["rung"] == 1 and lowered["tool_calls"] == {}
    assert lowered["answer"] == "Refused: restart_deployment is not an allowed call."
    assert cases["lowered to rung 1; the model asks to read"]["tool_calls"] == {"get_pod_status": 1}
    assert cases["an override of rung 4, above the manifest's 3"]["rung"] == 3
    for name in ("a malformed override (rung: one)", "an override that isn't YAML"):
        assert cases[name]["started"] is False and cases[name]["model_calls"] == 0
    assert cases["override removed; the model asks to restart"]["tool_calls"] == {"restart_deployment": 1}


def test_every_lever_left_its_change_record():
    changes = DRILLS["changes"]
    levers = [c["lever"] for c in changes]
    assert levers.count("kill switch, gateway half") == levers.count("kill switch released") == 5
    assert levers.count("rung down") == levers.count("rung restored") == 1
    for change in changes:
        at, due = datetime.fromisoformat(change["at"]), datetime.fromisoformat(change["document_by"])
        assert due - at == timedelta(hours=24)
        assert (change["kind"], change["authority"], change["by"], change["review"]) == \
            ("emergency", "on-call lead", "oncall.lead@larkspur.example", "the next board meeting")


@pytest.mark.parametrize("path", sorted(RESULTS.iterdir()), ids=lambda p: p.name)
def test_no_path_key_or_password_of_this_machine(path):
    text = path.read_text(encoding="utf-8")
    for pattern in (r"(?i)mykha", r"(?i)appdata", r"(?i)c:[\\/]+users", r"sk-[A-Za-z0-9]{12,}",
                    r"postgres(?:ql)?://[^<\s]"):
        assert not re.search(pattern, text), (path.name, pattern)
