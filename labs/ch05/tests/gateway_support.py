"""Start the lab's gateway for the tests: three fake backends and the LiteLLM proxy, as subprocesses.

Used by the session fixture `gateway` in conftest.py and by the helpers the gateway tests call.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

LAB = Path(__file__).resolve().parent.parent
GATEWAY = LAB / "gateway"
MASTER_KEY = "sk-larkspur-lab-test"  # a test value, set in the proxy's environment, not a secret
BACKENDS = (("primary", 8801), ("fallback", 8802), ("self-hosted", 8803))

BUDGET_TEST_MANIFEST = """\
workflow: w0-budget-test
owner: test@larkspur.example
sponsor: test@larkspur.example
rung: 0
data_class_max: internal
models: [larkspur-chat]
regions: [ca-central-1, us-east-2]
tools: {}
never: []
budget: {per_run_usd: 0.00001, per_month_usd: 1}
trace_content: false
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, seconds: float, proc: subprocess.Popen | None = None) -> None:
    deadline = time.time() + seconds
    last: object = None
    while time.time() < deadline:
        # A process that has already exited will never answer; waiting out the deadline would only
        # bury its exit code under a "connection refused" and the traceback it printed on stderr.
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"{url} did not come up: the process exited with code {proc.returncode}")
        try:
            r = httpx.get(url, timeout=2)
            if r.status_code < 500:
                return
            last = r.status_code
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(0.5)
    raise RuntimeError(f"{url} did not come up: {last}")


def litellm_executable() -> str:
    exe = shutil.which("litellm", path=str(Path(sys.executable).parent))
    if not exe:
        pytest.skip("litellm console script not found next to the interpreter")
    return exe


@contextmanager
def running_gateway(work: Path, trace_file: Path) -> Iterator[dict]:
    """The three fakes on the ports the config names and the proxy on a free port, until exit."""
    manifests = work / "manifests"
    manifests.mkdir()
    for path in (LAB / "manifest").glob("*.yaml"):
        shutil.copy(path, manifests / path.name)
    (manifests / "w0-budget-test.yaml").write_text(BUDGET_TEST_MANIFEST, encoding="utf-8")
    log = work / "gateway.log"
    # PYTHONUTF8: the proxy prints a banner that a cp1252 console on Windows cannot encode.
    env = dict(os.environ, GATEWAY_LOG_FILE=str(log), TRACE_FILE=str(trace_file),
               MANIFEST_DIR=str(manifests), LITELLM_MASTER_KEY=MASTER_KEY,
               PYTHONUNBUFFERED="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    procs: list[subprocess.Popen] = []
    try:
        for name, port in BACKENDS:
            procs.append(subprocess.Popen([sys.executable, str(GATEWAY / "fake_backend.py"),
                                           "--name", name, "--port", str(port)], env=env))
        for proc, (_, port) in zip(procs, BACKENDS):
            wait_for(f"http://127.0.0.1:{port}/health", 20, proc)
        port = free_port()
        procs.append(subprocess.Popen([litellm_executable(), "--config", "litellm.config.yaml",
                                       "--port", str(port), "--host", "127.0.0.1"],
                                      cwd=str(GATEWAY), env=env))
        wait_for(f"http://127.0.0.1:{port}/health/liveliness", 90, procs[-1])
        yield {"url": f"http://127.0.0.1:{port}", "log": log, "traces": trace_file}
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def wait_for_line(path: Path, predicate: Callable[[dict], bool], seconds: float = 5.0) -> dict:
    """The callbacks run after the response is sent, so a line may lag the response a little."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        found = [line for line in lines(path) if predicate(line)]
        if found:
            return found[-1]
        time.sleep(0.2)
    raise AssertionError(f"no matching line in {path.name}")


def set_failing(port: int, fail: bool) -> None:
    httpx.post(f"http://127.0.0.1:{port}/control", json={"fail": fail}, timeout=5).raise_for_status()


def calls_served(port: int) -> int:
    return httpx.get(f"http://127.0.0.1:{port}/health", timeout=5).json()["calls"]


def cache_salt_seen(port: int) -> str | None:
    """The cache_salt of the last request the fake backend on `port` answered."""
    return httpx.get(f"http://127.0.0.1:{port}/health", timeout=5).json()["cache_salt"]
