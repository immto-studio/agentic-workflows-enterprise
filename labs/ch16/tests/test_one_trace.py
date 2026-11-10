"""The follow-up to step 3b: one W3 incident and one W4 change through the Collector after each was made one trace
(companion #10 and #11). The committed results are what collector/one_trace.py writes from the committed files,
each case's spans form one tree under its harness's span with nothing elsewhere, and step 3b's rows for the same
cases had more than one root. None of these needs a model or the Collector."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import analyze
import one_trace

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-03" / "one-trace"
GENERATED = ("one-trace.json", "summary.md")
ROOTS = {"w3": "w3-harness: invoke_agent w3-incident", "w4-gpt-oss-20b": "scribe: invoke_agent change-management"}


def data() -> dict:
    return json.loads((RESULTS / "one-trace.json").read_text(encoding="utf-8"))


def test_the_summary_is_what_one_trace_writes_from_the_committed_files(tmp_path: Path) -> None:
    copy = tmp_path / "one-trace"
    shutil.copytree(RESULTS, copy)
    for name in GENERATED:
        (copy / name).unlink()
    one_trace.summarize(copy)
    for name in GENERATED:
        fresh = (copy / name).read_text(encoding="utf-8")
        assert fresh == (RESULTS / name).read_text(encoding="utf-8").replace("\r\n", "\n"), name


def test_each_case_is_one_tree_under_its_harness_span() -> None:
    runs = data()["runs"]
    assert set(runs) == set(ROOTS)
    for name, run in runs.items():
        row, case = run["row"], run["case"]
        assert case["passed"] and run["collector_exit"] == 0 and run["all_kept_spans_at_the_sink"], name
        assert row["roots"] == 1 and row["root_names"] == {ROOTS[name]: 1}, name
        assert row["other_traces"] == 0 and run["unnamed_traces"] == 0 and run["one_tree"], name
        tap = analyze.read_jsonl(RESULTS / name / "tap.jsonl")
        assert {d["trace_id"] for d in tap} == {case["trace_id"]} and row["spans"] == len(tap) == run["spans_sent"], name
        assert one_trace.one_tree(tap, case["trace_id"]), name
        # each model call's span sits under the case's tree: the gateway's spans have a parent, under the trace id
        chat = [d for d in tap if d["service"] == "gateway"]
        assert len(chat) == run["gateway_calls"] > 0 and all(d["parent_span_id"] for d in chat), name
    w4 = analyze.read_jsonl(RESULTS / "w4-gpt-oss-20b" / "tap.jsonl")
    scorer = next(d for d in w4 if d["name"] == "invoke_agent risk-scorer")
    assert next(d for d in w4 if d["service"] == "gateway")["parent_span_id"] == scorer["span_id"]
    w3 = analyze.read_jsonl(RESULTS / "w3" / "tap.jsonl")
    services = {d["service"] for d in w3}
    assert services == {"w3-harness", "gateway", "larkspur-ops-kubernetes", "larkspur-ops-metrics", "larkspur-ops-logs",
                        "larkspur-ops-writer", "larkspur-ops-servicenow"}


def test_step_3b_had_more_than_one_root_for_the_same_cases() -> None:
    runs = data()["runs"]
    w3, w4 = runs["w3"]["step_3b"], runs["w4-gpt-oss-20b"]["step_3b"]
    assert w3["row"]["roots"] > 1 and w3["row"]["other_traces"] > 0 and w3["unnamed_traces"] > 0
    assert set(w3["row"]["root_names"]) <= {"gateway: chat larkspur-chat", "gateway: chat larkspur-chat-restricted"}
    assert w4["row"]["root_names"] == {"gateway: chat larkspur-chat": 1, "scribe: invoke_agent change-management": 1}


def test_one_tree_reads_parents_within_the_trace() -> None:
    def span(span_id: str, parent: str | None, trace: str = "t") -> dict:
        return {"trace_id": trace, "span_id": span_id, "parent_span_id": parent}

    chain = [span("a", None), span("b", "a"), span("c", "b")]
    assert one_trace.one_tree(chain, "t")
    assert not one_trace.one_tree(chain + [span("d", None)], "t")  # a second root
    assert not one_trace.one_tree(chain + [span("e", "elsewhere")], "t")  # a parent outside the trace is a root too
    assert one_trace.one_tree(chain + [span("x", None, trace="other")], "t")  # another trace is another question


def test_the_results_hold_no_path_of_this_machine() -> None:
    for path in RESULTS.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for fragment in ("C:\\\\", "C:/", "AppData", "\\\\Users\\\\", "/Users/", "scratchpad"):
                assert fragment not in text, (path.name, fragment)
