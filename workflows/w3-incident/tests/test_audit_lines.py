"""The logs server's audit line in a W3 run, and the harness's log that matches it (chapter 17, companion #126).

W3 reads logs through W2's logs server, whose line keeps the search string only as an HMAC under AUDIT_HMAC_KEY.
eval/lab.py keeps the harness's log for each incident beside the servers' logs, with the text, so an auditor who
holds the key can match the two. This test runs one incident the way the live runs do, through the five servers
as processes and the approval service, against a scripted gateway that asks for one log search and then answers,
and reads both logs the run left."""

from __future__ import annotations

import hashlib
import hmac
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
AUDIT_KEY = "w3-audit-hmac-key-for-tests-at-least-32-bytes"  # AUDIT_HMAC_KEY, fixed for the test
SEARCHED = "Dana Whitfield"  # a search string that holds a person's name
SEARCH = {"service": "claims-api", "minutes": 60, "contains": SEARCHED, "lines": 20}

DRIVER = """
import json, sys
eval_dir, gateway, incident_id = sys.argv[1:4]
sys.path.insert(0, eval_dir)
import lab
incidents = [c for c in lab.scoring.load_incidents(lab.HERE / "incidents.yaml") if c["id"] == incident_id]
records, summary = lab.run_all(incidents, gateway_url=gateway)
print(json.dumps({"trace_id": lab.TRACE["id"], "record": records[0]}))
"""

REPLIES = [{"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
    {"id": "c1", "type": "function", "function": {"name": "search_logs", "arguments": json.dumps(SEARCH)}}]}}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 20}}]
DONE = {"choices": [{"message": {"role": "assistant", "content": "Nothing in the logs names that person."}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 5}}


def auditors_hmac(text: str, key: str) -> str:
    """What an auditor computes from the harness's log: HMAC-SHA256 of the text under the key, in the line's form."""
    return "hmac-sha256:" + hmac.new(key.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()


@contextmanager
def scripted_gateway() -> Iterator[str]:
    """A Chat Completions endpoint on 127.0.0.1: the replies in order, then a plain answer."""
    bodies: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            return None

        def do_POST(self):  # noqa: N802
            bodies.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0))))
            payload = json.dumps(REPLIES[len(bodies) - 1] if len(bodies) <= len(REPLIES) else DONE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_logs_servers_line_holds_an_hmac_of_the_search_string_the_harnesss_log_keeps(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONUTF8": "1", "W3_LAB_SCRATCH": str(tmp_path / "lab"), "AUDIT_HMAC_KEY": AUDIT_KEY,
           "TRACE_FILE": str(tmp_path / "traces.jsonl")}
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    with scripted_gateway() as gateway:
        run = subprocess.run([sys.executable, "-X", "utf8", "-c", DRIVER, str(W3 / "eval"), gateway, "w3-01"], env=env,
                             capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert run.returncode == 0, run.stderr[-3000:]
    printed = json.loads(run.stdout.strip().splitlines()[-1])
    trace = printed["trace_id"]
    assert printed["record"]["state"] == "done" and printed["record"]["reads"] == ["search_logs"]

    folder = tmp_path / "lab" / "run"
    [kept] = [e for e in read_lines(folder / "harness.jsonl")
              if e["event"] == "tool_call" and e.get("tool") == "search_logs" and e["trace_id"] == trace]
    assert kept["args"] == SEARCH and kept["ok"] is True  # the harness's log keeps the text
    [audited] = [e for e in read_lines(folder / "logs-mcp.log")
                 if e["event"] == "tool_call" and e["tool"] == "search_logs" and e["trace_id"] == trace]
    # The service, the window, and the line count as they are; the search string as its HMAC.
    assert audited["args"] == {**SEARCH, "contains": auditors_hmac(kept["args"]["contains"], AUDIT_KEY)}
    assert audited["args"]["contains"] != auditors_hmac(SEARCHED, "another audit key, also 32 bytes or more")
    assert audited["identity"] == "larkspur-ops-logs-reader" and audited["ok"] is True
    line = json.dumps(audited).lower()
    assert not any(part in line for part in SEARCHED.lower().split())  # no part of the text in clear
