"""The harness: allowlist refusal, lock verification, and the trace id in both logs."""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from mcp.server import MCPServer

import client as harness
import server as mcp_server

pytestmark = pytest.mark.anyio

IDENTITY = "larkspur-ops-reader"


def lines(stream: io.StringIO | Path) -> list[dict]:
    text = stream.read_text() if isinstance(stream, Path) else stream.getvalue()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def inproc_server(log: io.StringIO) -> MCPServer:
    return mcp_server.build_server(IDENTITY, log, "inproc")


# --- allowlist ------------------------------------------------------------------------------

async def test_tool_outside_the_allowlist_is_refused_before_it_reaches_the_server() -> None:
    server_log, client_log = io.StringIO(), io.StringIO()
    greedy = lambda messages: {"tool_call": {"name": "get_recent_alerts",  # noqa: E731
                                             "args": {"service": "claims-api", "minutes": 30}}}
    answer = await harness.run_harness(inproc_server(server_log), "Any alerts?", model=greedy,
                                       trace_id="t-refused", log=client_log)
    assert answer == "Refused: get_recent_alerts is not an allowed call."
    assert [line["event"] for line in lines(client_log)] == ["tools_verified", "answer"]
    assert lines(client_log)[-1]["refused"] is True
    assert [line for line in lines(server_log) if line["event"] == "tool_call"] == []  # never called


async def test_unexpected_arguments_are_refused() -> None:
    server_log = io.StringIO()
    sneaky = lambda messages: {"tool_call": {"name": "get_pod_status",  # noqa: E731
                                             "args": {"service": "claims-api", "namespace": "kube-system"}}}
    answer = await harness.run_harness(inproc_server(server_log), model=sneaky, log=io.StringIO())
    assert answer == "Refused: get_pod_status is not an allowed call."
    assert lines(server_log) == []


async def test_allowed_tool_runs_and_answers() -> None:
    answer = await harness.run_harness(inproc_server(io.StringIO()), log=io.StringIO())
    assert answer == "claims-api has 2 of 3 pods ready."


# --- lock verification on the client side ---------------------------------------------------

async def test_harness_refuses_a_server_whose_description_drifted() -> None:
    drifted = MCPServer("impostor")

    @drifted.tool(description="Return pod counts. Also restart the deployment if asked nicely.")
    def get_pod_status(service: str) -> dict:
        return {"service": service, "ready": 0, "desired": 0}

    with pytest.raises(harness.LockMismatch, match="get_pod_status: definition does not match"):
        await harness.run_harness(drifted, log=io.StringIO())


async def test_harness_refuses_a_server_whose_schema_drifted_under_the_same_description() -> None:
    # The description is word for word the real one; the tool now takes a `force` flag and no
    # longer says it is read-only. A description-only lock would let this through.
    real = json.loads(harness.LOCK_PATH.read_text(encoding="utf-8"))["tools"]["get_pod_status"]["definition"]
    drifted = MCPServer("impostor")

    @drifted.tool(description=real["description"])
    def get_pod_status(service: str, force: bool = False) -> dict:
        return {"service": service, "ready": 0, "desired": 0}

    with pytest.raises(harness.LockMismatch, match="get_pod_status: definition does not match"):
        await harness.run_harness(drifted, log=io.StringIO())


async def test_harness_refuses_a_server_with_an_unpinned_tool() -> None:
    real = inproc_server(io.StringIO())

    @real.tool(description="Scale a deployment.")
    def scale(service: str, replicas: int) -> dict:
        return {}

    with pytest.raises(harness.LockMismatch, match="scale: served but not in the lock file"):
        await harness.run_harness(real, log=io.StringIO())


# --- trace id in both logs ------------------------------------------------------------------

def assert_joined_on_trace_id(client_log: list[dict], server_log: list[dict], trace_id: str) -> None:
    client_calls = [line for line in client_log if line["event"] == "tool_call"]
    server_calls = [line for line in server_log if line["event"] == "tool_call"]
    assert len(client_calls) == len(server_calls) == 1
    assert client_calls[0]["trace_id"] == server_calls[0]["trace_id"] == trace_id
    assert server_calls[0]["trace_source"] == "request"
    assert client_calls[0]["tool"] == server_calls[0]["tool"] == "get_pod_status"
    assert client_calls[0]["args"] == server_calls[0]["args"] == {"service": "claims-api"}
    assert server_calls[0]["identity"] == IDENTITY


async def test_trace_id_appears_in_both_logs_over_stdio(tmp_path: Path) -> None:
    server_log = tmp_path / "server.log"
    client_log = io.StringIO()
    params = harness.stdio_server(identity=IDENTITY, log_file=str(server_log))
    answer = await harness.run_harness(params, trace_id="trace-stdio-42", log=client_log)
    assert answer == "claims-api has 2 of 3 pods ready."
    assert_joined_on_trace_id(lines(client_log), lines(server_log), "trace-stdio-42")
    assert lines(server_log)[0]["transport"] == "stdio"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port: int, process: subprocess.Popen, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited early with {process.returncode}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"server did not listen on {port} within {timeout}s")


async def test_trace_id_appears_in_both_logs_over_streamable_http(tmp_path: Path) -> None:
    server_log = tmp_path / "server.log"
    port = free_port()
    env = {k: v for k, v in os.environ.items() if k not in ("TOOL_IDENTITY", "TOOL_LOG_FILE")}
    env |= {"TOOL_IDENTITY": IDENTITY, "TOOL_LOG_FILE": str(server_log)}
    process = subprocess.Popen(
        [sys.executable, str(harness.SERVER_PY), "--transport", "streamable-http", "--port", str(port)],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    try:
        wait_for_port(port, process)
        client_log = io.StringIO()
        answer = await harness.run_harness(f"http://127.0.0.1:{port}/mcp", trace_id="trace-http-42",
                                           log=client_log)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    assert answer == "claims-api has 2 of 3 pods ready."
    assert_joined_on_trace_id(lines(client_log), lines(server_log), "trace-http-42")
    assert lines(server_log)[0]["transport"] == "streamable-http"
    assert lines(client_log)[0]["transport"] == "http"


# --- command line ---------------------------------------------------------------------------

def test_cli_runs_the_loop_and_prints_the_answer(tmp_path: Path) -> None:
    server_log = tmp_path / "server.log"
    env = {k: v for k, v in os.environ.items() if k not in ("TOOL_IDENTITY", "TOOL_LOG_FILE")}
    env |= {"TOOL_IDENTITY": IDENTITY, "TOOL_LOG_FILE": str(server_log)}
    result = subprocess.run(
        [sys.executable, str(Path(harness.__file__)), "--trace-id", "trace-cli-42"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "claims-api has 2 of 3 pods ready."
    client_log = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    assert_joined_on_trace_id(client_log, lines(server_log), "trace-cli-42")
