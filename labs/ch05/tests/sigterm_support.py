"""A stub OpenTelemetry Collector, and a way to stop a server with SIGTERM once it serves.

Used by the runtime adapter's tests here and by the harness image's tests in chapters 7 and 8,
which import this file. Every runtime stops a container with SIGTERM, and Foundry's contract asks
for pending writes to be flushed: the process must exit cleanly, and the spans still waiting in
the batch must reach the Collector on the way out.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


@contextmanager
def otlp_collector() -> Iterator[tuple[str, list[str]]]:
    """A stub OpenTelemetry Collector: it accepts OTLP/HTTP posts and records their paths."""
    received: list[str] = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("content-length", 0)))
            received.append(self.path)
            self.send_response(200)
            self.send_header("content-length", "0")
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()


# Runs a server script as its command line would, probes it once it serves, queues one span, and
# raises SIGTERM inside the process: Windows has no way to send SIGTERM to another process.
STOP_ON_SIGTERM = """
import runpy, signal, sys, threading, time, urllib.error, urllib.request

script, probe, *argv = sys.argv[1:]

def stop_once_serving():
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                status = urllib.request.urlopen(probe, timeout=1).status
            except urllib.error.HTTPError as error:
                status = error.code
            except OSError:
                time.sleep(0.1)
                continue
            print(f"probe {status}", flush=True)
            break
    finally:  # whatever the probe saw, the process is stopped
        import trace_setup
        with trace_setup.start_span("before-sigterm"):
            pass  # still in the batch when the signal arrives: the flush on the way out is under test
        signal.raise_signal(signal.SIGTERM)

threading.Thread(target=stop_once_serving, daemon=True).start()
sys.argv = [script, *argv]
runpy.run_path(script, run_name="__main__")
"""


def serve_then_sigterm(script: Path, argv: list[str], probe: str,
                       env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run `script` with `argv` in a subprocess, wait until `probe` answers, then send SIGTERM.

    The process exports its spans to a stub Collector. Returns the finished process and the paths
    the Collector received; `probe <status>` on its stdout is the probe's answer.
    """
    with otlp_collector() as (otel, received):
        result = subprocess.run([sys.executable, "-c", STOP_ON_SIGTERM, str(script), probe, *argv],
                                env=env | {"OTEL_EXPORTER_OTLP_ENDPOINT": otel, "PYTHONUTF8": "1"},
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        return result, list(received)
