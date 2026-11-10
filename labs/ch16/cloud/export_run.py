"""The live run: chapter 5's skeleton through the pinned Collector to CloudWatch and Langfuse (step 7, items 2 and 7).

Step 3 ran chapter 5's skeleton through the Collector on this workstation with two fakes in place of the stores.
This is the same run with the real exporters: config.yaml as it is, the CloudWatch exporter signed by `sigv4auth`
with the session's profile (the extension reads AWS_PROFILE and the shared credentials file, as the SDK does), and
the Langfuse exporter pointed through the tunnel at the VM (cloud/tunnel.py). The runs are run_local.py's
every-run phase: chapter 5's golden set and the five runs made to be kept, 25 runs, with the share of the rest at
100 percent, so every trace is kept and both stores should hold every span. The tap records what the processes
sent, the sink what left the Collector and when, and the two checks (cloudwatch_spans.py, langfuse_check.py) then
poll the two stores for the kept traces and record the delay until each appeared. Without `--langfuse`, the
Langfuse exporter points at a local fake and the record says Langfuse wasn't reached.

Run (from labs/ch16, in chapter 5's environment, with the session's environment and the tunnel open):
    LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... python cloud/export_run.py --langfuse http://127.0.0.1:<port> \
        --out results/<date>/cloud
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
CH05 = LAB.parent / "ch05"
for folder in (HERE, LAB / "collector", LAB / "ledger", CH05 / "harness", CH05 / "mcp-server", CH05 / "tracing", CH05 / "golden"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import cloud_session  # noqa: E402
import cloudwatch_spans  # noqa: E402
import fake_otlp  # noqa: E402
import fetch  # noqa: E402
import langfuse_check  # noqa: E402
import otelcol  # noqa: E402
import policies  # noqa: E402
import run_local  # noqa: E402
import trace_setup as tracing  # noqa: E402

KEPT_FILES = ("harness.jsonl", "server.jsonl", "gateway.jsonl", "spans.jsonl", "runs.jsonl")


def collector_environment(*, span_file: Path, langfuse_endpoint: str, public_key: str, secret_key: str,
                          share_percent: float = 100.0) -> dict[str, str]:
    """The Collector's environment: the session's AWS variables for SigV4, Langfuse's keys, the span file."""
    env = {name: os.environ[name] for name in otelcol.PASS_THROUGH if name in os.environ}
    env |= cloud_session.aws_environment()
    env |= {"LANGFUSE_OTLP_ENDPOINT": langfuse_endpoint, "LANGFUSE_PUBLIC_KEY": public_key,
            "LANGFUSE_SECRET_KEY": secret_key, "LARKSPUR_SPAN_FILE": str(span_file),
            "LARKSPUR_TRACE_SHARE_PERCENT": f"{share_percent:g}"}
    return env


def overlay(*, otlp_port: int, metrics_port: int, tap_url: str, sink_url: str) -> dict[str, Any]:
    """The run's second config file: the port, the Collector's own metrics, the tap, and the sink beside the two
    real exporters. CloudWatch's endpoint stays config.yaml's."""
    return {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{otlp_port}"}}}},
        "exporters": {"otlp_http/tap": {"endpoint": tap_url, "compression": "none"},
                      "otlp_http/sink": {"endpoint": sink_url, "compression": "none"}},
        "service": {
            "telemetry": {"metrics": {"readers": [{"pull": {"exporter": {"prometheus": {
                "host": "127.0.0.1", "port": metrics_port}}}}]}},
            "pipelines": {"traces/tap": {"receivers": ["otlp"], "exporters": ["otlp_http/tap"]},
                          "traces/stores": {"exporters": ["file", "otlp_http/cloudwatch", "otlp_http/sink"]}},
        },
    }


def wait_for_sink(sink: fake_otlp.Receiver, expected: dict[str, int], limit: float) -> None:
    deadline = time.time() + limit
    while time.time() < deadline:
        seen = fake_otlp.by_trace(sink.spans())
        if all(len(seen.get(t, [])) >= n for t, n in expected.items()):
            return
        time.sleep(0.5)


def sink_times(sink: fake_otlp.Receiver) -> dict[str, float]:
    """When the last span of each trace left the Collector (the sink's receipt)."""
    out: dict[str, float] = {}
    for record in sink.records:
        for span in record["spans"]:
            out[span["trace_id"]] = max(out.get(span["trace_id"], 0.0), record["received_at"])
    return out


def collector_log_summary(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    bad = [line for line in lines if "error" in line.lower() or "failed" in line.lower() or "warn" in line.lower()]
    return {"lines": len(lines), "error_or_warning_lines": len(bad),
            "first_error_or_warning_lines": [cloud_session.redact_text(line)[:300] for line in bad[:8]]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--langfuse", help="Langfuse's base URL through the tunnel, e.g. http://127.0.0.1:3000")
    parser.add_argument("--out", type=Path, default=cloud_session.results_dir())
    parser.add_argument("--work", type=Path, help="raw output folder (default cloud/_lab/export-<stamp>)")
    parser.add_argument("--rounds", type=int, default=1, help="times the golden set runs (default 1)")
    parser.add_argument("--cloudwatch-limit", type=float, default=1200.0)
    parser.add_argument("--langfuse-limit", type=float, default=900.0)
    args = parser.parse_args(argv)
    cloud_session.require_environment()
    public_key, secret_key = os.environ.get("LANGFUSE_PUBLIC_KEY", ""), os.environ.get("LANGFUSE_SECRET_KEY", "")
    if args.langfuse and not (public_key and secret_key):
        raise SystemExit("--langfuse needs LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in the environment")
    exe = fetch.verified()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = args.work or cloud_session.SCRATCH / f"export-{stamp}"
    work.mkdir(parents=True)
    collector_port = otelcol.free_port()
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"http://127.0.0.1:{collector_port}"
    os.environ["LARKSPUR_TRACE_TOOL_ARGS"] = "1"
    os.environ.pop("TRACE_FILE", None)
    setup = tracing.configure("harness")
    decision_wait = float(policies.config()["processors"]["tail_sampling"]["decision_wait"].rstrip("s"))
    record: dict[str, Any] = {"stamp": stamp, "clock": cloud_session.CLOCK, "decision_wait_s": decision_wait,
                              "share_percent": 100.0, "langfuse_reached_for": args.langfuse is not None}
    fake_langfuse = None if args.langfuse else fake_otlp.langfuse().start()
    langfuse_endpoint = f"{args.langfuse}/api/public/otel" if args.langfuse else f"{fake_langfuse.url}/api/public/otel"
    specs = run_local.golden(args.rounds) + run_local.specials()
    with fake_otlp.Receiver("tap", "/v1/traces") as tap, fake_otlp.Receiver("sink", "/v1/traces") as sink:
        env = collector_environment(span_file=work / "spans.jsonl", langfuse_endpoint=langfuse_endpoint,
                                    public_key=public_key or otelcol.DUMMY_LANGFUSE_PUBLIC_KEY,
                                    secret_key=secret_key or otelcol.DUMMY_LANGFUSE_SECRET_KEY)
        metrics_port = otelcol.free_port()
        extra = overlay(otlp_port=collector_port, metrics_port=metrics_port, tap_url=tap.url, sink_url=sink.url)
        collector = otelcol.Collector(exe, work, env, extra).start()
        stack = run_local.Stack(work, collector_port)
        runs_started = time.time()
        try:
            stack.start()
            with (work / "harness.jsonl").open("a", encoding="utf-8", newline="\n") as log:
                results = run_local.run_specs(specs, "cloud", stack, log)
            runs_ended = time.time()
            setup.provider.force_flush()
            run_local.settle(tap)
            tapped = fake_otlp.by_trace(tap.spans())
            expected = {r.trace_id: len(tapped.get(r.trace_id, [])) for r in results}
            wait_for_sink(sink, expected, decision_wait + 40)
            left = sink_times(sink)
            import httpx

            metrics = httpx.get(f"http://127.0.0.1:{metrics_port}/metrics", timeout=10).text
        finally:
            stack.stop()
            stopped = cloud_session.Clock()
            code = collector.stop()
            record["collector_stop_s"] = stopped.seconds()
        if fake_langfuse is not None:
            fake_langfuse.stop()
            fake_langfuse.write(work / "langfuse-fake.jsonl")
        (work / "metrics.txt").write_text(metrics, encoding="utf-8", newline="\n")
        tap.write(work / "tap.jsonl")
        sink.write(work / "sink.jsonl")
    from dataclasses import asdict

    (work / "runs.jsonl").write_text("".join(json.dumps(asdict(r)) + "\n" for r in results), encoding="utf-8", newline="\n")
    kept = fake_otlp.by_trace(fake_otlp.spans_from_file(work / "spans.jsonl"))
    record["run"] = {
        "runs": len(results), "passed": sum(1 for r in results if r.passed), "kinds": sorted({r.kind for r in results}),
        "started": datetime.fromtimestamp(runs_started, tz=timezone.utc).isoformat(timespec="seconds"),
        "ended": datetime.fromtimestamp(runs_ended, tz=timezone.utc).isoformat(timespec="seconds"),
        "spans_sent": sum(expected.values()), "spans_in_file": sum(len(v) for v in kept.values()),
        "spans_left_collector": len(sink.spans()), "traces": len(expected),
        "traces_with_every_span_in_file": sum(1 for t, n in expected.items() if len(kept.get(t, [])) == n),
        "traces_with_every_span_left": sum(1 for t, n in expected.items() if len(fake_otlp.by_trace(sink.spans()).get(t, [])) == n),
        "sink_requests": len(sink.records),
        "sink_delay_s": {t: round(left[t] - min(s["start_ns"] for s in tapped[t]) / 1e9, 1) for t in expected if t in left},
    }
    record["collector"] = {"exit_code": code, "log": collector_log_summary(collector.log()),
                           "exporter_metrics": [line for line in metrics.splitlines()
                                                if line.startswith("otelcol_exporter_") and "exporter=" in line and not line.startswith("#")]}
    record["trace_ids"] = {r.case: r.trace_id for r in results}
    checks: dict[str, Any] = {}

    def cloudwatch() -> None:
        checks["cloudwatch"] = cloudwatch_spans.poll(cloud_session.session(), expected, runs_started, left, limit=args.cloudwatch_limit)

    def langfuse() -> None:
        checks["langfuse"] = langfuse_check.poll(args.langfuse, public_key, secret_key, expected, kept, left, limit=args.langfuse_limit)

    threads = [threading.Thread(target=cloudwatch, name="cloudwatch")]
    if args.langfuse:
        threads.append(threading.Thread(target=langfuse, name="langfuse"))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    record["cloudwatch"] = checks.get("cloudwatch")
    record["langfuse"] = checks.get("langfuse") if args.langfuse else {"reached": False, "why": "no tunnel to Langfuse; the exporter sent to a local fake"}
    if record["langfuse"] and "observations" in record["langfuse"]:
        cloud_session.write_json(args.out / "export-run" / "langfuse-observations.json", record["langfuse"].pop("observations"))
    out_run = args.out / "export-run"
    out_run.mkdir(parents=True, exist_ok=True)
    for name in KEPT_FILES:
        if (work / name).exists():
            cloud_session.write_text(out_run / name, (work / name).read_text(encoding="utf-8"))
    cloud_session.write_json(out_run / "sink-times.json", {t: datetime.fromtimestamp(v, tz=timezone.utc).isoformat(timespec="milliseconds") for t, v in left.items()})
    if record["cloudwatch"] and record["cloudwatch"].get("sample_record") is not None:
        cloud_session.write_json(out_run / "cloudwatch-sample-record.json", record["cloudwatch"]["sample_record"])
    cloud_session.write_json(args.out / "export-run.json", record)
    shutil.copy(work / "metrics.txt", out_run / "collector-metrics.txt")
    cw = record["cloudwatch"] or {}
    print(f"runs {record['run']['runs']}, spans sent {record['run']['spans_sent']}, left {record['run']['spans_left_collector']}; "
          f"CloudWatch: {cw.get('traces_complete')} of {cw.get('traces_expected')} traces complete in {cw.get('polled_s')} s; "
          f"Langfuse: {(record['langfuse'] or {}).get('traces_complete')} complete in {(record['langfuse'] or {}).get('polled_s')} s")
    print(f"raw records in {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
