"""The A2A demo: scribe to analyst, authentication, the refusals, and one trace across four components."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import agent_common
import analyst
import scribe
import trace_setup as tracing

pytestmark = pytest.mark.anyio

ANALYST_IDENTITY = "larkspur-analyst"
SCRIBE_IDENTITY = "larkspur-scribe"
TOOL_IDENTITY = "larkspur-ops-reader"
SCRIBE_TOKEN = "test-token-for-the-scribe-0001"     # test values, not secrets
OTHER_TOKEN = "test-token-for-someone-else-0002"
CALLER_TOKENS = f"{SCRIBE_IDENTITY}={SCRIBE_TOKEN},larkspur-other={OTHER_TOKEN}"
OUR_ENV = ("AGENT_IDENTITY", "AGENT_LOG_FILE", "AGENT_TOKEN", "ANALYST_CALLER_TOKENS", "TOOL_IDENTITY",
           "TOOL_LOG_FILE")
DEVNULL = open(os.devnull, "w")  # noqa: SIM115  (one sink for the whole module)


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


@pytest.fixture(scope="module")
def analyst_server(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """One analyst process for the module, launching the MCP server per task as a stdio subprocess."""
    folder = tmp_path_factory.mktemp("analyst")
    paths = SimpleNamespace(server_log=folder / "server.log", agent_log=folder / "analyst.log",
                            trace_file=Path(os.environ[tracing.TRACE_FILE_ENV]))
    port = free_port()
    env = base_env() | {"AGENT_IDENTITY": ANALYST_IDENTITY, "AGENT_LOG_FILE": str(paths.agent_log),
                        "ANALYST_CALLER_TOKENS": CALLER_TOKENS,
                        "TOOL_IDENTITY": TOOL_IDENTITY, "TOOL_LOG_FILE": str(paths.server_log)}
    process = subprocess.Popen([sys.executable, str(Path(analyst.__file__)), "--port", str(port)], env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        wait_for_port(port, process)
        yield SimpleNamespace(url=f"http://127.0.0.1:{port}", **vars(paths))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


async def send(url: str, text: str, metadata: dict, token: str = SCRIBE_TOKEN,
               traceparent: str | None = None) -> scribe.TaskRun:
    """One task with the given token, as the scribe sends it, without the scribe's span."""
    async with httpx.AsyncClient(timeout=30) as plain:
        card = await scribe.discover(plain, url, DEVNULL)
    client, http = scribe.connect(card, token, origin=url, traceparent=traceparent)
    async with http:
        return await scribe.send_task(client, text, metadata, DEVNULL)


# --- the happy path -------------------------------------------------------------------------

async def test_scribe_drives_a_task_to_completion_and_writes_the_artifact(analyst_server, tmp_path: Path) -> None:
    out = tmp_path / "summary.json"
    result = await scribe.run_scribe(analyst_server.url, "claims-api", out, SCRIBE_IDENTITY, SCRIBE_TOKEN, log=DEVNULL)

    assert result["states"] == ["TASK_STATE_SUBMITTED", "TASK_STATE_WORKING", "TASK_STATE_COMPLETED"]
    assert result["final_state"] == "TASK_STATE_COMPLETED"
    assert result["analyst"]["name"] == "analyst" and result["requested_by"] == SCRIBE_IDENTITY
    [artifact] = result["artifacts"]
    assert artifact["name"] == "alert-summary"
    assert artifact["text"].startswith("claims-api had 2 alerts in the last 60 minutes (1 critical, 1 warning).")
    data = artifact["data"]
    assert data["service"] == "claims-api" and data["count"] == 2 and data["window_minutes"] == 60
    assert data["by_severity"] == {"critical": 1, "warning": 1, "info": 0}
    assert [a["severity"] for a in data["alerts"]] == ["critical", "warning"]
    assert data["produced_by"] == ANALYST_IDENTITY and data["requested_by"] == SCRIBE_IDENTITY
    assert data["trace_id"] == result["trace_id"] and tracing.is_trace_id(result["trace_id"])
    assert json.loads(out.read_text()) == result  # the file is the result, byte for byte


async def test_analyst_card_is_public_and_declares_the_bearer_scheme(analyst_server) -> None:
    async with httpx.AsyncClient() as http:
        card = (await http.get(f"{analyst_server.url}/.well-known/agent-card.json")).json()  # no token
    assert card["name"] == "analyst"
    assert [skill["id"] for skill in card["skills"]] == ["summarize-alerts"]
    assert card["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
    assert card["capabilities"]["streaming"] is True
    assert card["securitySchemes"]["larkspur-bearer"]["httpAuthSecurityScheme"]["scheme"] == "bearer"
    assert card["securityRequirements"] == [{"schemes": {"larkspur-bearer": {}}}]


# --- authentication --------------------------------------------------------------------------

def rpc_body() -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "nope"}}


@pytest.mark.parametrize("headers, reason", [
    ({}, "no bearer token"),
    ({"Authorization": "Bearer not-a-token-anyone-was-given"}, "unknown token"),
    ({"Authorization": f"Basic {SCRIBE_TOKEN}"}, "unknown token"),
])
async def test_requests_without_a_known_token_get_401(analyst_server, headers: dict, reason: str) -> None:
    calls_before = len([e for e in lines(analyst_server.server_log) if e["event"] == "tool_call"])
    async with httpx.AsyncClient(timeout=10) as http:
        r = await http.post(f"{analyst_server.url}/", json=rpc_body(), headers=headers)
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")
    assert [e for e in lines(analyst_server.agent_log) if e["event"] == "unauthenticated"][-1]["reason"] == reason
    assert len([e for e in lines(analyst_server.server_log) if e["event"] == "tool_call"]) == calls_before


async def test_a_claimed_identity_that_is_not_the_tokens_is_rejected(analyst_server) -> None:
    run = await send(analyst_server.url, "Summarize the alerts for claims-api",
                     {agent_common.TRACE_ID_KEY: tracing.new_trace_id(),
                      agent_common.CALLER_IDENTITY_KEY: SCRIBE_IDENTITY}, token=OTHER_TOKEN)
    assert run.final_state == "TASK_STATE_REJECTED"
    assert run.status_messages == [f"refused: the request claims to come from {SCRIBE_IDENTITY!r} "
                                   "but its token belongs to 'larkspur-other'"]


async def test_the_scribe_sends_no_token_to_an_agent_without_a_bearer_scheme(analyst_server) -> None:
    async with httpx.AsyncClient(timeout=10) as plain:
        card = await scribe.discover(plain, analyst_server.url, DEVNULL)
    del card.security_schemes["larkspur-bearer"]
    with pytest.raises(scribe.NoBearerScheme):
        scribe.connect(card, SCRIBE_TOKEN, origin=analyst_server.url)


async def test_the_scribe_sends_no_token_to_an_interface_on_another_origin(analyst_server) -> None:
    async with httpx.AsyncClient(timeout=10) as plain:
        card = await scribe.discover(plain, analyst_server.url, DEVNULL)
    card.supported_interfaces[0].url = "http://127.0.0.1:1/"  # a card can name any host
    with pytest.raises(scribe.ForeignInterface):
        scribe.connect(card, SCRIBE_TOKEN, origin=analyst_server.url)
    assert scribe.same_origin("http://127.0.0.1:8766/", "http://127.0.0.1:8766")
    assert not scribe.same_origin("http://127.0.0.1:8766/", "https://127.0.0.1:8766/")


def test_caller_tokens_are_parsed_and_compared() -> None:
    tokens = agent_common.parse_caller_tokens(CALLER_TOKENS)
    assert agent_common.subject_for(SCRIBE_TOKEN, tokens) == SCRIBE_IDENTITY
    assert agent_common.subject_for(SCRIBE_TOKEN[:-1], tokens) is None
    for bad in ("", "larkspur-scribe", "larkspur-scribe=short", "two words=" + SCRIBE_TOKEN):
        with pytest.raises(ValueError):
            agent_common.parse_caller_tokens(bad)


# --- refusals -------------------------------------------------------------------------------

def test_require_agent_identity() -> None:
    with pytest.raises(SystemExit) as exc:
        agent_common.require_agent_identity({})
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        agent_common.require_agent_identity({"AGENT_IDENTITY": "two words"})
    assert agent_common.require_agent_identity({"AGENT_IDENTITY": " larkspur-scribe "}) == "larkspur-scribe"


def test_analyst_refuses_to_start_without_identity() -> None:
    env = base_env() | {"TOOL_IDENTITY": TOOL_IDENTITY, "ANALYST_CALLER_TOKENS": CALLER_TOKENS}
    result = subprocess.run([sys.executable, str(Path(analyst.__file__)), "--port", str(free_port())],
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2
    assert "refusing to start" in result.stderr and "AGENT_IDENTITY" in result.stderr


def test_analyst_refuses_to_start_without_caller_tokens() -> None:
    env = base_env() | {"AGENT_IDENTITY": ANALYST_IDENTITY, "TOOL_IDENTITY": TOOL_IDENTITY}
    result = subprocess.run([sys.executable, str(Path(analyst.__file__)), "--port", str(free_port())],
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2 and "ANALYST_CALLER_TOKENS" in result.stderr


def test_analyst_refuses_to_start_without_a_tool_identity_for_its_server() -> None:
    env = base_env() | {"AGENT_IDENTITY": ANALYST_IDENTITY, "ANALYST_CALLER_TOKENS": CALLER_TOKENS}
    result = subprocess.run([sys.executable, str(Path(analyst.__file__)), "--port", str(free_port())],
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2 and "TOOL_IDENTITY" in result.stderr


def test_scribe_refuses_to_start_without_identity(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, str(Path(scribe.__file__)), "--out", str(tmp_path / "x.json")],
                            env=base_env() | {"AGENT_TOKEN": SCRIBE_TOKEN}, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2
    assert "refusing to start" in result.stderr and "AGENT_IDENTITY" in result.stderr
    assert not (tmp_path / "x.json").exists()


def test_scribe_refuses_to_start_without_a_token(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, str(Path(scribe.__file__)), "--out", str(tmp_path / "x.json")],
                            env=base_env() | {"AGENT_IDENTITY": SCRIBE_IDENTITY}, capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 2 and "AGENT_TOKEN" in result.stderr


async def test_task_without_a_trace_id_is_rejected(analyst_server) -> None:
    calls_before = len([e for e in lines(analyst_server.server_log) if e["event"] == "tool_call"])
    run = await send(analyst_server.url, "Summarize the alerts for claims-api",
                     {agent_common.CALLER_IDENTITY_KEY: SCRIBE_IDENTITY})
    assert run.final_state == "TASK_STATE_REJECTED"
    assert run.states == ["TASK_STATE_SUBMITTED", "TASK_STATE_REJECTED"]
    assert run.status_messages == ["refused: request metadata carries no trace_id; the analyst does not run untraced work"]
    assert run.artifacts == []
    rejected = [e for e in lines(analyst_server.agent_log) if e["event"] == "task_rejected"]
    assert rejected and rejected[-1]["task_id"] == run.task_id and rejected[-1]["caller"] == SCRIBE_IDENTITY
    # The MCP server never heard about it.
    assert len([e for e in lines(analyst_server.server_log) if e["event"] == "tool_call"]) == calls_before


async def test_task_outside_the_skill_is_rejected(analyst_server) -> None:
    run = await send(analyst_server.url, "Restart claims-api", {agent_common.TRACE_ID_KEY: tracing.new_trace_id()})
    assert run.final_state == "TASK_STATE_REJECTED"
    assert "only summarizes alerts" in run.status_messages[0]


# --- one trace id, four components ----------------------------------------------------------

async def test_one_trace_id_across_scribe_analyst_harness_and_server(analyst_server, tmp_path: Path) -> None:
    trace_id = tracing.new_trace_id()
    scribe_log = tmp_path / "scribe.log"
    with scribe_log.open("w") as log:
        result = await scribe.run_scribe(analyst_server.url, "document-ocr", tmp_path / "out.json", SCRIBE_IDENTITY,
                                         SCRIBE_TOKEN, minutes=30, trace_id=trace_id, log=log)
    assert result["final_state"] == "TASK_STATE_COMPLETED" and result["trace_id"] == trace_id

    # 1. The scribe's request carried it, in the metadata, next to the W3C traceparent.
    sent = [e for e in lines(scribe_log) if e["event"] == "task_sent"][0]
    assert sent["trace_id"] == trace_id and sent["traceparent"].split("-")[1] == trace_id
    # 2. The analyst saw it and logged it.
    received = [e for e in lines(analyst_server.agent_log) if e.get("trace_id") == trace_id]
    assert {e["event"] for e in received} >= {"task_received", "tools_verified", "tool_call", "answer", "task_completed"}
    task = [e for e in received if e["event"] == "task_received"][0]
    assert task["caller"] == SCRIBE_IDENTITY  # the token's subject
    assert task["trace_source"] == "header"   # the W3C header, not the metadata copy
    # 3. The MCP server logged the tool call under it, from the request `_meta`, under its own identity.
    served = [e for e in lines(analyst_server.server_log) if e["event"] == "tool_call" and e["trace_id"] == trace_id]
    assert len(served) == 1 and served[0]["trace_source"] == "request"
    assert served[0]["identity"] == TOOL_IDENTITY and served[0]["args"] == {"service": "document-ocr", "minutes": 30}
    # 4. The spans: one per component, all with this trace id, parented in call order.
    spans = {(s["attributes"].get(tracing.LARKSPUR_COMPONENT), s["name"]): s
             for s in tracing.read_spans(analyst_server.trace_file) if s["trace_id"] == trace_id}
    scribe_span = spans[("scribe", "invoke_agent analyst")]
    analyst_span = spans[("analyst", "invoke_agent analyst")]
    harness_span = spans[("harness", "invoke_agent harness")]
    call_span = spans[("harness", "execute_tool get_recent_alerts")]
    server_span = spans[("mcp-server", "execute_tool get_recent_alerts")]
    assert scribe_span["kind"] == "CLIENT" and analyst_span["kind"] == "SERVER"
    assert scribe_span["parent_span_id"] is None  # the run's root, a real one
    assert analyst_span["parent_span_id"] == scribe_span["span_id"]
    assert harness_span["parent_span_id"] == analyst_span["span_id"]
    assert call_span["parent_span_id"] == harness_span["span_id"]
    assert analyst_span["resource"][tracing.LARKSPUR_IDENTITY] == ANALYST_IDENTITY
    assert server_span["resource"][tracing.LARKSPUR_IDENTITY] == TOOL_IDENTITY
    assert analyst_span["attributes"][tracing.LARKSPUR_CALLER_IDENTITY] == SCRIBE_IDENTITY
    assert analyst_span["attributes"][tracing.A2A_TASK_ID] == result["task_id"]
    assert all(s["attributes"][tracing.LARKSPUR_TRACE_ID] == trace_id
               for s in (scribe_span, analyst_span, harness_span, call_span, server_span))
