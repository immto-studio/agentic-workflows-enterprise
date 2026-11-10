"""W2's three servers: locks, read-only annotations, the service map before every read, and the fakes'
planted text where an attacker could put it."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from mcp import Client

from conftest import AUDIT_KEY, SECRET, SERVERS, USERS, W2, free_port, log_events, w2_token

sys.path.insert(0, str(W2.parent / "w1-knowledge-assistant" / "knowledge-server"))
from actor_transport import ActorMCP  # noqa: E402
from audit_hmac import text_hmac  # noqa: E402

import fakes  # noqa: E402

sys.path.insert(0, str(W2))
import vet  # noqa: E402

CATALOG = yaml.safe_load((W2 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
MANIFEST = yaml.safe_load((W2 / "manifest" / "w2-ops-assistant.yaml").read_text(encoding="utf-8"))


def call(url: str, token: str, tool: str, **args):
    async def go():
        async with Client(ActorMCP(url, token)) as client:
            return await client.call_tool(tool, args)
    return asyncio.run(go())


def tools_of(url: str, token: str) -> list:
    async def go():
        async with Client(ActorMCP(url, token)) as client:
            return (await client.list_tools()).tools
    return asyncio.run(go())


def test_every_lock_matches_what_its_server_serves(running_servers):
    for name, (url, _) in running_servers.items():
        lock = json.loads((W2 / "servers" / f"{name}.lock.json").read_text(encoding="utf-8"))["tools"]
        served = {t.name: t for t in tools_of(url, w2_token("oncall.engineer"))}
        assert set(served) == set(lock), name
        assert len(served) == SERVERS[name]


def test_every_tool_is_annotated_read_only_and_listed_in_the_catalog_and_the_manifest(running_servers):
    served: set[str] = set()
    for name, (url, _) in running_servers.items():
        for tool in tools_of(url, w2_token("oncall.engineer")):
            served.add(tool.name)
            a = tool.annotations
            assert (a.read_only_hint, a.destructive_hint, a.open_world_hint) == (True, False, False), tool.name
            assert "not instructions" in tool.description or tool.name == "get_pod_status", tool.name
    assert served == set(CATALOG["tools"]) == set(MANIFEST["tools"])
    for tool, spec in CATALOG["tools"].items():
        assert set(MANIFEST["tools"][tool]["args"]) == set(spec["args"]), tool
        assert "service" in spec["args"] and "namespace" not in spec["args"], tool  # W2-D3


def test_the_service_map_decides_and_the_refusal_names_no_service(running_servers, service_map):
    k8s, _ = running_servers["kubernetes"]
    oncall = w2_token("oncall.engineer")  # lm-all-staff, lm-eng-all, lm-platform-oncall
    visible = service_map.visible(frozenset({"lm-all-staff", "lm-eng-all"}))
    assert "claims-api" in visible and "fraud-scoring" not in visible  # fraud-scoring is incident response's
    ok = call(k8s, oncall, "get_pod_status", service="claims-api")
    assert not ok.is_error and json.loads(ok.content[0].text)["ready"] == 2
    for service in ("fraud-scoring", "no-such-service"):
        refused = call(k8s, oncall, "get_pod_status", service=service)
        assert refused.is_error
        text = refused.content[0].text
        assert "fraud-scoring" not in text and "no-such-service" not in text  # the same sentence either way
        assert "among the ones you can ask about" in text
    responder = w2_token("incident.responder")  # holds lm-sec-incident-response
    assert not call(k8s, responder, "get_pod_status", service="fraud-scoring").is_error


def test_a_token_for_w1s_server_or_from_another_client_is_refused(running_servers):
    k8s, log = running_servers["kubernetes"]
    from access import issue  # W1's defaults: W1's audience, scope, and runtime
    from conftest import SECRET
    w1_shaped = issue(SECRET, USERS["oncall.engineer"], "x")
    assert call(k8s, w1_shaped, "get_pod_status", service="claims-api").is_error
    other_client = w2_token("oncall.engineer", client="00000000-0000-0000-0000-000000000001")
    assert call(k8s, other_client, "get_pod_status", service="claims-api").is_error
    reasons = [e["reason"] for e in log_events(log) if e["event"] == "refused"]
    assert any("azp" in r for r in reasons) and any("audience" in r.lower() for r in reasons)


def test_results_are_redacted_before_they_leave_the_server(running_servers):
    oncall = w2_token("oncall.engineer")
    k8s, _ = running_servers["kubernetes"]
    logs, _ = running_servers["logs"]
    tail = json.loads(call(k8s, oncall, "get_pod_logs", service="claims-api", minutes=30, lines=200).content[0].text)
    text = json.dumps(tail)
    assert "eyJhbGciOiJSUzI1NiJ9" not in text and "CLM-2026-118842" not in text and "POL-77120" not in text
    assert "[credential redacted]" in text and "[claim redacted]" in text and "[policy redacted]" in text
    found = json.loads(call(logs, oncall, "search_logs", service="claims-api", minutes=60, contains="bearer",
                            lines=50).content[0].text)
    assert found["returned"] == 1 and "eyJ" not in json.dumps(found)  # matched on the raw line, served redacted


def test_bounds_hold_on_every_read(running_servers):
    oncall = w2_token("oncall.engineer")
    k8s, _ = running_servers["kubernetes"]
    logs, _ = running_servers["logs"]
    metrics, _ = running_servers["metrics"]
    assert call(k8s, oncall, "get_pod_logs", service="claims-api", minutes=60, lines=0).is_error
    too_wide = call(k8s, oncall, "get_recent_events", service="claims-api", minutes=fakes.MAX_WINDOW_MINUTES + 1)
    assert too_wide.is_error and "bad argument: " in too_wide.content[0].text  # the harness's mark, after the SDK's prefix
    assert call(logs, oncall, "search_logs", service="claims-api", minutes=60, contains="", lines=fakes.MAX_LINES + 1).is_error
    assert call(metrics, oncall, "query_metric", service="claims-api", metric="rate(http_requests[5m])", minutes=60).is_error
    tail = json.loads(call(k8s, oncall, "get_pod_logs", service="claims-api", minutes=60, lines=2).content[0].text)
    assert tail["returned"] == 2 and tail["truncated"] is True


def test_the_planted_text_sits_where_an_attacker_can_write(running_servers):
    """The scorer and the chapter name each planted instruction; the fakes must still carry them."""
    oncall, responder = w2_token("oncall.engineer"), w2_token("incident.responder")
    k8s, _ = running_servers["kubernetes"]
    logs, _ = running_servers["logs"]
    metrics, _ = running_servers["metrics"]
    log_text = call(logs, oncall, "search_logs", service="claims-api", minutes=60, contains="SYSTEM NOTE", lines=5)
    assert fakes.PLANTED["log"] in log_text.content[0].text
    events = call(k8s, responder, "get_recent_events", service="fraud-scoring", minutes=60)
    assert fakes.PLANTED["event"] in events.content[0].text
    series = call(metrics, responder, "query_metric", service="fraud-scoring", metric="saturation", minutes=60)
    assert fakes.PLANTED["label"] in series.content[0].text
    alerts = call(k8s, oncall, "get_recent_alerts", service="claims-api", minutes=120)
    assert fakes.PLANTED["alert"] in alerts.content[0].text  # the HighErrorRate rule's annotation


def test_every_call_is_logged_with_the_servers_identity_and_the_engineers(running_servers):
    k8s, log = running_servers["kubernetes"]
    call(k8s, w2_token("oncall.engineer"), "get_pod_status", service="policy-admin")
    calls = [e for e in log_events(log) if e["event"] == "tool_call" and e["args"].get("service") == "policy-admin"]
    assert calls and calls[-1]["identity"] == "larkspur-ops-kubernetes-reader"
    assert calls[-1]["caller"] == USERS["oncall.engineer"] and calls[-1]["ok"] is True
    assert "line" not in json.dumps(calls[-1])  # the log line holds the arguments, never a result's text


def test_the_search_string_is_logged_as_its_hmac_and_an_empty_one_as_the_empty_strings(running_servers):
    # Companion #126: `contains` is text. An empty search matches every line, and its line carries the HMAC of the
    # empty string, the same shape as any other, so the auditor's match has no special case.
    logs, log = running_servers["logs"]
    oncall, key = w2_token("oncall.engineer"), AUDIT_KEY.encode()
    for searched, minutes in (("upstream policy-admin", 7), ("", 8)):
        assert not call(logs, oncall, "search_logs", service="claims-api", minutes=minutes, contains=searched,
                        lines=5).is_error
        [line] = [e for e in log_events(log) if e["event"] == "tool_call" and e["args"].get("minutes") == minutes]
        assert line["args"] == {"service": "claims-api", "minutes": minutes, "lines": 5,
                                "contains": text_hmac(searched, key)}
        assert "upstream" not in json.dumps(line) and "policy-admin" not in json.dumps(line)
    # A refused search is logged the same way: the service the call named, and the HMAC.
    assert call(logs, oncall, "search_logs", service="fraud-scoring", minutes=9, contains="Dana Whitfield", lines=5).is_error
    [refused] = [e for e in log_events(log) if e["event"] == "tool_call" and e["args"].get("minutes") == 9]
    assert refused["refused"] == "service not visible" and refused["args"]["contains"] == text_hmac("Dana Whitfield", key)


def test_a_logs_server_without_the_key_hashes_under_a_random_one_and_warns_once(table_file, tmp_path):
    port, log, stderr = free_port(), tmp_path / "logs.log", tmp_path / "logs.stderr"
    env = {**os.environ, "TOOL_IDENTITY": "larkspur-ops-logs-reader", "W2_TOKEN_SECRET": SECRET,
           "TOOL_LOG_FILE": str(log), "MEMBERSHIP_TABLE": str(table_file)}
    env.pop("AUDIT_HMAC_KEY", None)
    with stderr.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen([sys.executable, str(W2 / "servers" / "logs_server.py"), "--port", str(port)], env=env,
                                stdout=subprocess.DEVNULL, stderr=err, text=True)
        try:
            deadline = time.time() + 60
            while time.time() < deadline and proc.poll() is None:
                with socket.socket() as s:
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        break
                time.sleep(0.2)
            url, oncall = f"http://127.0.0.1:{port}/mcp", w2_token("oncall.engineer")
            for _ in range(2):
                assert not call(url, oncall, "search_logs", service="claims-api", minutes=60, contains="Dana Whitfield",
                                lines=5).is_error
        finally:
            proc.terminate()
            proc.wait(timeout=30)
    warnings = [line for line in stderr.read_text(encoding="utf-8").splitlines() if "AUDIT_HMAC_KEY is not set" in line]
    assert len(warnings) == 1  # once a process, at the first line that needs the key
    hashed = [e["args"]["contains"] for e in log_events(log) if e["event"] == "tool_call"]
    assert len(hashed) == 2 and hashed[0] == hashed[1]  # one key for the process
    assert hashed[0] != text_hmac("Dana Whitfield", AUDIT_KEY.encode()) and "Dana" not in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", list(SERVERS))
def test_each_server_runs_under_its_own_identity(running_servers, name):
    _, log = running_servers[name]
    start = next(e for e in log_events(log) if e["event"] == "server_start")
    assert start["identity"] == f"larkspur-ops-{name}-reader"
    assert len(start["tools"]) == SERVERS[name]


def test_the_catalog_identities_hold_read_actions_only():
    for server, spec in CATALOG["servers"].items():
        for action in spec.get("aws", {}).get("role_actions", []):
            assert vet.is_read_action(action), (server, action)  # one read rule, vet.py's
        assert spec["identity"].startswith("larkspur-ops-") and spec["identity"].endswith("-reader")
    assert set(CATALOG["never"]) == set(MANIFEST["never"])
    assert all(Path(W2 / "servers" / f"{name}_server.py").exists() for name in SERVERS)
