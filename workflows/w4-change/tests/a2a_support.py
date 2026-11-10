"""Shared constants, helpers, and server launchers for W4's A2A tests (test_a2a.py and test_eval.py).

The analyst and risk-scorer A2A servers are launched as subprocesses, the way the scripts run; both test
files use the `analyst_server` and `risk_server` fixtures that conftest.py builds on `launch` below.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

SCRIBE_IDENTITY = "larkspur-scribe"
ANALYST_IDENTITY = "larkspur-analyst"
RISK_SCORER_IDENTITY = "larkspur-risk-scorer"
SCRIBE_TOKEN = "test-token-for-the-scribe-0001"     # test values, not secrets
OTHER_TOKEN = "test-token-for-someone-else-0002"
ANALYST_CALLERS = f"{SCRIBE_IDENTITY}={SCRIBE_TOKEN},larkspur-other={OTHER_TOKEN}"
RISK_CALLERS = f"{SCRIBE_IDENTITY}={SCRIBE_TOKEN},larkspur-other={OTHER_TOKEN}"
OUR_ENV = ("AGENT_IDENTITY", "AGENT_LOG_FILE", "AGENT_TOKEN", "ANALYST_CALLER_TOKENS",
           "RISK_SCORER_CALLER_TOKENS")
DEVNULL = open(os.devnull, "w")  # noqa: SIM115  (one sink for the whole test run)


def base_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in OUR_ENV}


def lines(path: Path) -> list[dict]:
    text = path.read_text() if path.exists() else ""
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port: int, process: subprocess.Popen, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"process exited early with {process.returncode}: {process.stderr.read()}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"nothing listening on {port} within {timeout}s")


def launch(module, identity: str, callers_env: str, callers: str, folder: Path,
           extra: dict[str, str] | None = None) -> SimpleNamespace:
    """Start one A2A server (analyst or risk_scorer) as a subprocess on a free port. `extra` adds
    environment the live wiring needs (the risk scorer's model seam pointed at the gateway)."""
    agent_log = folder / "agent.log"
    port = free_port()
    env = base_env() | {"AGENT_IDENTITY": identity, "AGENT_LOG_FILE": str(agent_log), callers_env: callers}
    env.update(extra or {})
    process = subprocess.Popen([sys.executable, str(Path(module.__file__)), "--port", str(port)], env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True)
    wait_for_port(port, process)
    return SimpleNamespace(url=f"http://127.0.0.1:{port}", agent_log=agent_log, process=process)


def stop(server: SimpleNamespace) -> None:
    server.process.terminate()
    try:
        server.process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.process.kill()
        server.process.wait(timeout=10)
