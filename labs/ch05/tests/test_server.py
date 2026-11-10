"""The server's startup checks: identity, pinned descriptions, and the call log."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import server
from server import (
    LOCK_PATH, LockMismatch, advertised_definitions, build_server, definition_hash, read_lock,
    require_identity, verify_lock,
)

SERVER_PY = Path(server.__file__)
SUBPROCESS_TIMEOUT = 60


def run_server(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Start server.py as a subprocess with exactly `env` and let it exit on its own."""
    return subprocess.run(
        [sys.executable, str(SERVER_PY), *args],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT,
    )


def base_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in ("TOOL_IDENTITY", "TOOL_LOG_FILE")}


# --- identity -------------------------------------------------------------------------------

def test_require_identity_refuses_when_unset(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        require_identity({})
    assert exc.value.code == 2
    assert "TOOL_IDENTITY" in capsys.readouterr().err


def test_require_identity_refuses_blank_or_spaced_values() -> None:
    with pytest.raises(SystemExit):
        require_identity({"TOOL_IDENTITY": "   "})
    with pytest.raises(SystemExit):
        require_identity({"TOOL_IDENTITY": "ops reader"})
    assert require_identity({"TOOL_IDENTITY": " larkspur-ops-reader "}) == "larkspur-ops-reader"


def test_process_refuses_to_start_without_identity() -> None:
    result = run_server(env=base_env())
    assert result.returncode == 2
    assert "refusing to start" in result.stderr and "TOOL_IDENTITY" in result.stderr
    assert result.stdout == ""  # nothing was served


def test_process_starts_with_identity_and_logs_it(tmp_path: Path) -> None:
    log_file = tmp_path / "server.log"
    env = base_env() | {"TOOL_IDENTITY": "larkspur-ops-reader", "TOOL_LOG_FILE": str(log_file)}
    result = run_server(env=env)  # stdin is /dev/null, so the stdio server exits on EOF
    assert result.returncode == 0, result.stderr
    start = json.loads(log_file.read_text().splitlines()[0])
    assert start["event"] == "server_start"
    assert start["identity"] == "larkspur-ops-reader"
    assert start["transport"] == "stdio"


# --- pinned definitions ---------------------------------------------------------------------

def served_definitions() -> dict:
    return advertised_definitions(build_server("test", io.StringIO(), "test"))


def test_committed_lock_matches_served_definitions() -> None:
    # If this fails, a tool changed without `python server.py --write-lock` being run.
    served = served_definitions()
    assert set(served) == {"get_pod_status", "get_recent_alerts"}
    verify_lock(served, read_lock(LOCK_PATH))


def test_lock_covers_every_field_a_client_acts_on() -> None:
    entry = served_definitions()["get_recent_alerts"]
    assert set(entry) == {"name", "description", "inputSchema", "outputSchema", "annotations"}
    assert entry["annotations"]["readOnlyHint"] is True
    # A typed result gives the output schema named fields, so a client's check means something.
    assert entry["outputSchema"]["required"] == ["service", "window_minutes", "count", "alerts"]
    assert entry["outputSchema"]["$defs"]["Alert"]["properties"]["severity"]["enum"] == ["critical", "warning", "info"]


@pytest.mark.parametrize("change", [
    lambda d: d.update(description=d["description"] + " Also deletes the pod if it is unhealthy."),
    lambda d: d["inputSchema"]["properties"].update(force={"type": "boolean"}),
    lambda d: d["annotations"].update(readOnlyHint=False, destructiveHint=True),
    lambda d: d["outputSchema"].update(additionalProperties=True),
])
def test_any_change_to_a_definition_is_detected(change) -> None:
    served = served_definitions()
    lock = read_lock(LOCK_PATH)
    change(served["get_pod_status"])
    with pytest.raises(LockMismatch, match="get_pod_status: definition changed"):
        verify_lock(served, lock)


def test_key_order_does_not_change_the_hash() -> None:
    definition = served_definitions()["get_pod_status"]
    reordered = dict(reversed(list(definition.items())))
    assert definition_hash(reordered) == definition_hash(definition)


def test_unpinned_and_missing_tools_are_detected() -> None:
    lock = {"get_pod_status": definition_hash({"name": "get_pod_status"})}
    with pytest.raises(LockMismatch, match="get_recent_alerts: not in the lock file"):
        verify_lock({"get_pod_status": {"name": "get_pod_status"}, "get_recent_alerts": {"name": "b"}}, lock)
    with pytest.raises(LockMismatch, match="get_pod_status: in the lock file but not served"):
        verify_lock({}, lock)


def test_process_refuses_to_start_when_lock_is_stale(tmp_path: Path) -> None:
    data = json.loads(LOCK_PATH.read_text())
    data["tools"]["get_pod_status"]["sha256"] = definition_hash({"name": "an older definition"})
    stale = tmp_path / "tools.lock.json"
    stale.write_text(json.dumps(data))
    env = base_env() | {"TOOL_IDENTITY": "larkspur-ops-reader"}
    result = run_server("--lock", str(stale), env=env)
    assert result.returncode == 2
    assert "refusing to start" in result.stderr
    assert "get_pod_status: definition changed" in result.stderr


def test_process_refuses_to_start_without_a_lock(tmp_path: Path) -> None:
    env = base_env() | {"TOOL_IDENTITY": "larkspur-ops-reader"}
    result = run_server("--lock", str(tmp_path / "missing.json"), env=env)
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_write_lock_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "tools.lock.json"
    result = run_server("--write-lock", "--lock", str(target), env=base_env())  # no identity needed
    assert result.returncode == 0, result.stderr
    assert read_lock(target) == read_lock(LOCK_PATH)


# --- the tools and the call log -------------------------------------------------------------

@pytest.mark.anyio
async def test_tools_are_read_only_and_log_every_call() -> None:
    from mcp import Client

    log = io.StringIO()
    srv = build_server("larkspur-ops-reader", log, "inproc")
    async with Client(srv) as client:
        for tool in (await client.list_tools()).tools:
            assert tool.annotations is not None and tool.annotations.read_only_hint is True

        ok = await client.call_tool("get_pod_status", {"service": "claims-api"}, meta={"trace_id": "t-1"})
        assert ok.is_error is False
        assert ok.structured_content["ready"] == 2 and ok.structured_content["desired"] == 3

        alerts = await client.call_tool("get_recent_alerts", {"service": "claims-api", "minutes": 30})
        assert alerts.structured_content["count"] == 2  # the 95-minute-old alert is outside the window

        bad = await client.call_tool("get_pod_status", {"service": "payroll"})
        assert bad.is_error is True

    lines = [json.loads(line) for line in log.getvalue().splitlines()]
    assert [line["tool"] for line in lines] == ["get_pod_status", "get_recent_alerts", "get_pod_status"]
    assert all(line["identity"] == "larkspur-ops-reader" for line in lines)
    assert lines[0]["trace_id"] == "t-1" and lines[0]["trace_source"] == "request"
    assert lines[1]["trace_source"] == "generated" and len(lines[1]["trace_id"]) == 32
    assert lines[2]["ok"] is False and "payroll" in lines[2]["error"]
