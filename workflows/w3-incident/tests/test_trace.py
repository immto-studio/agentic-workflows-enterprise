"""An incident as one trace (chapter 16's lab, companion #14; the follow-up to step 3b on issue #10).

Step 3b found W3's spans scattered: each read and each session's set-up was a trace of its own, and each model
call a root under the incident's trace id. eval/lab.py now opens one `invoke_agent w3-incident` span an
incident, with the incident's trace id, and hands its context to every read and write and its traceparent to
every model call. This test runs one incident the way the live runs do, through the five servers as processes
and the approval service, against a scripted gateway on 127.0.0.1, in a process of its own that installs
chapter 5's tracer provider, and follows every span the six processes recorded to the one root."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

W3 = Path(__file__).resolve().parents[1]
INCIDENT = "w3-01"  # claims-api in a crash loop: a read, a proposed restart, an approval, the write, the check

# The incident run in a process of its own: chapter 5's tracer provider there writes to TRACE_FILE, which the
# five servers lab.py starts inherit, and run_all uses the scripted gateway instead of starting LiteLLM.
DRIVER = """
import json, sys
eval_dir, gateway, incident_id = sys.argv[1:4]
sys.path.insert(0, eval_dir)
import lab
import trace_setup as tracing
tracing.configure("w3-harness")
incidents = [c for c in lab.scoring.load_incidents(lab.HERE / "incidents.yaml") if c["id"] == incident_id]
records, summary = lab.run_all(incidents, gateway_url=gateway)
print(json.dumps({"trace_id": lab.TRACE["id"], "record": records[0]}))
"""


def _tool_call(call_id: str, name: str, args: dict) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


REPLIES = [_tool_call("c1", "get_pod_status", {"service": "claims-api"}),
           _tool_call("c2", "restart_deployment", {"service": "claims-api"})]
DONE = {"choices": [{"message": {"role": "assistant", "content": "Nothing more to add."}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 5}}


@contextmanager
def scripted_gateway() -> Iterator[tuple[str, list[dict]]]:
    """A Chat Completions endpoint on 127.0.0.1: the replies in order, then a plain answer; each body kept."""
    bodies: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            return None

        def do_POST(self):  # noqa: N802
            bodies.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0))))
            reply = REPLIES[len(bodies) - 1] if len(bodies) <= len(REPLIES) else DONE
            payload = json.dumps(reply).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", bodies
    finally:
        server.shutdown()
        server.server_close()


def read_spans(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [json.loads(line) for line in text.split("\n")[:-1] if line.strip()]


def test_every_span_of_an_incident_sits_under_one_root(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    env = {**os.environ, "PYTHONUTF8": "1", "TRACE_FILE": str(traces), "W3_LAB_SCRATCH": str(tmp_path / "lab")}
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    with scripted_gateway() as (gateway, bodies):
        run = subprocess.run([sys.executable, "-X", "utf8", "-c", DRIVER, str(W3 / "eval"), gateway, INCIDENT], env=env,
                             capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert run.returncode == 0, run.stderr[-3000:]
    printed = json.loads(run.stdout.strip().splitlines()[-1])
    trace, record = printed["trace_id"], printed["record"]

    # The run did what an incident does, and its record has the shape it always had: the trace changes no record.
    assert record["state"] == "done" and record["executed"] and record["approved"]
    assert record["proposal"] == {"tool": "restart_deployment", "args": {"service": "claims-api"}}
    assert record["reads"] == ["get_pod_status"] and len(record["labels"]) == 2
    assert set(record) == {"id", "triage", "proposal", "executed", "approved", "labels", "reads", "hidden_reads", "state",
                           "persona", "seconds"}

    spans = read_spans(traces)
    assert spans and {s["trace_id"] for s in spans} == {trace}  # no read and no session started a trace of its own
    services = {s["resource"]["service.name"] for s in spans}
    assert services == {"w3-harness", "larkspur-ops-kubernetes", "larkspur-ops-metrics", "larkspur-ops-logs",
                        "larkspur-ops-writer", "larkspur-ops-servicenow"}
    by_id = {s["span_id"]: s for s in spans}
    roots = [s for s in spans if s["parent_span_id"] is None]
    assert [(r["name"], r["resource"]["service.name"]) for r in roots] == [("invoke_agent w3-incident", "w3-harness")]
    root = roots[0]
    assert root["attributes"]["larkspur.trace_id"] == trace
    for span in spans:  # each span reaches the root through parents of the same incident
        current = span
        while current["parent_span_id"] is not None:
            assert current["parent_span_id"] in by_id, (span["name"], span["resource"]["service.name"])
            current = by_id[current["parent_span_id"]]
        assert current is root, span["name"]
    assert root["start"] <= min(s["start"] for s in spans) and root["end"] >= max(s["end"] for s in spans)
    tools = [s for s in spans if s["name"].startswith("execute_tool ") and s["resource"]["service.name"] == "w3-harness"]
    assert sorted(s["name"] for s in tools) == ["execute_tool get_pod_status", "execute_tool restart_deployment"]
    assert all(s["parent_span_id"] == root["span_id"] for s in tools)  # the read and the write, each under the root
    writer = [s for s in spans if s["resource"]["service.name"] == "larkspur-ops-writer" and s["name"].startswith("execute_tool")]
    assert [s["name"] for s in writer] == ["execute_tool restart_deployment"]

    # Every model call: the incident's trace id and the root's traceparent, which chapter 5's gateway prefers.
    assert len(bodies) == 2
    for body in bodies:
        version, trace_part, parent, flags = body["metadata"]["traceparent"].split("-")
        assert body["metadata"]["trace_id"] == trace and (version, trace_part, parent) == ("00", trace, root["span_id"])
        assert int(flags, 16) & 1  # sampled
