"""Step 3b: the Collector with CloudWatch and Langfuse off, the root trigger's cap, and the committed results of the
workflows' runs on the local models: what each sent, what a run's trace id holds, fig-16-01, and W5's night under
the two sampler settings. None of these needs a model; the two that start the pinned Collector skip without it."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

import yaml

import analyze_workflows as aw
import fake_otlp
import join
import otelcol
import policies
from collector_support import exe_or_skip, request, running, send, span, trace_id

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-03" / "workflows"
GENERATED = ("summary.md", "workflows.json", aw.FIGURE)


def data() -> dict:
    return json.loads((RESULTS / "workflows.json").read_text(encoding="utf-8"))


def figure() -> dict:
    return json.loads((RESULTS / aw.FIGURE).read_text(encoding="utf-8"))


# --- the Collector for the runs on the local models -------------------------------------------------------------

def test_the_local_config_is_config_yaml_without_cloudwatch_and_langfuse() -> None:
    full, local = yaml.safe_load(otelcol.CONFIG.read_text(encoding="utf-8")), otelcol.local_config()
    assert set(full["exporters"]) - set(local["exporters"]) == set(otelcol.CLOUD_EXPORTERS)
    assert local["exporters"] == {"file": full["exporters"]["file"]}
    assert "extensions" not in local and "extensions" not in local["service"]
    assert set(full["processors"]) - set(local["processors"]) == {otelcol.CLOUD_PROCESSOR}
    for name, processor in local["processors"].items():  # the content drop, the sampler and its policies, the batch
        assert processor == full["processors"][name], name
    assert local["receivers"] == full["receivers"] and local["connectors"] == full["connectors"]
    assert local["service"]["pipelines"] == {"traces/sample": full["service"]["pipelines"]["traces/sample"],
                                             "traces/stores": {"receivers": ["forward/sampled"], "exporters": ["file"]}}
    text = yaml.safe_dump(local)
    assert "https://" not in text and "LANGFUSE" not in text and "sigv4" not in text and "basicauth" not in text


def test_the_local_environment_holds_no_credential_and_the_overlay_adds_the_tap_the_sink_and_the_trigger(tmp_path: Path) -> None:
    env = otelcol.local_environment(span_file=tmp_path / "spans.jsonl", share_percent=100)
    assert not [k for k in env if k.startswith(("AWS_", "LANGFUSE_"))] and env["LARKSPUR_TRACE_SHARE_PERCENT"] == "100"
    extra = otelcol.local_overlay(otlp_port=1, metrics_port=2, tap_url="http://127.0.0.1:3", sink_url="http://127.0.0.1:4",
                                  decision_wait="300s", after_root="10s")
    assert extra["processors"] == {"tail_sampling": {"decision_wait": "300s", "decision_wait_after_root_received": "10s"}}
    assert extra["service"]["pipelines"]["traces/stores"] == {"exporters": ["file", "otlp_http/sink"]}
    assert extra["service"]["pipelines"]["traces/tap"] == {"receivers": ["otlp"], "exporters": ["otlp_http/tap"]}
    assert "processors" not in otelcol.local_overlay(otlp_port=1, metrics_port=2, tap_url="t", sink_url="s")


def test_the_binary_validates_the_local_config_with_its_overlay(tmp_path: Path) -> None:
    exe = exe_or_skip()
    config = otelcol.write_local_config(tmp_path)
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(yaml.safe_dump(otelcol.local_overlay(otlp_port=otelcol.free_port(), metrics_port=otelcol.free_port(),
                                                            tap_url="http://127.0.0.1:9", sink_url="http://127.0.0.1:9")),
                       encoding="utf-8")
    done = otelcol.validate(exe, otelcol.local_environment(span_file=tmp_path / "spans.jsonl"), config, overlay)
    assert done.returncode == 0, done.stderr[-2000:]


def test_the_root_trigger_brings_a_decision_forward_and_never_past_decision_wait(tmp_path: Path) -> None:
    """decision_wait stays the cap: a root that arrives after it finds the trace decided on its first spans, as a
    W5 night longer than 30 seconds would with decision_wait at 30 and the trigger on."""
    exe = exe_or_skip()
    with running(exe, tmp_path, decision_wait="3s", tail={"decision_wait_after_root_received": "1s"}) as collector:
        late, root = trace_id(kept_by_share=False), uuid.uuid4().hex[:16]
        send(collector.url, request([span(late, "early child", parent=root)]))
        time.sleep(4.5)  # past the 3-second cap
        send(collector.url, request([span(late, "slow root", span_id=root, seconds=40)]))
        time.sleep(3)
    assert late not in collector.stores()["langfuse"] and late not in collector.stores()["file"]


# --- the committed results --------------------------------------------------------------------------------------

def test_the_summary_is_what_analyze_workflows_writes_from_the_committed_files(tmp_path: Path) -> None:
    copy = tmp_path / "workflows"
    shutil.copytree(RESULTS, copy)
    for name in GENERATED:
        (copy / name).unlink()
    aw.summarize(copy)
    for name in GENERATED:
        fresh = (copy / name).read_text(encoding="utf-8")
        assert fresh == (RESULTS / name).read_text(encoding="utf-8").replace("\r\n", "\n"), name


def test_every_span_the_processes_sent_was_kept_and_left_through_the_sink() -> None:
    for name in aw.RUNS:
        tap = aw.analyze.read_jsonl(RESULTS / name / "tap.jsonl")
        sink = aw.analyze.read_jsonl(RESULTS / name / "sink.jsonl")
        kept = fake_otlp.spans_from_file(RESULTS / name / "spans.jsonl")
        assert tap and {d["span_id"] for d in tap} == {d["span_id"] for d in sink} == {s["span_id"] for s in kept}, name
        assert not [d for d in tap if d["content"]], name  # no process put content on a span
        meta = json.loads((RESULTS / name / "meta.json").read_text(encoding="utf-8"))
        assert meta["collector_exit"] == 0 and meta["all_kept_spans_at_the_sink"] and not meta["only"], name


def test_each_case_s_gateway_lines_are_its_own_calls() -> None:
    runs = data()["runs"]
    assert set(runs) == set(aw.RUNS)
    for name, row in runs.items():
        assert row["lines_per_case_match"] and row["failed_calls"] == 0, name
    assert {name: (row["cases"], row["calls"]) for name, row in runs.items()} == {
        "w2": (25, 49), "w3": (24, 142), "w4-gpt-oss-20b": (8, 8), "w4-gemma4-12b": (8, 8), "w5-step3": (1, 14),
        "w5-root": (1, 14)}


def test_which_processes_sent_spans() -> None:
    sent = {name: {p["service"]: p["sent"] for p in rows} for name, rows in data()["processes"].items()}
    assert all(row[None] == 0 for row in sent.values())  # Ollama sends none
    assert all(n > 0 for row in sent.values() for service, n in row.items() if service)
    assert set(sent["w2"]) == {"w2-harness", "larkspur-ops-kubernetes", "larkspur-ops-metrics", "larkspur-ops-logs", "gateway", None}
    assert set(sent["w4-gpt-oss-20b"]) == {"scribe", "analyst", "risk-scorer", "gateway", None}
    assert set(sent["w5-step3"]) == {"w5-night", "gateway", None} | {f"larkspur-drift-{n}" for n in ("state", "cloud", "cost", "policy")}


def test_what_a_run_s_trace_id_holds() -> None:
    """W2's and W5's runs are one tree under the harness's span. W4's has two roots, the scribe's span and the
    gateway's, since the rationale seam sends a bare trace id. W3's trace id holds only the gateway's spans, each a
    root, and every read is a trace of its own."""
    cover = data()["coverage"]
    w2 = [r for r in cover["w2"]["rows"] if r["spans"]]
    assert len(w2) == 24 and all(r["roots"] == 1 and r["root_names"] == {"w2-harness: invoke_agent w2-harness": 1}
                                 and not r["other_traces"] for r in w2)
    assert [r["case"] for r in cover["w2"]["rows"] if not r["spans"]] == ["w2-13"]  # refused before its span opened
    for name in ("w4-gpt-oss-20b", "w4-gemma4-12b"):
        assert all(r["root_names"] == {"gateway: chat larkspur-chat": 1, "scribe: invoke_agent change-management": 1}
                   for r in cover[name]["rows"])
    for name in ("w5-step3", "w5-root"):
        [row] = cover[name]["rows"]
        assert row["root_names"] == {"w5-night: invoke_agent w5-night": 1} and cover[name]["traces_at_the_collector"] == 1
    w3 = cover["w3"]
    assert all(set(r["root_names"]) <= {"gateway: chat larkspur-chat", "gateway: chat larkspur-chat-restricted"}
               for r in w3["rows"])
    assert sum(r["roots"] for r in w3["rows"]) == data()["runs"]["w3"]["calls"]  # every model call a root
    assert sum(r["other_traces"] for r in w3["rows"]) > 0 and w3["unnamed_traces"] > 0


def test_fig_16_01_is_w2_s_median_run_from_its_real_trace() -> None:
    fig = figure()
    assert (fig["workflow"], fig["model"], fig["model_calls"], fig["tool_calls"]) == ("w2-ops-assistant", "gpt-oss-20b", 2, 1)
    [root] = fig["tree"]
    assert root["name"] == "invoke_agent w2-harness" and root["service"] == "w2-harness"
    under = [c["name"] for c in root["children"]]
    assert under.count("chat larkspur-chat") == 2 and under.count("execute_tool get_pod_status") == 1
    calls = [c for c in root["children"] if c["name"] == "chat larkspur-chat"]
    assert all(c["service"] == "gateway" and c["attributes"]["gen_ai.response.model"] == "gpt-oss:20b" for c in calls)
    stores = {s["store"]: s["records"] for s in fig["stores"]}
    joined = join.join(fig["trace_id"], join.local_stores(RESULTS / "w2"))
    assert stores["span file (the Collector)"] == len(fig["spans"]) == len(joined["spans"])
    assert stores["gateway cost lines"] == 2 and stores["tool servers' logs"] == 1
    assert fig["join"] == join.render(fig["trace_id"], joined).splitlines()
    cases = aw.cases("w2", RESULTS / "w2", "gpt-oss-20b")
    first = next(c for c in cases if c["model_calls"] == 2 and c["tool_calls"] == 1 and c["passed"])
    assert fig["case"] == first["case"] and fig["trace_id"] == first["trace_id"]


def test_w5_s_night_under_the_two_settings() -> None:
    s = data()["sampler"]
    step3, root = s["w5-step3"], s["w5-root"]
    for run in (step3, root):
        assert run["spans_sent"] == run["spans_kept"] == run["spans_at_the_sink"] and run["policy"] == ["slow"]
        assert run["share"] == [1.0] and run["decision_on_all"]["kept"]
    # config.yaml's 30 seconds: decided on the spans of the first 30, the root and the rest late, and kept anyway
    assert step3["decision_wait_s"] == 30 and 30 <= step3["first_arrival_to_first_departure_s"] <= 32
    assert not step3["root_among_them"] and step3["root_arrival_to_departure_s"] < 2
    assert step3["late_span_count_metric"] == [str(step3["spans_sent"] - step3["spans_before_the_first_departure"])]
    # the root trigger, with the cap above the night: decided 10 seconds after the root, on every span
    assert root["decision_wait_after_root_received"] == "10s" and root["root_among_them"]
    assert root["spans_before_the_first_departure"] == root["spans_sent"] and root["late_span_count_metric"] == []
    assert 10 <= root["first_departure_after_root_arrival_s"] <= 12 and root["night_seconds"] < root["decision_wait_s"]


def test_the_readme_s_step_3b_tables_are_the_summary_s() -> None:
    from test_results import readme_rows

    summary = (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    _, _, rows = readme_rows()
    assert len(rows) >= 12
    for row in rows:
        assert row in summary, row


def test_the_readme_shows_fig_16_01_as_join_prints_it() -> None:
    readme = (LAB / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    block = readme.split("prints for fig-16-01's run:\n\n```\n", 1)[1].split("```", 1)[0]
    assert block.splitlines() == figure()["join"]


def test_the_runs_are_kept_beside_each_workflow_s_results_with_no_path_of_this_machine() -> None:
    for workflow, expected in (("w2", {"answers-gpt-oss-20b.json"}), ("w3", {"runs-gpt-oss-20b.json", "trace-ids-gpt-oss-20b.json"}),
                               ("w4", {f"{kind}-{model}.{ext}" for model in ("gpt-oss-20b", "gemma4-12b")
                                       for kind, ext in (("packs", "json"), ("results", "json"), ("summary", "json"),
                                                         ("metrics", "json"), ("readme", "md"))})):
        folder = aw.traced_folder(workflow)
        assert {p.name for p in folder.iterdir() if p.is_file()} == expected, workflow
        for logs in folder.glob("logs-*"):
            assert (logs / "gateway.jsonl").is_file(), logs
    for root in (RESULTS, *(aw.traced_folder(w) for w in ("w2", "w3", "w4"))):
        for path in root.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for fragment in ("C:\\\\", "C:/", "AppData", "\\\\Users\\\\", "/Users/", "scratchpad"):
                    assert fragment not in text, (path.name, fragment)


def test_ten_percent_would_keep_no_w3_incident_whole() -> None:
    """At config.yaml's share each of W3's traces is sampled on its own: the model calls and every read apart."""
    w3 = data()["at_ten_percent"]["w3"]
    assert w3["cases_whole"] == 0 and w3["cases_partly"] + w3["cases_none"] == w3["cases_with_spans"] == 24
    for name in ("w2", "w4-gpt-oss-20b", "w4-gemma4-12b"):
        t = data()["at_ten_percent"][name]
        assert t["cases_partly"] == 0 and t["cases_whole"] == t["kept"]  # one trace a case: kept whole or not at all
    assert policies.settings()["percent"] == aw.CONFIG_SHARE
