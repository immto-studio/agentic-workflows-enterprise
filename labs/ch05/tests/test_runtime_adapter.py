"""The runtime adapter: three managed-runtime contracts, one handler, the same answer on each.

Each contract is checked against the shapes the vendors document (see the adapter's docstring):
the health route, the request body, the response body, and that the routes of one runtime are
not served by another. The handler behind them is the part 1 harness with an in-process server.
Foundry's route also returns the session a request ran in, records the platform's user id and
serves one user per sandbox, and the process stops cleanly on SIGTERM, as Foundry's contract asks
of every hosted agent. AgentCore's route records the session, the request and the engineer from
the validated token, serves only the engineer the session's ID names, and keeps the workload
access token for the request it came with.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "adapter"))

import runtime_adapter as adapter  # noqa: E402
import server as mcp_server  # noqa: E402
import trace_setup as tracing  # noqa: E402
from gateway_support import free_port  # noqa: E402
from sigterm_support import serve_then_sigterm  # noqa: E402

QUESTION = "Is claims-api healthy?"
ANSWER = "claims-api has 2 of 3 pods ready. Not ready: claims-api-7d9f8b6c4-t8w2c (CrashLoopBackOff, 7 restarts)."


def app_for(runtime: str, log: io.StringIO | None = None) -> TestClient:
    answer = adapter.harness_answer(lambda: mcp_server.build_server("larkspur-ops-reader", io.StringIO(), "inproc"),
                                    log=log or io.StringIO())
    return TestClient(adapter.build_app(runtime, answer))


def test_agentcore_contract() -> None:
    with app_for("agentcore") as http:
        assert http.get("/ping").json() == {"status": "Healthy"}
        r = http.post("/invocations", json={"prompt": QUESTION})
        assert r.status_code == 200 and r.json() == {"response": ANSWER, "status": "success"}
        assert http.post("/invocations", json={"message": QUESTION}).status_code == 400
        assert http.get("/readiness").status_code == 404


def test_google_agent_runtime_contract() -> None:
    with app_for("agent-runtime") as http:
        r = http.post("/api/reasoning_engine", json={"class_method": "query", "input": {"message": QUESTION}})
        assert r.status_code == 200 and r.json() == {"output": ANSWER}
        bad = http.post("/api/reasoning_engine", json={"class_method": "delete_everything", "input": {}})
        assert bad.status_code == 400
        assert http.post("/invocations", json={"prompt": QUESTION}).status_code == 404


def test_foundry_invocations_contract() -> None:
    with app_for("foundry") as http:
        assert http.get("/readiness").status_code == 200
        r = http.post("/invocations", json={"message": QUESTION})
        assert r.status_code == 200 and r.json() == {"output": ANSWER}
        assert http.get("/ping").status_code == 404


def test_ports_are_the_runtimes_own() -> None:
    assert adapter.PORTS == {"agentcore": 8080, "agent-runtime": 8080, "foundry": 8088}


def test_the_adapter_is_a_few_dozen_lines() -> None:
    # The chapter counts the per-runtime code at 102 lines, from foundry_session to build_app. Hold the
    # largest piece to its size: build_app stays under fifty lines of code, comments and blank lines
    # excluded.
    source = Path(adapter.__file__).read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(source) if line.startswith("def build_app("))
    end = next(i for i, line in enumerate(source) if line.startswith("def harness_answer("))
    code = [line for line in source[start:end] if line.strip() and not line.strip().startswith(("#", '"""'))]
    assert len(code) < 50, len(code)


@pytest.mark.parametrize("runtime, path, body", [
    ("agentcore", "/invocations", {"prompt": QUESTION}),
    ("foundry", "/invocations", {"message": QUESTION}),
])
def test_a_callers_traceparent_parents_the_run(runtime: str, path: str, body: dict, trace_file: Path) -> None:
    trace_id, parent = tracing.new_trace_id(), "b7ad6b7169203331"
    log = io.StringIO()
    with app_for(runtime, log) as http:
        http.post(path, json=body, headers={"traceparent": f"00-{trace_id}-{parent}-01"})
    spans = [s for s in tracing.read_spans(trace_file) if s["trace_id"] == trace_id]
    entry = [s for s in spans if s["name"] == "runtime_adapter"][0]
    run = [s for s in spans if s["name"] == "invoke_agent harness"][0]
    assert entry["parent_span_id"] == parent and run["parent_span_id"] == entry["span_id"]
    # The audit log is kept, under the caller's trace id.
    calls = [json.loads(line) for line in log.getvalue().splitlines() if '"tool_call"' in line]
    assert calls and all(c["trace_id"] == trace_id for c in calls)


# --- Foundry's route, against Microsoft's hosted-agent contract -------------------------------

@pytest.mark.parametrize("body", [b"not json", b"", b"[]", b'"Is claims-api healthy?"', b"{}", b'{"message": ""}',
                                  b'{"message": 3}', b'{"prompt": "Is claims-api healthy?"}'])
def test_foundry_answers_400_to_a_body_without_a_message(body: bytes) -> None:
    log = io.StringIO()
    with app_for("foundry", log) as http:
        r = http.post("/invocations", content=body)
    assert r.status_code == 400 and r.json() == {"error": "expected {\"message\": \"...\"}"}
    assert log.getvalue() == ""  # the harness never ran


def test_foundry_returns_the_session_the_request_ran_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOUNDRY_AGENT_SESSION_ID", "session-the-platform-chose")
    with app_for("foundry") as http:
        r = http.post("/invocations", json={"message": QUESTION}, headers={"x-agent-invocation-id": "invocation-42"})
        assert r.status_code == 200 and r.json() == {"output": ANSWER}
        assert r.headers["x-agent-session-id"] == "session-the-platform-chose"
        assert r.headers["x-agent-invocation-id"] == "invocation-42"
        # The query parameter the platform routes by comes first, as in Microsoft's libraries.
        r = http.post("/invocations?agent_session_id=session-in-the-query", json={"message": QUESTION})
        assert r.headers["x-agent-session-id"] == "session-in-the-query"
        assert "x-agent-invocation-id" not in r.headers  # echoed only when one came in
        assert http.post("/invocations", content=b"{}").headers["x-agent-session-id"] == "session-the-platform-chose"
    with app_for("agentcore") as http:  # another runtime's route says nothing about Foundry's sessions
        assert "x-agent-session-id" not in http.post("/invocations", json={"prompt": QUESTION}).headers
    monkeypatch.delenv("FOUNDRY_AGENT_SESSION_ID")
    with app_for("foundry") as http:  # a local run, with no session to name
        assert "x-agent-session-id" not in http.post("/invocations", json={"message": QUESTION}).headers


@pytest.mark.parametrize("runtime, path, body", [
    ("foundry", "/invocations", {"message": QUESTION}),
    ("agentcore", "/invocations", {"prompt": QUESTION}),
    ("agent-runtime", "/api/reasoning_engine", {"class_method": "query", "input": {"message": QUESTION}}),
])
def test_foundrys_user_id_is_in_every_audit_line_on_foundry_only(runtime: str, path: str, body: dict,
                                                                   session_storage: Path) -> None:
    log = io.StringIO()
    with app_for(runtime, log) as http:
        assert http.post(path, json=body, headers={"x-agent-user-id": "user-7f3a"}).status_code == 200
        http.post(path, json=body)  # no header, as when the container runs locally
    lines = [json.loads(line) for line in log.getvalue().splitlines()]
    assert [line["event"] for line in lines] == ["tools_verified", "tool_call", "answer"] * 2
    if runtime == "foundry":
        assert [line.get("foundry_user_id") for line in lines] == ["user-7f3a"] * 3 + [None] * 3
        assert all(list(line)[3] == "foundry_user_id" for line in lines[:3])  # right after the trace id
    else:
        assert not [line for line in lines if "foundry_user_id" in line]
    # Only Foundry's route pins its sandbox to the user; the header means nothing to the others.
    assert (session_storage / adapter.SANDBOX_USER_FILE).exists() == (runtime == "foundry")


# --- one engineer per sandbox -----------------------------------------------------------------

def ask(http: TestClient, user: str | None, **request: Any) -> Any:
    """POST /invocations as `user` (no x-agent-user-id when None), with the question unless told otherwise."""
    request = request or {"json": {"message": QUESTION}}
    return http.post("/invocations", headers={"x-agent-user-id": user} if user else {}, **request)


def test_a_foundry_sandbox_serves_only_the_first_user_it_sees(session_storage: Path, monkeypatch: pytest.MonkeyPatch,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    assert os.environ[adapter.SESSION_STORAGE_ENV] == str(session_storage)  # never the real $HOME
    monkeypatch.setenv("FOUNDRY_AGENT_SESSION_ID", "session-of-user-7f3a")
    log = io.StringIO()
    with app_for("foundry", log) as http:
        first = ask(http, "user-7f3a")
        other = ask(http, "user-91c2")
        malformed = ask(http, "user-91c2", content=b"{}")  # refused before its body is read
        again = ask(http, "user-7f3a")
    assert first.status_code == again.status_code == 200 and again.json() == {"output": ANSWER}
    for refused in (other, malformed):
        assert refused.status_code == 403 and refused.json() == {"error": "this session belongs to another user"}
        assert refused.headers["x-agent-session-id"] == "session-of-user-7f3a"
    assert (session_storage / adapter.SANDBOX_USER_FILE).read_text(encoding="utf-8") == "user-7f3a"
    answers = [line for line in map(json.loads, log.getvalue().splitlines()) if line["event"] == "answer"]
    assert [line["foundry_user_id"] for line in answers] == ["user-7f3a"] * 2  # the harness never ran for user-91c2
    refusals = [json.loads(line) for line in capsys.readouterr().err.splitlines() if '"refused"' in line]
    assert [(r["foundry_user_id"], r["session_user_id"]) for r in refusals] == [("user-91c2", "user-7f3a")] * 2


def test_the_sandboxs_user_outlasts_a_restart(session_storage: Path) -> None:
    """$HOME is kept for the session's life, so a new process on the same storage keeps the first user."""
    (session_storage / adapter.SANDBOX_USER_FILE).write_text("user-7f3a", encoding="utf-8")
    with app_for("foundry") as http:  # the process after the platform released and restored the sandbox
        assert ask(http, "user-91c2").status_code == 403
        assert ask(http, "user-7f3a").status_code == 200


def test_without_the_header_nothing_is_pinned_or_refused(session_storage: Path) -> None:
    """Microsoft doesn't guarantee the platform's headers when the container runs locally."""
    pin = session_storage / adapter.SANDBOX_USER_FILE
    with app_for("foundry") as http:
        assert ask(http, None).status_code == 200
        assert not pin.exists()
        assert ask(http, "user-7f3a").status_code == 200  # the first user who arrives still pins the sandbox
        assert ask(http, None).status_code == 200
        assert ask(http, "user-91c2").status_code == 403
    assert pin.read_text(encoding="utf-8") == "user-7f3a"


# --- AgentCore's route, against the AgentCore Runtime HTTP contract (chapter 6) ---------------------

def bearer(**claims: Any) -> dict[str, str]:
    """An Authorization header carrying `claims`. Unsigned: AgentCore checks the signature before the container."""

    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return {"Authorization": f"Bearer {part({'alg': 'RS256', 'typ': 'JWT'})}.{part(claims)}.c2lnbmF0dXJl"}


ENGINEER = "5d1f0c2e-sam-okafor"
# As the bot builds it: the conversation, then a hash of the engineer. AgentCore asks for 33 characters or more.
SESSION = "incident-2026-10-29-claims-api" + adapter.session_suffix(ENGINEER)


@pytest.mark.parametrize("body", [b"not json", b"", b"[]", b'"Is claims-api healthy?"', b"{}", b'{"prompt": ""}',
                                  b'{"prompt": 3}', b'{"message": "Is claims-api healthy?"}'])
def test_agentcore_answers_400_to_a_body_without_a_prompt(body: bytes) -> None:
    log = io.StringIO()
    with app_for("agentcore", log) as http:
        r = http.post("/invocations", content=body)
    assert r.status_code == 400 and r.json() == {"error": "expected {\"prompt\": \"...\"}"}
    assert log.getvalue() == ""  # the harness never ran


def test_agentcore_puts_the_session_request_and_engineer_on_every_audit_line(session_storage: Path) -> None:
    log = io.StringIO()
    headers = {**bearer(oid=ENGINEER, sub="pairwise-subject"), "WorkloadAccessToken": "wat-never-logged",
               adapter.AGENTCORE_SESSION_HEADER: SESSION, adapter.AGENTCORE_REQUEST_HEADER: "request-17"}
    with app_for("agentcore", log) as http:
        r = http.post("/invocations", json={"prompt": QUESTION}, headers=headers)
    assert r.status_code == 200 and r.json() == {"response": ANSWER, "status": "success"}
    lines = [json.loads(line) for line in log.getvalue().splitlines()]
    assert [line["event"] for line in lines] == ["tools_verified", "tool_call", "answer"]
    for line in lines:
        assert (line["agentcore_session_id"], line["agentcore_request_id"], line["agentcore_user_id"]) == (
            SESSION, "request-17", ENGINEER)  # Entra's object id, not the pairwise sub
    assert "wat-never-logged" not in log.getvalue()


def test_an_agentcore_session_serves_only_the_engineer_its_id_names(session_storage: Path,
                                                                   capsys: pytest.CaptureFixture[str]) -> None:
    """AgentCore "does not enforce session-to-user mappings", so the harness checks every request.

    The check needs no file: a stopped session resumes on a new microVM, where a file would be gone.
    """
    log = io.StringIO()
    a_session = "incident-chat-0001" + adapter.session_suffix("engineer-a")
    b_session = "incident-chat-0001" + adapter.session_suffix("engineer-b")

    def ask(session: str | None, oid: str | None, **body: Any) -> Any:
        headers = {**(bearer(oid=oid) if oid else {}), **({adapter.AGENTCORE_SESSION_HEADER: session} if session else {})}
        return http.post("/invocations", headers=headers, **(body or {"json": {"prompt": QUESTION}}))

    with app_for("agentcore", log) as http:
        mine, again = ask(a_session, "engineer-a"), ask(a_session, "engineer-a")
        theirs = ask(b_session, "engineer-b")  # same conversation, another engineer: another session
        borrowed = ask(a_session, "engineer-b")
        malformed = ask(a_session, "engineer-b", content=b"{}")
        unnamed = ask(None, "engineer-a")  # an ID AgentCore made up names nobody
        local = ask(None, None)  # no token: a local run
    assert mine.status_code == again.status_code == theirs.status_code == local.status_code == 200
    for refused in (borrowed, malformed, unnamed):  # refused before the body is read
        assert refused.status_code == 403 and refused.json() == {"error": "this session belongs to another user"}
    assert not (session_storage / adapter.SANDBOX_USER_FILE).exists()  # nothing written
    answers = [line for line in map(json.loads, log.getvalue().splitlines()) if line["event"] == "answer"]
    assert [line.get("agentcore_user_id") for line in answers] == ["engineer-a", "engineer-a", "engineer-b", None]
    refusals = [json.loads(line) for line in capsys.readouterr().err.splitlines() if '"refused"' in line]
    assert [(r["agentcore_user_id"], r["agentcore_session_id"]) for r in refusals] == [
        ("engineer-b", a_session), ("engineer-b", a_session), ("engineer-a", None)]


def test_a_session_id_with_its_suffix_is_long_enough_for_agentcore() -> None:
    suffix = adapter.session_suffix("5d1f0c2e-1b2a-4c3d-9e8f-0a1b2c3d4e5f")
    assert len(suffix) == 33 and suffix[0] == "-" and int(suffix[1:], 16) >= 0
    assert adapter.session_suffix("engineer-a") != adapter.session_suffix("engineer-b")


@pytest.mark.parametrize("authorization, engineer", [
    (bearer(oid="oid-1", sub="sub-1")["Authorization"], "oid-1"),
    (bearer(sub="sub-1")["Authorization"], "sub-1"),
    (bearer(name="no identifier")["Authorization"], None),
    (bearer(oid="tab\there")["Authorization"], None),
    ("Basic dXNlcjpwYXNz", None),
    ("Bearer only.two", None),
    ("Bearer a.!!!.c", None),
    (f"Bearer a.{base64.urlsafe_b64encode(b'not json').decode()}.c", None),
    (f"Bearer a.{base64.urlsafe_b64encode(b'[1, 2]').decode()}.c", None),
    ("", None),
])
def test_the_engineer_is_the_tokens_oid_then_its_sub(authorization: str, engineer: str | None) -> None:
    request = type("Request", (), {"headers": {"authorization": authorization} if authorization else {}})()
    assert adapter.agentcore_caller(request) == engineer


def test_the_workload_token_lasts_one_request() -> None:
    seen: list[str | None] = []

    async def answer(question: str, traceparent: str | None, audit: Any = None) -> str:
        seen.append(adapter.WORKLOAD_TOKEN.get())
        return "ok"

    with TestClient(adapter.build_app("agentcore", answer)) as http:
        http.post("/invocations", json={"prompt": QUESTION},
                  headers={"X-Amz-Bedrock-AgentCore-Identity-WAT": "wat-new", "WorkloadAccessToken": "wat-old"})
        http.post("/invocations", json={"prompt": QUESTION}, headers={"WorkloadAccessToken": "wat-old"})
        http.post("/invocations", json={"prompt": QUESTION})
    assert seen == ["wat-new", "wat-old", None]  # the SDK's newer header first; nothing carried over
    assert adapter.WORKLOAD_TOKEN.get() is None


def test_sigterm_ends_the_process_cleanly_and_its_spans_still_leave() -> None:
    port = free_port()
    env = {k: v for k, v in os.environ.items() if k not in ("PORT", "MCP_URL")}
    result, received = serve_then_sigterm(Path(adapter.__file__), ["--runtime", "foundry", "--port", str(port)],
                                          f"http://127.0.0.1:{port}/readiness", env)
    assert result.returncode == 0, result.stderr
    assert "probe 200" in result.stdout  # Foundry's health probe, answered before the signal
    assert "/v1/traces" in received  # the span queued before SIGTERM was flushed on the way out
    assert "Traceback" not in result.stderr
