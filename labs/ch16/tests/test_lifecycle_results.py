"""Step 8's committed results: every file there, the summary what lifecycle_summary writes from them, the README's
step 8 tables the summary's, the register check clean with every digest matched, the retirement file what the code
computes for its dates, the gate's rows W2's checks, the canary's counts adding up, the decision recomputed from the
files, the remap matching the decision, fig-16-04's stages with the run's numbers, no path of this machine, and no
module name shared with another folder."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import yaml

import canary
import decision as deciding
import lifecycle_summary
import measure  # chapter 15's, on the path through canary
import register as reg
import retirement

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-09" / "lifecycle"
LIFECYCLE = LAB / "lifecycle"
STEP8 = "## The model register and the upgrade path (step 8)"
CONFIGS = {"promote": "litellm.promoted.yaml", "remap back": "litellm.restored.yaml"}


def load(name: str):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def lines(name: str) -> list[dict]:
    return [json.loads(x) for x in (RESULTS / name).read_text(encoding="utf-8").splitlines() if x.strip()]


def test_every_file_is_there_and_nothing_else():
    decided = load("decision.json")["decision"]
    expected = set(lifecycle_summary.FILES) | ({CONFIGS[decided]} if decided in CONFIGS else set())
    assert {p.name for p in RESULTS.iterdir()} == expected


def test_the_summary_is_what_the_module_writes_from_the_committed_files(tmp_path):
    for path in RESULTS.iterdir():
        if path.name != "summary.md":
            (tmp_path / path.name).write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    lifecycle_summary.write(tmp_path)
    assert (tmp_path / "summary.md").read_text(encoding="utf-8") == \
        (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_readmes_step_8_tables_are_the_summarys():
    readme = (LAB / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    summary = (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    section, rows = "", []
    for line in readme.splitlines():
        if line.startswith("## "):
            section = line
        if section == STEP8 and line.startswith("|") and not line.startswith("|---"):
            rows.append(line)
    assert len(rows) >= 25
    for row in rows:
        assert row in summary, row


def test_the_register_check_found_no_problem_and_every_digest_matched():
    check = load("register-check.json")
    assert check["problems"] == [] and check["models"] == 13 and check["deployments"] == 14
    assert check["by_cloud"] == {"aws": 6, "google": 2, "azure": 2, "local": 3} and check["pinned"] == 6
    assert sorted(check["unversioned_pins"]) == ["aws-claude-haiku-5-5", "aws-claude-sonnet-5-5"]
    assert check["digests"]["ollama"] == "0.40.13"
    assert len(check["digests"]["models"]) == 3 and all(r["matches"] and r["served"] for r in check["digests"]["models"])
    assert reg.check(reg.load()) == []


def test_the_retirement_file_holds_the_three_dates_as_the_code_computes_them():
    stored = load("retirement.json")
    assert list(stored["dates"]) == ["2026-11-09", "2027-02-01", "2027-05-01"]
    for day, result in stored["dates"].items():
        assert json.loads(json.dumps(retirement.evaluate(dt.date.fromisoformat(day)))) == result
    before, inside, past = (stored["dates"][d] for d in stored["dates"])
    assert before["tickets"] == 1 and before["pages"] == 0  # gpt-4o's Legacy notice; nothing within 90 days that Larkspur runs on
    assert inside["tickets"] == 3 and inside["pages"] == 0  # gpt-4o and the embedding model within 90 days, and the notice
    assert past["pages"] == 2  # both retired and still pinned
    assert stored["rules"]["windows"] == {"alert_days": 90, "review_days": 180}


def test_the_gate_rows_are_w2s_checks_and_the_pins_say_what_a_remap_changes():
    gate = load("gate.json")
    assert [r["check"] for r in gate["rows"]] == measure.case_checks("w2")
    assert gate["verdict"] == ("regressed" if gate["regressed"] else "held")
    assert gate["regressed"] == [r["check"] for r in gate["rows"] if r["verdict"] == "regressed"]
    assert gate["held"] + len(gate["regressed"]) + gate["not_gated"] == len(gate["rows"])
    assert gate["pins"]["w2"]["aliases"]["larkspur-chat"] == "ollama_chat/gemma4:12b"
    assert gate["pins"]["w2"]["aliases"]["larkspur-chat-restricted"] == "ollama_chat/gpt-oss:20b"
    assert any("alias map changed" in p for p in gate["pin_problems"]["w2"])
    assert any("holds no digest" in p for p in gate["pin_problems"]["w2"])
    assert any("judge's model changed" in p for p in gate["pin_problems"]["the judge"])
    assert gate["whole_gate"]["passed"] is False and any("partial" in p for p in gate["problems"])
    live = load(gate["live_result"])
    assert live["kind"] == "live" and live["run"]["complete"] is False and live["run"]["workflows"] == ["w2"]
    assert live["run"]["model"] == "gemma4-12b" and live["run"]["judge"] == "gpt-oss-20b"
    assert len(live["workflows"]["w2"]["cases"]) == 25
    for served in live["pins"]["workflows"]["w2"]["models"].values():
        assert served["server"] == "0.40.13" and reg.HEX64.match(served["digest"])
    assert gate["judge_tally"]["run"]["judged"] >= 15
    assert (RESULTS / "gate.md").read_text(encoding="utf-8").startswith("# The gate: live-w2-gemma4-12b.json against baseline.json")


def test_the_canarys_counts_add_up():
    result = load("canary.json")
    assert result["measured"] and result["complete"] and result["workflow"] == "w2" and result["threshold_s"] == 10
    arms = result["arms"]
    assert {a["arm"]: a["share"] for a in arms.values()} == {"control": 0.75, "candidate": 0.25}
    by_arm, groups = result["by_arm"], result["runs"]["by_group"]
    assert by_arm["control"]["calls"] + by_arm["candidate"]["calls"] == result["calls"]["total"]
    assert abs(by_arm["candidate"]["share_of_calls"] - 0.25) < 0.1
    assert sum(groups.values()) == result["runs"]["total"] == result["passes"] * result["cases_a_pass"]
    touched = by_arm["control"]["runs_touched"]["runs"] + by_arm["candidate"]["runs_touched"]["runs"]
    assert touched == result["runs"]["total"] - groups["none"] + groups["mixed"]
    assert by_arm["control"]["runs_pure"]["runs"] == groups["control"] and by_arm["candidate"]["runs_pure"]["runs"] == groups["candidate"]
    calls, runs = lines("canary-calls.jsonl"), lines("canary-runs.jsonl")
    assert len(runs) == result["runs"]["total"]
    assert sum(1 for c in calls if c["event"] == "call") == result["calls"]["total"]
    assert sum(1 for c in calls if c["event"] == "failed") == result["calls"]["failed"]
    assert all(set(r["arms"]) <= {"control", "candidate"} for r in runs)
    assert all(r["seconds_without_loads"] <= r["seconds"] for r in runs)
    swaps = result["server"]["swaps"]
    assert swaps["both_at_once"] is False and set(swaps["loads"]) <= {"gemma4:12b", "gpt-oss:20b"}
    assert result["calls"]["with_a_swap_during"] <= sum(swaps["loads"].values())
    for arm in ("control", "candidate"):
        t = by_arm[arm]["runs_touched"]
        assert t["latency_without_loads"]["good"] >= t["latency"]["good"]
        assert t["success"]["valid"] == t["runs"] - t["ends"].get("own_limit", 0)
    assert result["server"]["ollama"] == "0.40.13"


def test_the_decision_is_the_rule_on_the_files():
    stored, gate, result = load("decision.json"), load("gate.json"), load("canary.json")
    fresh = deciding.decide(gate["rows"], result["by_arm"], latency_key=stored["rule"]["latency_read_from"])
    for key in ("decision", "because", "rule", "gate", "slis"):
        assert fresh[key] == stored[key], key
    measured = deciding.decide(gate["rows"], result["by_arm"], latency_key="latency")
    assert stored["as_measured"]["decision"] == measured["decision"]
    assert stored["rule"]["latency_read_from"] == "latency_without_loads"
    assert stored["decision"] in (deciding.PROMOTE, deciding.BACK, deciding.EXTEND)


def test_the_remap_matches_the_decision_and_left_its_record():
    decided, remapped = load("decision.json")["decision"], load("remap.json")
    if decided == deciding.EXTEND:
        assert remapped["remapped"] is False and not (RESULTS / "changes.jsonl").exists()
        return
    assert remapped["remapped"] is True and remapped["config"] == CONFIGS[decided]
    written = yaml.safe_load((RESULTS / remapped["config"]).read_text(encoding="utf-8"))
    chat = [e for e in written["model_list"] if e["model_name"] == "larkspur-chat"]
    expected = "candidate-gemma4-12b-chat" if decided == deciding.PROMOTE else "local-gpt-oss-20b-chat"
    assert [e["model_info"]["id"] for e in chat] == [expected]
    assert [e["model_name"] for e in written["model_list"]].count("larkspur-chat-restricted") == 1
    if decided == deciding.BACK:  # the previous configuration, whole
        assert written == yaml.safe_load((LIFECYCLE / "litellm.current.yaml").read_text(encoding="utf-8"))
    record = remapped["record"]
    assert record["kind"] == ("planned" if decided == deciding.PROMOTE else "emergency")
    assert [d["id"] for d in record["from"]] == ["local-gpt-oss-20b-chat", "candidate-gemma4-12b-chat"]
    assert [d["id"] for d in record["to"]] == [expected]
    assert all(why in record["reason"] for why in load("decision.json")["because"])  # the decision's own reason
    assert lines("changes.jsonl") == [record]
    assert set(record["evidence"]) >= {"gate.json", "canary.json", "decision.json"}
    probe = remapped["probe"]
    assert probe["every_call_on_it"] is True and probe["deployments"] == [expected] and probe["calls"] >= len(probe["cases"])


def test_fig_16_04_has_the_paths_stages_with_the_runs_numbers():
    fig, design = load("fig-16-04.json"), yaml.safe_load((LIFECYCLE / "upgrade_path.yaml").read_text(encoding="utf-8"))
    assert fig["figure"] == "fig-16-04" and fig["measured"] is True and fig["simulated"] is False
    assert [s["id"] for s in fig["stages"]] == [s["id"] for s in design["stages"]] == \
        ["register", "staging", "canary", "decision", "remap", "after"]
    numbers = {s["id"]: s["numbers"] for s in fig["stages"]}
    result, decided = load("canary.json"), load("decision.json")
    assert numbers["register"]["models"] == 13 and numbers["register"]["candidate"] == "local-gemma4-12b"
    assert numbers["staging"]["checks"] == len(load("gate.json")["rows"])
    assert numbers["canary"]["runs"] == result["runs"]["total"] and numbers["canary"]["share"] == 0.25
    assert numbers["decision"]["decision"] == decided["decision"]
    assert numbers["after"]["ran"] is False


def test_no_path_or_name_of_this_machine_in_the_results():
    # A drive letter is one letter with nothing but a space, a quote or a line start before it; the `p:/` of a
    # loopback URL in the restored configuration is not one.
    for path in RESULTS.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]|AppData|Users[\\/]|/tmp/|<temp>|<home>|<localappdata>", text), path.name


def test_no_module_of_step_8_shares_a_name_with_another_folder_on_the_tests_path():
    mine = {p.stem for p in LIFECYCLE.glob("*.py")}
    for folder in ("ledger", "collector", "budget", "capacity", "slo", "cloud"):
        assert not mine & {p.stem for p in (LAB / folder).glob("*.py")}, folder
    ch15 = LAB.parent / "ch15"
    for folder in ("ci", "layers", "cases", "judge", "labels", "redteam", "release"):
        assert not mine & {p.stem for p in (ch15 / folder).glob("*.py")}, folder
    assert canary.ARMS == {"local-gpt-oss-20b-chat": "control", "candidate-gemma4-12b-chat": "candidate"}
