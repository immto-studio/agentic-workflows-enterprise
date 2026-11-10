"""W3's writer and ServiceNow MCP servers: the locks match what they serve, a token is required, a write is not
annotated read-only, a write runs only under an approval that covers it and changes the cluster, a write whose
approval cannot be checked is refused and logged, the ServiceNow read returns the changes (with the planted
ticket) and the write records the change once."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from mcp import Client

W3 = Path(__file__).resolve().parents[1]
SERVERS = W3 / "servers"
for folder in (SERVERS, W3 / "approval", W3.parent / "w1-knowledge-assistant" / "knowledge-server"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from actor_transport import ActorMCP  # noqa: E402
from approval_service import Service, serve as serve_approvals  # noqa: E402
from cluster_state import ClusterState  # noqa: E402

from conftest import (SERVICE_KEY, SECRET, USERS, approver_token, free_port, membership_table,  # noqa: E402
                      APPROVERS)

W3_SECRET = "w3-lab-secret-for-tests-at-least-32-bytes"


def w3_token(user: str, **overrides) -> str:
    """A token shaped like the one W3's runtime gets for its own servers (W3's app and scope)."""
    from access import issue
    from w3_server import W3_SCOPE, W3_SERVERS_APP
    from common import W3_RUNTIME
    shape = {"scope": W3_SCOPE, "client": W3_RUNTIME, "audience": W3_SERVERS_APP, **overrides}
    return issue(SECRET, USERS[user], f"{user}@larkspur.example", **shape)


def call(url: str, token: str, tool: str, meta: dict | None = None, **args):
    async def go():
        async with Client(ActorMCP(url, token)) as client:
            return await client.call_tool(tool, args, meta=meta or {})
    return asyncio.run(go())


def tools_of(url: str, token: str):
    async def go():
        async with Client(ActorMCP(url, token)) as client:
            return (await client.list_tools()).tools
    return asyncio.run(go())


@pytest.fixture
def approval_server(tmp_path):
    """The approval service behind its HTTP layer; a test that needs it gone shuts the server down itself."""
    import io
    table = membership_table()
    service = Service(tmp_path / "approvals.sqlite", lambda: table, SECRET, APPROVERS, io.StringIO())
    server: ThreadingHTTPServer = serve_approvals(service, SERVICE_KEY, port=free_port())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield url, service, server
    server.shutdown()
    server.server_close()


@pytest.fixture
def approval_url(approval_server):
    url, service, _server = approval_server
    return url, service


@pytest.fixture
def running_writers(tmp_path, approval_url):
    """The writer and ServiceNow servers as processes, under their identities, over a shared state file."""
    url, _service = approval_url
    state = tmp_path / "cluster.json"
    snow_state = tmp_path / "servicenow.json"
    env_common = {**os.environ, "W2_TOKEN_SECRET": SECRET, "APPROVAL_URL": url, "APPROVAL_KEY": SECRET if False else SERVICE_KEY}
    procs, out = [], {}
    specs = {
        "writer": ("writer_server.py", "larkspur-ops-restarter", {"CLUSTER_STATE_FILE": str(state)}),
        "servicenow": ("servicenow_server.py", "larkspur-ops-change-writer", {"SERVICENOW_STATE_FILE": str(snow_state)}),
    }
    for name, (script, identity, extra) in specs.items():
        port = free_port()
        log = tmp_path / f"{name}.log"
        env = {**env_common, "TOOL_IDENTITY": identity, "TOOL_LOG_FILE": str(log), **extra}
        stderr = (tmp_path / f"{name}.stderr").open("w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(SERVERS / script), "--port", str(port)],
                                env=env, stdout=subprocess.DEVNULL, stderr=stderr, text=True)
        procs.append((proc, stderr, tmp_path / f"{name}.stderr"))
        out[name] = (f"http://127.0.0.1:{port}/mcp", log, port)
    deadline = time.time() + 60
    for name, (_, _, port) in out.items():
        while time.time() < deadline:
            proc = next(p for p in procs if True)
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.2)
    yield {name: (u, log) for name, (u, log, _) in out.items()}, state, snow_state, url
    for proc, stderr, path in procs:
        proc.terminate()
        proc.wait(timeout=30)
        stderr.close()


def _approve(approval_url, service, tool, args, requester="oncall.engineer", approver="incident.responder"):
    url, svc = approval_url
    record = svc.request(workflow="w3-incident", trace_id="run-s1", tool=tool, args=args, service=service,
                         requester_oid=USERS[requester], requester_upn=f"{requester}@larkspur.example")
    svc.decide(record["approval_id"], approver_token(approver), approved=True)
    return record["approval_id"]


def test_each_lock_matches_what_its_server_serves(running_writers):
    servers, *_ = running_writers
    for name, (url, _) in servers.items():
        lock = json.loads((SERVERS / f"{name}.lock.json").read_text(encoding="utf-8"))["tools"]
        served = {t.name for t in tools_of(url, w3_token("oncall.engineer"))}
        assert served == set(lock), name


def test_the_writes_are_not_annotated_read_only(running_writers):
    servers, *_ = running_writers
    writes = {t.name: t for t in tools_of(servers["writer"][0], w3_token("oncall.engineer"))}
    for name, tool in writes.items():
        assert tool.annotations.read_only_hint is False, name
        assert tool.annotations.destructive_hint is True, name
    snow = {t.name: t for t in tools_of(servers["servicenow"][0], w3_token("oncall.engineer"))}
    assert snow["get_recent_changes"].annotations.read_only_hint is True
    assert snow["record_change"].annotations.read_only_hint is False


def test_a_write_runs_only_under_an_approval_that_covers_it(running_writers, approval_url):
    servers, state, _snow, _url = running_writers
    writer_url = servers["writer"][0]
    token = w3_token("oncall.engineer")
    # No approval in _meta: refused, nothing changes.
    nope = call(writer_url, token, "restart_deployment", service="claims-api")
    assert nope.is_error and "step was not taken" in "".join(getattr(b, "text", "") for b in nope.content)
    assert ClusterState(state).current("claims-api")["generation"] == 1
    # A covering approval: the restart runs and heals the deployment.
    approval_id = _approve(approval_url, "claims-api", "restart_deployment", {"service": "claims-api"})
    ok = call(writer_url, token, "restart_deployment", meta={"trace_id": "run-s1", "approval_id": approval_id},
              service="claims-api")
    assert not ok.is_error
    assert ClusterState(state).current("claims-api")["ready"] == 3
    # The same approval again: the writer finds it applied and does not change anything further.
    again = call(writer_url, token, "restart_deployment", meta={"trace_id": "run-s1", "approval_id": approval_id},
                 service="claims-api")
    assert again.is_error and "step was not taken" in "".join(getattr(b, "text", "") for b in again.content)


def test_a_write_is_refused_and_logged_when_the_approval_service_is_down(running_writers, approval_server):
    servers, state, _snow, _url = running_writers
    writer_url, writer_log = servers["writer"]
    url, service, server = approval_server
    approval_id = _approve((url, service), "claims-api", "restart_deployment", {"service": "claims-api"})
    server.shutdown()
    server.server_close()
    down = call(writer_url, w3_token("oncall.engineer"), "restart_deployment",
                meta={"trace_id": "run-s1", "approval_id": approval_id}, service="claims-api")
    text = "".join(getattr(b, "text", "") for b in down.content)
    assert down.is_error and "could not be asked, so the step was not taken" in text
    assert ClusterState(state).current("claims-api")["generation"] == 1, "nothing changed"
    lines = [json.loads(line) for line in Path(writer_log).read_text(encoding="utf-8").splitlines() if line.strip()]
    refused = [entry for entry in lines if entry.get("tool") == "restart_deployment" and entry.get("ok") is False]
    assert refused and refused[-1]["refused"].startswith("approval not checked"), "the refusal has its audit line"


def test_a_write_needs_a_valid_token(running_writers):
    servers, *_ = running_writers
    result = call(servers["writer"][0], "not-a-token", "restart_deployment",
                  meta={"trace_id": "run-s1", "approval_id": "APR-x"}, service="claims-api")
    assert result.is_error and "token refused" in "".join(getattr(b, "text", "") for b in result.content)


def test_the_servicenow_read_returns_the_changes_with_the_planted_ticket(running_writers):
    servers, *_ = running_writers
    result = call(servers["servicenow"][0], w3_token("oncall.engineer"), "get_recent_changes",
                  service="claims-api", minutes=10080)
    assert not result.is_error
    data = result.structured_content
    numbers = {c["number"] for c in data["changes"]}
    assert "CHG0030052" in numbers and data["count"] == 2


def test_a_hidden_service_is_refused_by_both_servers(running_writers):
    servers, *_ = running_writers
    token = w3_token("oncall.engineer")  # not in incident response; may not see fraud-scoring
    changes = call(servers["servicenow"][0], token, "get_recent_changes", service="fraud-scoring", minutes=60)
    assert changes.is_error and "among the ones you can ask about" in "".join(getattr(b, "text", "") for b in changes.content)
    # The writer refuses a service the caller may not see before it ever checks the approval (run_write order).
    restart = call(servers["writer"][0], token, "restart_deployment",
                   meta={"trace_id": "run-s1", "approval_id": "APR-dummy"}, service="fraud-scoring")
    assert restart.is_error and "among the ones you can ask about" in "".join(getattr(b, "text", "") for b in restart.content)
