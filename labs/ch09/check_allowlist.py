"""Run the path allowlist of k8s/vllm-allowlist.yaml with a real nginx and probe every route.

Part 2 of the lab is validated, not run, because the lab has no GPU cluster. The allowlist is the
exception: nginx runs anywhere, so this script starts the ConfigMap's nginx.conf in front of a
stand-in for vLLM on 127.0.0.1:8000 and checks that the gateway's port passes exactly three
routes (a streamed answer included), that the metrics port passes /metrics alone, and that every
other route, /invocations and /update_weights among them, gets a 404. Only the config's file paths
change, so that it runs on Linux, macOS and Windows; the servers, locations and upstream are the
ones the pod runs. Ports 8000, 8080 and 8081 must be free.

Run:  python check_allowlist.py --nginx /usr/sbin/nginx --json allowlist.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CONFIGMAP = HERE / "k8s" / "vllm-allowlist.yaml"
PASSED = {(8080, "/v1/chat/completions"), (8080, "/v1/models"), (8080, "/health"), (8081, "/metrics")}
PROBES = [("POST", 8080, "/v1/chat/completions"), ("GET", 8080, "/v1/models"), ("GET", 8080, "/health"),
          ("POST", 8080, "/invocations"), ("POST", 8080, "/update_weights"), ("POST", 8080, "/pause"),
          ("GET", 8080, "/metrics"), ("GET", 8080, "/tokenize"), ("POST", 8080, "/v1/completions"),
          ("GET", 8080, "/v1/chat/completions/../../invocations"),
          ("GET", 8081, "/metrics"), ("POST", 8081, "/v1/chat/completions"), ("GET", 8081, "/health")]
STREAM_PARTS, STREAM_GAP_S = 3, 0.2


class StandIn(BaseHTTPRequestHandler):
    """Answers any path the way vLLM would be reached: a stream on chat completions, text elsewhere."""

    protocol_version = "HTTP/1.1"

    def _answer(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(STREAM_PARTS):
                chunk = f"data: part {i}\n\n".encode()
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                self.wfile.flush()
                time.sleep(STREAM_GAP_S)
            self.wfile.write(b"0\r\n\r\n")
            return
        body = f"stand-in {self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer

    def log_message(self, *args: object) -> None:
        pass


def local_config(conf: str, prefix: Path) -> str:
    """The ConfigMap's nginx.conf with its file paths moved under `prefix`; nothing else changes."""
    p = prefix.as_posix()
    return (conf.replace("pid /tmp/nginx.pid;", f"pid {p}/nginx.pid;")
                .replace("error_log /dev/stderr warn;", f"error_log {p}/error.log warn;")
                .replace("access_log /dev/stdout;", f"access_log {p}/access.log;")
                .replace("/tmp/", f"{p}/"))


def probe(method: str, port: int, path: str) -> dict:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                     data=b"{}" if method == "POST" else None)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read(1)
            first_byte_s = time.monotonic() - start
            response.read()
            status = response.status
    except urllib.error.HTTPError as err:
        status, first_byte_s = err.code, time.monotonic() - start
    passed = (port, path) in PASSED
    return {"method": method, "port": port, "path": path, "status": status,
            "first_byte_s": round(first_byte_s, 2), "as_designed": status == (200 if passed else 404)}


def run(nginx: Path) -> dict:
    conf = yaml.safe_load(CONFIGMAP.read_text(encoding="utf-8"))["data"]["nginx.conf"]
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp)
        (prefix / "logs").mkdir()  # nginx opens its built-in error log before it reads the config
        config = prefix / "nginx.conf"
        config.write_text(local_config(conf, prefix), encoding="utf-8")
        args = [str(nginx), "-p", str(prefix), "-c", str(config)]
        check = subprocess.run([*args, "-t"], capture_output=True, text=True)
        if check.returncode != 0:
            raise SystemExit(check.stderr)
        stand_in = ThreadingHTTPServer(("127.0.0.1", 8000), StandIn)
        threading.Thread(target=stand_in.serve_forever, daemon=True).start()
        server = subprocess.Popen([*args, "-g", "daemon off;"] if sys.platform != "win32" else args)
        try:
            time.sleep(1.5)
            probes = [probe(*case) for case in PROBES]
        finally:
            subprocess.run([*args, "-s", "stop"], capture_output=True)
            server.wait(timeout=10)
            stand_in.shutdown()
    version = subprocess.run([str(nginx), "-v"], capture_output=True, text=True).stderr.strip()
    stream = next(p for p in probes if p["path"] == "/v1/chat/completions" and p["port"] == 8080)
    return {"nginx": version, "config_test": "successful" if "test is successful" in check.stderr else check.stderr,
            "probes": probes,
            # a buffered proxy would hold the first byte until the whole stream had arrived
            "streams": stream["first_byte_s"] < STREAM_PARTS * STREAM_GAP_S}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--nginx", type=Path, default=shutil.which("nginx"))
    parser.add_argument("--json", type=Path, help="write the results here")
    args = parser.parse_args(argv)
    if args.nginx is None:
        parser.error("no nginx on PATH; pass --nginx")
    result = run(args.nginx)
    text = json.dumps(result, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0 if result["streams"] and all(p["as_designed"] for p in result["probes"]) else 1


if __name__ == "__main__":
    sys.exit(main())
