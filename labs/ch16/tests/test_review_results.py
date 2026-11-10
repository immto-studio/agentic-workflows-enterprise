"""Step 9's committed results (results/2026-11-09/review): the two files are what the generator writes from the
committed files in another process, the review's headline numbers are the ledger's, step 6's, the register's, and W5's
ledger's, every section says what its figures are, the README's step 9 tables are the review's, no path of this
machine is in the files, and no module of review/ shares a name with another folder on the tests' path."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import monthly_review as review
import retirement

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-09" / "review"
STEP9 = "## The monthly review (step 9)"
FILES = ["review-2026-11.json", "review-2026-11.md"]


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads((RESULTS / "review-2026-11.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page() -> str:
    return (RESULTS / "review-2026-11.md").read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.fixture(scope="module")
def fresh(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("review")
    env = {**os.environ, "PYTHONHASHSEED": "11", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, str(LAB / "review" / "monthly_review.py"), "--month", "2026-11", "--on", "2026-11-09",
                    "--out", str(out)], check=True, env=env, capture_output=True, cwd=str(LAB), timeout=600)
    return out


def test_the_committed_results_are_what_the_generator_writes_from_another_process(fresh):
    assert sorted(p.name for p in RESULTS.iterdir()) == FILES == sorted(p.name for p in fresh.iterdir())
    for name in FILES:
        assert (fresh / name).read_bytes() == (RESULTS / name).read_bytes().replace(b"\r\n", b"\n"), name


def test_the_review_is_for_the_month_and_the_date_from_the_committed_files(data):
    assert (data["month"], data["on"], data["workflows"]) == ("2026-11", "2026-11-09", ["w1", "w2", "w3", "w4", "w5"])
    assert data["sources"]["ledger"] == "labs/ch16/results/2026-11-03/ledger.json"
    assert data["sources"]["slo"] == "labs/ch16/results/2026-11-09/slo"
    assert data["sources"]["drills"] == "labs/ch16/results/2026-11-03/budget/drills.json"
    assert data["sources"]["changes"] == "labs/ch16/results/2026-11-09/lifecycle/changes.jsonl"
    assert data["sources"]["w5_ledger"] == "workflows/w5-drift/eval/results/2026-11-03/after-review/nights-gpt-oss-20b/ledger.json"
    for value in data["sources"].values():
        for path in (value if isinstance(value, list) else [value]):
            assert (LAB.parents[1] / path).exists(), path


def test_cost_per_run_and_the_month_are_the_ledgers(data):
    ledger = json.loads(Path(LAB.parents[1], data["sources"]["ledger"]).read_text(encoding="utf-8"))
    r = data["sections"]["runs_and_cost_per_run"]
    rows = {w["workflow"]: w for w in r["rows"]}
    assert r["reference_model"] == "gpt-oss-20b"
    assert rows["w2"]["pct_of_per_run_usd"] == {"median": 0.0374208, "p95": 0.0905856}
    assert rows["w5"]["pct_of_per_run_usd"] == {"median": 0.2863008, "p95": 0.7093696}
    assert {w: rows[w]["runs_kept"] for w in rows} == {"w1": 75, "w2": 135, "w3": 48, "w4": 48, "w5": 33}
    assert {w: rows[w]["runs_a_month"] for w in rows} == {"w1": 6000.0, "w2": 43029.93, "w3": 300.0, "w4": 200.0, "w5": 34.0}
    assert r["highest_median"] == {"workflow": "w5", "pct": 0.2863008}
    assert r["highest_p95"] == {"workflow": "w5", "model": "gemma4-12b", "pct": 2.836384}
    for row in r["by_model"]:
        source = next(p for p in ledger["per_run"] if (p["workflow"], p["model"]) == (row["workflow"], row["model"]))
        assert row["cost_per_run_usd"]["median"] == source["cost_usd"]["median"]
    jd = r["judge"]
    assert (jd["calls"], jd["runs"], jd["prompt_tokens"], jd["completion_tokens"]) == (1439, 3, 1_231_927, 338_238)
    assert jd["thinking"] == {"gemma4-12b": False, "gpt-oss-20b": "model default"}
    rows = {(w["workflow"], w["judge"]): (w["judgments"], w["basis"], w["ratio"]["completion"], w["ratio"]["total"],
                                          w["completion_over"]) for w in jd["rows"]}
    assert rows[("w1", "gpt-oss-20b")] == (171, "measured", 1.3844, 0.3303, 117)
    assert rows[("w2", "gpt-oss-20b")] == (90, "measured", 1.8279, 0.3743, 84)
    assert rows[("w3", "gemma4-12b")] == (69, "stand-in", 0.0424, 0.0802, 0)
    assert rows[("w4", "gpt-oss-20b")] == (32, "stand-in", 3.5954, 3.6135, 27)
    assert rows[("w5", "gpt-oss-20b")] == (274, "measured", 2.9562, 1.9485, 254)
    assert rows[("w5", "gemma4-12b")] == (362, "measured", 0.0387, 0.7705, 0)
    assert len(jd["rows"]) == 9 and all(w["judge"] != "both" for w in jd["rows"])
    assert sum(w["judgments"] for w in jd["rows"]) == 1439  # every judgment is in one row
    c = jd["conclusion"]
    # ch15:156 for completion tokens, in total: gpt-oss-20b, thinking at the model's default, is above the output's
    # in each workflow it judged (W3 had no such judge); Gemma 4 12B, thinking off, is above it in none
    assert (c["thinking_on"], c["thinking_off"]) == (["gpt-oss-20b"], ["gemma4-12b"])
    assert c["completion_in_total"]["gpt-oss-20b"] == {"above": ["w1", "w2", "w4", "w5"], "not_above": []}
    assert c["completion_in_total"]["gemma4-12b"]["above"] == []
    assert c["not_judged_by"] == {"gemma4-12b": {}, "gpt-oss-20b": {"w3": ["gemma4-12b"]}}
    assert c["all_tokens_in_total"]["gpt-oss-20b"]["above"] == ["w4", "w5"]  # a separate finding, in all tokens
    assert c["all_tokens_in_total"]["gemma4-12b"]["above"] == ["w4"]
    assert ledger["judge"]["conclusion"] == c  # the review reads the ledger's judge section
    m = {w["workflow"]: w for w in data["sections"]["month_against_budget"]["rows"]}
    assert {w: m[w]["pct_of_per_month_usd"] for w in m} == {"w1": 1.440753, "w2": 4.506257, "w3": 0.042508, "w4": 0.006257,
                                                             "w5": 0.111623}
    assert m["w2"]["guardrail_pct"] == 63.029073 and m["w2"]["pct_range_over_kept_runs"] == [4.334428, 4.880808]
    assert data["sections"]["month_against_budget"]["largest"] == {"workflow": "w2", "pct": 4.506257}
    sh = data["sections"]["shared_lines"]
    assert sh["tenants"] == ["w1", "w2", "w3"] and sh["gpu"]["idle_share"] == pytest.approx(0.999664, abs=1e-6)
    assert {w["workflow"]: w["fixed_pct_of_per_month_usd"] for w in sh["rows"]}["w2"] == 189.68845
    assert sh["fixed"]["priced_usd"] == 466.5416 and len(sh["fixed"]["parameters"]) == 4


def test_the_error_budget_and_the_incidents_are_step_6s(data):
    e = data["sections"]["error_budget"]
    policy = json.loads((LAB / "results" / "2026-11-09" / "slo" / "policy.json").read_text(encoding="utf-8"))
    month = json.loads((LAB / "results" / "2026-11-09" / "slo" / "month.json").read_text(encoding="utf-8"))
    for a in e["simulated"]:
        account = policy["accounts"][a["workflow"]][a["sli"]]
        assert (a["bad"], a["budget_events"]) == (account["bad"], account["budget_events"])
        assert a["spent_at"] == review.with_year(account["spent_at_clock"], month["start"], account["spent_at"])
        assert a["left"] == pytest.approx(1 - account["bad"] / account["budget_events"], abs=1e-4)
    assert [(a["workflow"], a["sli"]) for a in e["spent"]] == [("w1", "success"), ("w2", "success"), ("w3", "success"),
                                                               ("w3", "outcome"), ("w4", "success")]
    assert [a["spent_at"] for a in e["spent"]] == ["Sat 30 Jan 2027 21:56", "Sun 17 Jan 2027 04:24", "Fri 22 Jan 2027 21:38",
                                                   "Wed 20 Jan 2027 11:18", "Thu 28 Jan 2027 18:00"]
    measured = {(a["workflow"], a["sli"]): a for a in e["measured"]}
    assert measured[("w3", "success")]["good"] == 40 and measured[("w3", "success")]["valid"] == 48
    assert ("w1", "outcome") not in measured and measured[("w4", "outcome")]["valid"] == 0
    i = data["sections"]["incidents"]
    # O-D5's controls are not evaluated by anything in the lab, so an empty list is not a count of zero
    assert i["design"] == "with-probe" and i["basis"]["control_breaches"] == "not evaluated"
    assert {k: v for k, v in i["control_breaches"].items() if k != "why"} == {"status": "not evaluated", "kept_runs": [],
                                                                               "simulated_month": []}
    assert i["control_breaches"]["why"] == review.CONTROLS_WHY
    assert [ev["id"] for ev in i["events"]] == ["provider-outage", "throttled-hour", "model-regression", "self-hosted-down",
                                                "w4-records-refused"]
    assert {ev["id"]: ev["symptom"] for ev in i["events"]}["throttled-hour"] == review.NO_SYMPTOM
    regression = next(ev for ev in i["events"] if ev["id"] == "model-regression")
    assert regression["first_alert"]["scope"] == "w2" and regression["first_alert"]["start"] == "Wed 20 Jan 2027 10:30"
    assert (regression["start"], regression["end"]) == ("Wed 20 Jan 2027 10:00", "Thu 04 Feb 2027 00:00")
    assert [p["action"] for p in regression["policy"]] == ["freeze", "rung down"]
    assert [a["change"] for a in i["policy_actions"] if a["change"]] == ["EC-SIM-01"]
    assert next(a for a in i["alerts_by_scope"] if a["scope"] == "platform")["pages"] == {"throttled-hour": 1}


def test_the_months_records_are_the_drills_and_the_remap(data):
    b = data["sections"]["budget_events_and_switches"]
    assert [a["event"] for a in b["alerts"]] == ["threshold_crossed", "soft_budget_crossed", "budget_crossed", "budget_crossed"]
    assert b["stop"]["status"] == 422 and b["stop"]["first_stopped_run"] == 5 and b["stop"]["short_of_budget_usd"] == 0.244368
    assert [c["change"] for c in b["changes"]] == ["EC-DRILL-01", "EC-DRILL-02", "EC-DRILL-03", "EC-DRILL-04", "EC-DRILL-05",
                                                   "EC-DRILL-RUNG", "CH-20261109-01"]
    assert sum(c["lines"] for c in b["changes"]) == 13
    remap = b["changes"][-1]
    assert remap["workflow"] == "larkspur-chat" and remap["run"] == "the upgrade path, run once"
    assert remap["steps"] == [{"lever": "alias remap, back",
                               "from": "local-gpt-oss-20b-chat (weight 3), candidate-gemma4-12b-chat (weight 1)",
                               "to": "local-gpt-oss-20b-chat"}]


def test_the_window_is_the_registers_on_the_reviews_date(data):
    t = data["sections"]["retirement"]
    assert t["on"] == "2026-11-09" and t["windows"] == {"alert_days": 90, "review_days": 180}
    assert [(r["model"], r["days_left"]) for r in t["rows"]] == [("Claude 3 Haiku", 4), ("Llama 3 70B Instruct", 141),
                                                                 ("text-multilingual-embedding-002", 143),
                                                                 ("gpt-4.1-mini", 156), ("gpt-4o", 156)]
    assert [r["model"] for r in t["rows"] if r["pinned"]] == ["text-multilingual-embedding-002", "gpt-4o"]
    assert (t["pages"], t["tickets"], t["review_rows"]) == (0, 1, 5)
    assert [u["model"] for u in t["unscheduled"] if u["earliest_passed"]] == ["Amazon Nova Lite", "Mistral Large (24.02)"]
    fresh = retirement.evaluate(__import__("datetime").date(2026, 11, 9))
    assert (fresh["pages"], fresh["tickets"], fresh["review_rows"]) == (t["pages"], t["tickets"], t["review_rows"])


def test_w5s_savings_are_its_ledgers_and_the_cost_to_find_is_priced(data):
    v = data["sections"]["w5_savings"]
    assert v["savings"] == {"proposed_share_of_spend": 0.0077, "realized_share_of_spend": 0.0033,
                            "realized_share_of_proposed": 0.4277, "realized_findings": 1}
    assert v["pull_requests"]["open"] == 14 and v["pull_requests"]["merged"] == 1 and v["pull_requests"]["closed"] == 0
    assert v["findings"]["seen"] == 16 and v["findings"]["with_estimate"] == 6 and v["findings"]["suppressed"] == 1
    assert v["nights"] == 3 and v["night_kinds"] == {"budget": 1, "schedule": 2}
    assert (v["agent"]["gateway_calls"], v["agent"]["prompt_tokens"], v["agent"]["completion_tokens"]) == (31, 19577, 19358)
    priced = 19577 * 0.064 / 1e6 + 19358 * 0.256 / 1e6
    assert v["priced"]["deployment"] == "nova-lite-ca"
    assert v["priced"]["pct_of_per_month_usd"] == pytest.approx(priced, abs=1e-6)  # W5's per_month_usd is 100
    assert v["priced"]["share_of_realized_saving"] == pytest.approx(priced / 96.0, abs=1e-8)
    # W5-D10: shares only, no amount in the data (the cost to find, a night's cost, or a saving)
    assert set(v["priced"]) == {"deployment", "pct_of_per_month_usd", "share_of_realized_saving"}
    assert set(v["per_night"]) == {"model", "pct_of_per_run_usd"}
    assert v["range_over_kept_runs"]["runs"] == 6 and v["range_over_kept_runs"]["completion_tokens"] == [18696, 51682]
    assert all(o["same_savings"] for o in v["other_kept_runs"])
    assert v["per_night"] == {"model": "gpt-oss-20b", "pct_of_per_run_usd": {"median": 0.2863008, "p95": 0.7093696}}


def test_every_section_says_what_its_figures_are(data, page):
    for name, section in data["sections"].items():
        marks = {k: v for k, v in section["basis"].items() if k != "note"}
        for mark in marks.values():
            # the legend's five words, or the controls' own: something that was not evaluated, or that a file lists
            assert any(word in mark for word in data["legend"]) or mark in ("not evaluated", "listed"), (name, mark)
    headings = [line for line in page.splitlines() if line.startswith("## ")]
    assert headings == ["## 1. Runs and cost per run", "## 2. The month against the monthly budget", "## 3. The shared lines",
                        "## 4. The error budget left", "## 5. Incidents",
                        "## 6. Budget events and switches pulled in November 2026",
                        "## 7. Models within 180 days of retirement on 9 November 2026",
                        "## 8. W5's savings, and what finding them cost", "## Sources"]
    assert page.count("Basis: ") == 8 and "(simulated)" in page and "(measured)" in page and "(estimated)" in page
    assert "(USD, priced)" in page and list(data["legend"]) == ["measured", "priced", "estimated", "simulated", "recorded"]
    assert "Basis: events simulated; control breaches not evaluated." in page and "0 control breaches" not in page
    assert "Basis: month estimated; mean cost per run priced." in page


def test_the_judge_paragraph_cites_chapter_15s_sentence_and_claims_it_in_tokens(page):
    paragraph = next(line for line in page.splitlines() if line.startswith("Chapter 15's judge is in the ledger"))
    assert ("Chapter 15 says (ch15:156) that a judge that thinks before it answers writes more tokens than the answer it "
            "judges.") in paragraph
    assert ("In completion tokens, in total, gpt-oss-20b (thinking at the model's default) wrote more than the outputs it "
            "read in every workflow it judged: W1 (1.38), W2 (1.83), W4 (3.60, on the stand-in) and W5 (2.96). The sentence "
            "holds as written, for completion tokens, wherever that judge judged; W3 was judged by Gemma 4 12B alone."
            ) in paragraph
    assert "these are token figures and not prices" in paragraph
    assert "Gemma 4 12B (thinking off) wrote, in completion tokens and in total, fewer than the outputs it read" in paragraph
    for stale in ("needs that qualification", "holds in part", "than every output it judges", "costs more than the answer"):
        assert stale not in page, stale


def test_w5s_section_prints_shares_and_no_amount(page):
    section = page.split("## 8. W5's savings, and what finding them cost")[1].split("## Sources")[0]
    assert "USD" not in section and "dollars" not in section
    assert "0.00621% of W5's monthly budget and 0.00647% of the saving it realized" in section


@pytest.mark.parametrize("month, word", [("2026-12", "December 2026"), ("2026-10", "October 2026")])
def test_another_month_writes_both_files_and_says_w5_ran_no_night(tmp_path, month, word):
    """The committed files carry no December or October for W5, the alerts, or the change records: the review says so
    where it reads them, and writes the page and its JSON, as it does for any month."""
    env = {**os.environ, "PYTHONHASHSEED": "11", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, str(LAB / "review" / "monthly_review.py"), "--month", month, "--on", "2026-11-09",
                           "--out", str(tmp_path)], check=True, env=env, capture_output=True, text=True, encoding="utf-8",
                          cwd=str(LAB), timeout=600)
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"review-{month}.json", f"review-{month}.md"], done.stdout
    page = (tmp_path / f"review-{month}.md").read_text(encoding="utf-8")
    assert f"W5 ran no night and no alarm in {word}" in page
    assert f"## 6. Budget events and switches pulled in {word}" in page
    assert f"No budget alert was received in {word}." in page and f"No change record is dated in {word}." in page
    assert json.loads((tmp_path / f"review-{month}.json").read_text(encoding="utf-8"))["sections"]["w5_savings"]["nights"] == 0


def test_a_missing_input_stops_the_review_before_anything_is_written(tmp_path):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    out = tmp_path / "nothing"
    # a results folder with no ledger.json stands in for the committed one: the generator reads it by its name
    code = ("import sys, datetime as dt; sys.path.insert(0, 'review'); import monthly_review as r; "
            f"s = r.Sources.committed(r.Path({str(tmp_path)!r})); r.write(r.Path({str(out)!r}), '2026-11', dt.date(2026, 11, 9), s)")
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8",
                          cwd=str(LAB), timeout=600)
    assert done.returncode != 0 and "FileNotFoundError" in done.stderr
    assert not out.exists()


def test_the_readmes_step_9_tables_are_the_reviews(page):
    readme = (LAB / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    section, rows = "", []
    for line in readme.splitlines():
        if line.startswith("## "):
            section = line
        if section == STEP9 and line.startswith("|") and not line.startswith("|---"):
            rows.append(line)
    assert len(rows) >= 30
    for row in rows:
        assert row in page.splitlines(), row


def test_no_path_or_name_of_this_machine_in_the_results():
    for path in RESULTS.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]|AppData|Users[\\/]|/tmp/|<temp>|<home>", text), path.name


def test_no_module_of_step_9_shares_a_name_with_another_folder_on_the_tests_path():
    mine = {p.stem for p in (LAB / "review").glob("*.py")}
    assert mine == {"monthly_review"}
    for folder in ("ledger", "collector", "budget", "capacity", "slo", "cloud", "lifecycle"):
        assert not mine & {p.stem for p in (LAB / folder).glob("*.py")}, folder
    ch15 = LAB.parent / "ch15"
    for folder in ("ci", "layers", "cases", "judge", "labels", "redteam", "release"):
        assert not mine & {p.stem for p in (ch15 / folder).glob("*.py")}, folder
