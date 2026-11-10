"""The runtime adapter: the only per-cloud code in the skeleton.

Chapter 5. A managed agent runtime runs a container and expects a small HTTP contract from it.
This file serves three of them from one handler that hands the question to the harness of
part 1 and returns its answer. Everything behind the handler (the harness, the allowlist, the
lock check, the gateway, the MCP server, the trace) is the same on every runtime.

- agentcore: port 8080; GET /ping answers {"status": "Healthy"}; POST /invocations takes
  {"prompt": ...} and answers {"response": ..., "status": "success"}; anything else is a 400. The
  session and request ids go into the audit record, and so does the engineer, read from the Entra
  token the runtime validated and passed through; a session serves only the engineer its ID names
  (see session_is_callers). The workload access token the runtime adds is kept for the request,
  never logged.
- agent-runtime (Google): port 8080; no health route is required; POST /api/reasoning_engine
  takes {"class_method": "query", "input": {"message": ...}} and answers {"output": ...}.
- foundry: port 8088 (or PORT); GET /readiness answers 200; POST /invocations takes
  {"message": ...}, a payload the invocations protocol leaves to the agent, and answers {"output": ...}
  with the session the request ran in; anything else is a 400. The platform's x-agent-user-id goes
  into the audit record, and a sandbox serves only the first one it sees: another is a 403.

Sources, read on 2026-10-29: the AgentCore Runtime HTTP protocol contract, the Gemini Enterprise
Agent Platform runtime contract, and the Foundry hosted agent runtime contract (invocations
protocol; the responses protocol, which implements the OpenAI Responses API, is the one
Microsoft recommends, and its SDK adapter handles history and streaming for you). None of the
streaming variants is served here.

Inside a cloud the container binds 0.0.0.0 on the runtime's port, and the runtime is the only
caller. On a laptop the adapter binds 127.0.0.1 unless told otherwise. On SIGTERM the requests in
flight finish and the process exits normally, so the spans still waiting in the batch are sent.

Run:  TOOL_IDENTITY=larkspur-ops-reader python adapter/runtime_adapter.py --runtime agentcore
      curl -s localhost:8080/invocations -d '{"prompt": "Is claims-api healthy?"}'
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import signal
import sys
from contextvars import ContextVar
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from types import FrameType
from typing import Any, NoReturn, Protocol, TextIO

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

LAB = Path(__file__).resolve().parent.parent
for folder in ("harness", "tracing"):
    if str(LAB / folder) not in sys.path:
        sys.path.insert(0, str(LAB / folder))

import client as harness  # noqa: E402
import trace_setup as tracing  # noqa: E402
from rule_model import rule_based_model  # noqa: E402

PORTS = {"agentcore": 8080, "agent-runtime": 8080, "foundry": 8088}
# Where a Foundry sandbox records the one user it serves: $HOME, the session's persisted storage,
# unless this variable names another folder, as the tests do. Microsoft reserves the FOUNDRY_* and
# AGENT_* names for the platform.
SESSION_STORAGE_ENV = "SESSION_STORAGE_DIR"
SANDBOX_USER_FILE = ".x-agent-user-id"

# AgentCore Runtime's request headers, as its Python SDK (bedrock-agentcore) names them.
AGENTCORE_SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
AGENTCORE_REQUEST_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Request-Id"
AGENTCORE_TOKEN_HEADERS = ("X-Amz-Bedrock-AgentCore-Identity-WAT", "WorkloadAccessToken")
# The workload access token of the request being served: what AgentCore Identity's token vault asks
# for before it hands over a credential. Set for the length of one request; never logged.
WORKLOAD_TOKEN: ContextVar[str | None] = ContextVar("workload_token", default=None)


class Answer(Protocol):
    """(question, the caller's traceparent, fields for the audit record) -> the harness's answer."""

    def __call__(self, question: str, traceparent: str | None,
                 audit: Mapping[str, str] | None = None) -> Awaitable[str]: ...


def foundry_session(request: Request) -> dict[str, str]:
    """The headers Microsoft's hosted-agent libraries put on an invocation's response.

    x-agent-session-id is "Resolved from agent_session_id query param, FOUNDRY_AGENT_SESSION_ID env
    var, or generated UUID" (Azure AI Agent Server Invocations client library for Python,
    learn.microsoft.com, 2026-09-29). A caller that let Foundry create the session sends it back as
    ?agent_session_id= to reach the same sandbox; a generated id would name no session, so there is
    none here. x-agent-invocation-id is echoed when the platform sends one.
    """
    session = request.query_params.get("agent_session_id") or os.environ.get("FOUNDRY_AGENT_SESSION_ID")
    pairs = (("x-agent-session-id", session), ("x-agent-invocation-id", request.headers.get("x-agent-invocation-id")))
    return {name: value for name, value in pairs if value and value.isprintable()}


def sandbox_admits(user: str | None) -> bool:
    """Whether this sandbox may serve `user`, the request's x-agent-user-id: only the first one it saw.

    "Within delegation, the platform doesn't fence one delegated end user from another", and "if you
    route two users to the same session, they can see each other's data" (Isolate hosted agent
    sessions per user, learn.microsoft.com, 2026-10-13). Chapter 4 never reuses a session across
    people, so the first user is written under $HOME, which the platform keeps for the session's
    life, and any other is refused and logged. Without the header nothing is pinned or refused:
    Microsoft doesn't guarantee the platform's headers when the container runs locally. The pin
    catches a caller that sends two people to one session. It can't stop someone who can already
    upload into the session, since uploads write beneath $HOME too.
    """
    if not user:
        return True
    pin = Path(os.environ.get(SESSION_STORAGE_ENV) or Path.home()) / SANDBOX_USER_FILE
    try:
        with pin.open("x", encoding="utf-8") as first:  # created by the first request only
            first.write(user)
        return True
    except FileExistsError:
        pinned = pin.read_text(encoding="utf-8")
    if pinned == user:
        return True
    harness.json_line(sys.stderr, event="refused", reason="another user's session", foundry_user_id=user,
                      session_user_id=pinned)
    return False


def agentcore_caller(request: Request) -> str | None:
    """The engineer in the request's bearer token: its `oid` claim (Entra's object id), else `sub`.

    The signature isn't checked here, because AgentCore checked it: with a JWT authorizer the
    runtime validates the token's signature, issuer, audience and calling app before the request
    reaches the container, and passes the header through only when it is on the runtime's
    allowlist. The container's only caller is the runtime. Without a well-formed token there is no
    engineer, and no session to check.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    parts = token.split(".")
    if scheme.lower() != "bearer" or len(parts) != 3:
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (binascii.Error, ValueError):
        return None
    user = claims.get("oid") or claims.get("sub") if isinstance(claims, dict) else None
    return user if isinstance(user, str) and user.isprintable() else None


def session_suffix(user: str) -> str:
    """How every AgentCore session ID the bot opens for `user` ends: a hash of their object id."""
    return "-" + hashlib.sha256(user.encode("utf-8")).hexdigest()[:32]


def session_is_callers(session_id: str | None, user: str | None) -> bool:
    """Whether the AgentCore session's ID names the engineer in this request's token.

    AgentCore "does not enforce session-to-user mappings" (Use isolated sessions for agents,
    AgentCore developer guide, read 2026-10-29), and a stopped session resumes on a new microVM,
    so nothing the container writes can hold the mapping. The bot builds each session ID from the
    conversation and session_suffix(engineer), and the check runs on every request, whichever
    microVM serves it. Without a token (a local run) there is no engineer to check.
    """
    if not user:
        return True
    if session_id and session_id.endswith(session_suffix(user)):
        return True
    harness.json_line(sys.stderr, event="refused", reason="another engineer's session",
                      agentcore_user_id=user, agentcore_session_id=session_id)
    return False


async def body_text(request: Request, field: str) -> str | None:
    """The JSON body's `field` when it is a string with something in it; None for anything else."""
    try:
        body = await request.json()
    except ValueError:  # not JSON
        return None
    text = body.get(field) if isinstance(body, dict) else None
    return text if isinstance(text, str) and text.strip() else None


def agentcore_context(request: Request, user: str | None) -> tuple[dict[str, str], str | None]:
    """(the audit fields, the workload access token) from AgentCore Runtime's request headers."""
    pairs = (("agentcore_session_id", request.headers.get(AGENTCORE_SESSION_HEADER)),
             ("agentcore_request_id", request.headers.get(AGENTCORE_REQUEST_HEADER)),
             ("agentcore_user_id", user))
    token = next((request.headers[name] for name in AGENTCORE_TOKEN_HEADERS if request.headers.get(name)), None)
    return {name: value for name, value in pairs if value and value.isprintable()}, token


def error(message: str, status: int, **kwargs: Any) -> JSONResponse:
    """A refusal in the one shape every runtime gets."""
    return JSONResponse({"error": message}, status_code=status, **kwargs)


def build_app(runtime: str, answer: Answer) -> Starlette:
    """One runtime's routes, all ending in the same `answer` call."""

    async def agentcore_invoke(request: Request) -> JSONResponse:
        user = agentcore_caller(request)
        session = request.headers.get(AGENTCORE_SESSION_HEADER)
        if not session_is_callers(session, user):  # one engineer
            return error("this session belongs to another user", 403)
        prompt = await body_text(request, "prompt")
        if prompt is None:
            return error('expected {"prompt": "..."}', 400)
        audit, token = agentcore_context(request, user)
        trace = request.headers.get("traceparent")
        reset = WORKLOAD_TOKEN.set(token)  # for this request only
        try:
            text = await answer(prompt, trace, audit or None)
        finally:
            WORKLOAD_TOKEN.reset(reset)
        return JSONResponse({"response": text, "status": "success"})

    async def google_query(request: Request) -> JSONResponse:
        body = await request.json()
        if body.get("class_method") != "query":
            return error(f"method {body.get('class_method')!r} not found", 400)
        message = (body.get("input") or {}).get("message", "")
        return JSONResponse({"output": await answer(message, request.headers.get("traceparent"))})

    async def foundry_invoke(request: Request) -> JSONResponse:
        headers = foundry_session(request)
        user = request.headers.get("x-agent-user-id")  # Foundry's identifier for the caller (protocol 2.0.0)
        if not sandbox_admits(user):  # one engineer per sandbox
            return error("this session belongs to another user", 403, headers=headers)
        message = await body_text(request, "message")
        if message is None:
            return error('expected {"message": "..."}', 400, headers=headers)
        text = await answer(message, request.headers.get("traceparent"), {"foundry_user_id": user} if user else None)
        return JSONResponse({"output": text}, headers=headers)

    async def healthy(request: Request) -> JSONResponse:
        # AgentCore wants a status; "HealthyBusy" would keep the session alive for background work.
        return JSONResponse({"status": "Healthy"})

    post, get = ["POST"], ["GET"]
    routes = {
        "agentcore": [
            Route("/invocations", agentcore_invoke, methods=post),
            Route("/ping", healthy, methods=get)],
        "agent-runtime": [
            Route("/api/reasoning_engine", google_query, methods=post)],
        "foundry": [
            Route("/invocations", foundry_invoke, methods=post),
            Route("/readiness", healthy, methods=get)],
    }[runtime]
    return Starlette(routes=routes)


def harness_answer(server_factory: Callable[[], Any], model: Callable = rule_based_model,
                   log: TextIO = sys.stderr) -> Answer:
    """The handler every runtime shares: run the harness on the question, in the caller's trace.

    The harness's log lines (the audit record) go to `log`, under the caller's trace id when a
    `traceparent` came with the request, so the runtime's logs, the spans and the MCP server's log
    all join on one id. `audit` adds the runtime's fields to every line, such as Foundry's user id.
    """

    async def answer(question: str, traceparent: str | None, audit: Mapping[str, str] | None = None) -> str:
        with tracing.start_span("runtime_adapter", traceparent=traceparent):
            return await harness.run_harness(server_factory(), question, model=model, log=log,
                                             trace_id=tracing.current_trace_id(), audit=audit)

    return answer


def exit_cleanly(signum: int, frame: FrameType | None) -> NoReturn:
    """A SIGTERM handler that ends the process normally, so atexit still flushes the batched spans.

    uvicorn finishes the requests in flight and then raises the signal again. With Python's
    default action the process would die there, before trace_setup's atexit handler runs.
    """
    raise SystemExit(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runtime", choices=sorted(PORTS), required=True)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside the runtime's container")
    parser.add_argument("--port", type=int, help="default: the runtime's own (8080 or 8088; Foundry reads PORT)")
    args = parser.parse_args(argv)
    port = args.port or int(os.environ.get("PORT", 0)) or PORTS[args.runtime]
    mcp_url = os.environ.get("MCP_URL")  # a running MCP server; a stdio subprocess when unset
    factory = (lambda: mcp_url) if mcp_url else harness.stdio_server
    signal.signal(signal.SIGTERM, exit_cleanly)
    setup = tracing.configure("runtime-adapter")
    print(f"runtime adapter for {args.runtime} on {args.host}:{port}; spans to {setup.destination}",
          file=sys.stderr)
    uvicorn.run(build_app(args.runtime, harness_answer(factory)), host=args.host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
