"""Step 6's committed results: what run_slo.py writes, the same bytes from two processes, every simulated file marked,
the two cautions of fact sheet 8.9 in the month, fig-16-03's data and the dashboard, and the README's tables."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import run_slo
import slis

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-09" / "slo"
STEP6 = "## SLOs, the simulated month, the alerts and the playbook (step 6)"


def load(name: str):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fresh(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("slo")
    env = {**os.environ, "PYTHONHASHSEED": "7", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, str(LAB / "slo" / "run_slo.py"), "--out", str(out)], check=True, env=env,
                   capture_output=True, cwd=str(LAB), timeout=600)
    return out


def test_the_committed_results_are_what_run_slo_writes_from_another_process(fresh):
    assert sorted(p.name for p in RESULTS.iterdir()) == sorted(run_slo.FILES) == sorted(p.name for p in fresh.iterdir())
    for name in run_slo.FILES:
        assert (fresh / name).read_bytes() == (RESULTS / name).read_bytes().replace(b"\r\n", b"\n"), name


def test_the_summary_is_what_summarize_writes_from_the_committed_files(tmp_path):
    for name in run_slo.FILES:
        if name != "summary.md":
            (tmp_path / name).write_bytes((RESULTS / name).read_bytes().replace(b"\r\n", b"\n"))
    run_slo.summarize(tmp_path)
    assert (tmp_path / "summary.md").read_text(encoding="utf-8") == \
        (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_every_simulated_file_says_so_and_the_kept_runs_say_measured():
    assert load("kept.json")["measured"] is True and load("kept.json")["simulated"] is False
    for name in ("month.json", "alerts.json", "policy.json", "probe.json", "fig-16-03.json"):
        data = load(name)
        assert data["simulated"] is True and next(iter(data)) == "simulated", name
    for name in ("policy-actions.jsonl", "probe-costlines.jsonl"):
        lines = [json.loads(line) for line in (RESULTS / name).read_text(encoding="utf-8").splitlines()]
        assert lines and all(line["simulated"] is True for line in lines), name
    assert "SIMULATED" in (RESULTS / "summary.md").read_text(encoding="utf-8")


def test_the_green_probe_hides_w3s_real_failures_that_its_own_traffic_pages():
    """Fact sheet 8.9's first caution, in the month: the weekend without the self-hosted path failed W3's Restricted
    incidents while its probe, on larkspur-chat, stayed green."""
    month, alerts = load("month.json"), load("alerts.json")
    assert month["workflows"]["w3"]["bad_by"]["self-hosted-down"] == 5
    episodes = alerts["episodes"]
    own = [a for a in episodes["own-traffic"] if a["scope"] == "w3" and a["cause"] == "self-hosted-down"]
    probed = [a for a in episodes["with-probe"] if a["scope"] == "w3" and a["cause"] == "self-hosted-down"]
    assert any(a["action"] == "page" for a in own) and probed == []
    assert alerts["by_event"]["self-hosted-down"]["with-probe"]["first"]["scope"] == "w1"  # W1's own traffic pages


def test_the_group_misses_w4_failing_completely_that_its_own_alerts_page():
    """Fact sheet 8.9's second caution: a day of W4's packs refused is no event for W1, W3 and W4 grouped."""
    by_event = load("alerts.json")["by_event"]["w4-records-refused"]
    assert by_event["grouped"]["action"] == "none"
    assert by_event["own-traffic"]["action"] == by_event["with-probe"]["action"] == "page"
    assert load("month.json")["workflows"]["w4"]["bad_by"]["w4-records-refused"] == 3


def test_the_month_table_and_the_policy_count_every_sli_by_one_rule():
    """slos.yaml, in_the_month: both place a run when it ends and an outcome when a person decides, so the month's
    SLI ratios and the policy's accounts agree on every valid and bad count."""
    month, policy = load("month.json"), load("policy.json")
    for workflow, accounts in policy["accounts"].items():
        for sli, account in accounts.items():
            ratio = month["workflows"][workflow]["slis"][sli]
            assert (account["valid"], account["bad"]) == (ratio["valid"], ratio["valid"] - ratio["good"]), (workflow, sli)


def test_the_alerts_and_the_policy_cite_only_what_the_month_holds():
    alerts, policy, month = load("alerts.json"), load("policy.json"), load("month.json")
    names = {e["id"] for e in month["injected"]} | {"baseline"}
    for design in alerts["episodes"].values():
        for a in design:
            assert a["cause"] in names and set(a["bad_by_cause"]) <= names
    for action in policy["actions"]:
        account = policy["accounts"][action["workflow"]][action["sli"]]
        assert account["spent_at"] is not None and account["bad"] >= account["budget_events"]
    assert alerts["proposed"] == "with-probe"
    # every rule carries the workbook's short window, a twelfth of its long one (fact sheet 9.4)
    assert [r["short_window_hours"] * 3600 for r in alerts["rules"]] == [300, 1800, 21600]


def test_fig_16_03_is_the_workflow_whose_month_shows_the_most():
    fig = load("fig-16-03.json")
    scores = fig["chosen_because"]
    assert fig["workflow"] == max(scores, key=lambda w: sum(scores[w].values())) == "w3"
    assert len(fig["series"]) == fig["hours"] == 720 and fig["design"] == "with-probe" and fig["with_probe"]
    first, last = fig["series"][0], fig["series"][-1]
    assert set(fig["targets"]) == {"success", "latency", "outcome"} <= set(first)
    assert last["success"]["valid_to_date"] == load("month.json")["workflows"]["w3"]["slis"]["success"]["valid"]
    assert {a["action"] for a in fig["policy"]} == {"freeze", "rung down", "budget spent"}
    dashboard = yaml.safe_load((LAB / "slo" / "dashboard.yaml").read_text(encoding="utf-8"))
    assert fig["panels"] == [p["id"] for p in dashboard["workflow_row"]]


def test_the_dashboard_lists_every_panel_with_its_source_and_the_foundry_panel_as_an_open_fact():
    dashboard = yaml.safe_load((LAB / "slo" / "dashboard.yaml").read_text(encoding="utf-8"))
    ids = [p["id"] for p in dashboard["workflow_row"]]
    assert ids[:6] == ["slis", "budget-left", "burn-rates", "alerts", "budget-events", "owner-429s"]
    for panel in dashboard["workflow_row"] + dashboard["platform_row"]:
        assert panel["source"] and panel["status"] in ("emitted", "derived", "open"), panel["id"]
    foundry = next(p for p in dashboard["platform_row"] if p["id"] == "foundry-sessions")
    assert foundry["status"] == "open" and "names no metric" in foundry["source"]
    assert [p["id"] for p in dashboard["platform_row"] + dashboard["workflow_row"] if p["status"] == "open"] == \
        ["foundry-sessions"]


def test_the_probes_cost_comes_from_the_kept_tokens_and_its_lines_are_the_ledgers_shape():
    probes = load("probe.json")["cases"]
    assert {w: (r["input_tokens"], r["output_tokens"]) for w, r in probes.items()} == \
        {"w1": (404, 44), "w3": (981, 43), "w4": (200, 253)}
    for r in probes.values():
        assert r["tokens_in_month"] == r["served"] * (r["input_tokens"] + r["output_tokens"])
    assert probes["w4"]["over_workflow_tokens"] > 4
    line = json.loads((RESULTS / "probe-costlines.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert {"run_id", "workflow", "kept_run", "case", "alias", "input_tokens", "output_tokens", "source"} <= set(line)


def test_the_readmes_step_6_tables_are_the_summarys():
    readme = (LAB / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    summary = (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    section, rows = "", []
    for line in readme.splitlines():
        if line.startswith("## "):
            section = line
        if section == STEP6 and line.startswith("|") and not line.startswith("|---"):
            rows.append(line)
    assert len(rows) >= 40
    for row in rows:
        assert row in summary, row


def test_no_path_or_name_of_this_machine_in_the_results():
    for path in RESULTS.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:[\\/]|AppData|Users[\\/]|/tmp/", text), path.name
        assert "slo-policy-" not in text, path.name  # the dry run's temporary folder


def test_no_module_of_step_6_shares_a_name_with_another_folder_on_the_tests_path():
    mine = {p.stem for p in (LAB / "slo").glob("*.py")}
    for folder in ("ledger", "collector", "budget", "capacity"):
        assert not mine & {p.stem for p in (LAB / folder).glob("*.py")}, folder
    assert slis.WORKFLOWS == ("w1", "w2", "w3", "w4", "w5")
