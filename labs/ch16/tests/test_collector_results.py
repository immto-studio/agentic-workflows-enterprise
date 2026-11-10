"""The local run's committed results: the summary is what analyze.py writes from them, and they show what step 3
claims: every run in the right stores under one trace id, no content, the right decisions, the delay, the headers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import analyze
import fake_otlp
import policies

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-03" / "collector"
GENERATED = ("summary.md", "collector.json")


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads((RESULTS / "collector.json").read_text(encoding="utf-8"))


def test_the_summary_is_what_analyze_writes_from_the_committed_files(tmp_path: Path) -> None:
    copy = tmp_path / "collector"
    shutil.copytree(RESULTS, copy)
    for name in GENERATED:
        (copy / name).unlink()
    analyze.summarize(copy)
    for name in GENERATED:
        fresh = (copy / name).read_text(encoding="utf-8")
        assert fresh == (RESULTS / name).read_text(encoding="utf-8").replace("\r\n", "\n"), name


def test_every_kept_run_reached_the_file_and_both_fakes_with_the_same_spans(data: dict) -> None:
    for phase in data["phases"].values():
        assert phase["other_traces"] == [] and phase["collector_exit"] == 0
        for row in phase["rows"]:
            assert row["kept"] == {store: row["expected"]["kept"] for store in ("file", "cloudwatch", "langfuse")}, row["case"]
            if row["expected"]["kept"]:
                assert row["same_spans"], row["case"]
    every = data["phases"]["every-run"]["rows"]
    assert len(every) == 25 and all(r["expected"]["kept"] for r in every)


def test_one_trace_id_joins_the_harness_log_the_server_log_and_the_cost_lines(data: dict) -> None:
    for phase in data["phases"].values():
        for row in phase["rows"]:
            # a run that raised logs its tools_verified line and no answer: chapter 5's harness writes none
            assert row["harness_lines"] >= (1 if row["kind"] == "failed" else 2) and row["cost_lines"] >= 1, row["case"]
            assert (row["server_lines"] > 0) == (row["tool_calls"] > 0), row["case"]
            if row["expected"]["kept"]:
                assert row["gateway_spans"] == row["cost_lines"], row["case"]


def test_the_runs_did_what_they_were_made_for(data: dict) -> None:
    for phase in data["phases"].values():
        assert all(row["passed"] for row in phase["rows"])
        made = {row["kind"]: row for row in phase["rows"] if row["kind"] in analyze.SPECIALS}
        assert set(made) == set(analyze.SPECIALS)
        for kind in ("refused", "slow", "over-budget"):
            assert made[kind]["expected"]["matched"] == [kind]
        assert made["fallback"]["expected"]["matched"] == ["failed", "fallback"]  # its primary's failure has a span
        assert made["failed"]["expected"]["matched"] == ["failed"]
        assert made["over-budget"]["cost_usd"] >= 0.50 and made["slow"]["seconds"] > 12


def test_the_collector_decided_as_the_policies_say_and_recorded_the_share(data: dict) -> None:
    for name, phase in data["phases"].items():
        for row in phase["rows"]:
            if row["expected"]["kept"]:
                assert row["recorded_policy"] == [row["expected"]["policy"]], (name, row["case"])
                assert row["recorded_share"] == [row["expected"]["share"]], (name, row["case"])
        assert phase["hashing"]["same"]
        for policy in phase["by_policy"]:
            assert policy["collector_count"] == policy["matched"], (name, policy["policy"])
    sampled = data["phases"]["sampled"]
    assert sampled["meta"]["share_percent"] == 10.0 and sampled["hashing"]["runs"] >= 90
    assert {s for p in sampled["by_policy"] if p["policy"] == policies.SHARE for s in p["shares"]} == {0.1}


def test_no_content_attribute_reached_any_store(data: dict) -> None:
    for name, phase in data["phases"].items():
        assert phase["content"]["before"].get("gen_ai.tool.call.arguments", 0) > 0
        assert phase["content"]["file"] == phase["content"]["cloudwatch"] == phase["content"]["langfuse"] == {}
        folder = RESULTS / name
        spans = fake_otlp.spans_from_file(folder / "spans.jsonl")
        spans += [s for f in ("langfuse.jsonl", "cloudwatch.jsonl") for r in analyze.read_jsonl(folder / f) for s in r["spans"]]
        assert spans and not [k for s in spans for k in s["attributes"] if policies.is_content(k)]
        assert not [k for s in spans for e in s["events"] for k in e["attributes"] if policies.is_content(k)]


def test_the_tail_sampler_holds_a_trace_for_its_decision_wait(data: dict) -> None:
    for phase in data["phases"].values():
        wait = phase["meta"]["decision_wait_s"]
        for key in ("collector_to_langfuse", "collector_to_cloudwatch"):
            spread = phase["delay"][key]
            assert wait <= spread["min"] and spread["max"] <= wait + 2.5, (key, spread)


def test_langfuse_got_basic_auth_the_v4_header_and_the_cost_and_cloudwatch_a_valid_signature(data: dict) -> None:
    for phase in data["phases"].values():
        lf, cw = phase["headers"]["langfuse"], phase["headers"]["cloudwatch"]
        assert lf["all_basic"] and lf["basic"] == ["pk-lab-dummy:sk-lab-dummy"] and lf["all_ingestion_version"]
        assert lf["paths"] == [fake_otlp.LANGFUSE_PATH] and lf["errors"] == 0
        assert cw["verified"] == cw["requests"] > 0 and cw["scopes"] == ["us-east-2/xray/aws4_request"] and cw["errors"] == 0
        assert phase["langfuse_cost"]["equal"] == phase["langfuse_cost"]["spans"] > 0
        assert phase["langfuse_cost"]["elsewhere"] == 0


def test_the_readme_s_step_3_tables_are_the_summary_s() -> None:
    from test_results import readme_rows

    summary = (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    _, rows, _ = readme_rows()
    assert len(rows) >= 20
    for row in rows:
        assert row in summary, row


def test_no_path_or_name_of_this_machine_is_committed() -> None:
    for path in RESULTS.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for fragment in ("C:\\\\", "C:/", "AppData", "\\\\Users\\\\", "/Users/", "scratchpad"):
                assert fragment not in text, (path.name, fragment)
