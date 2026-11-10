"""analyst: an A2A agent that summarizes the recent alerts for one Larkspur service.

Chapter 5, part 2. The analyst serves an Agent Card and one skill. A task of the form
"summarize the alerts for <service>" makes it run the part 1 harness (the chapter 1 loop with
the rule-based model) against the part 1 MCP server, which is where `get_recent_alerts` lives.
The result comes back as one artifact: the summary sentence plus the structured alert list.

Four rules, each checked before any work is done:

1. Identity. The process refuses to start unless `AGENT_IDENTITY` is set. The MCP server it
   launches runs under its own `TOOL_IDENTITY`; the two are different principals on purpose.
2. Authentication. The card declares a bearer scheme; every request except the card needs a
   token of a known caller (`ANALYST_CALLER_TOKENS`), or it gets 401 before the SDK sees it. The
   caller is the token's subject. A request whose `agent_identity` metadata names someone else
   is rejected, and the subject, not the claim, is what the logs and the span record.
3. Trace id. A task whose request metadata carries no `trace_id` is rejected (A2A state
   REJECTED, with a message saying why). Work nobody can trace is work nobody can audit.
4. Allowlist. The harness is handed exactly one tool, `get_recent_alerts`. The server also
   serves `get_pod_status`; the analyst cannot call it, whatever the task text says.

Run:  AGENT_IDENTITY=larkspur-analyst TOOL_IDENTITY=larkspur-ops-reader \
      ANALYST_CALLER_TOKENS=larkspur-scribe=<a long random string> python analyst.py
Binds 127.0.0.1 only. The A2A SDK's own spans are off by default here (see the README).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, TextIO

# The A2A SDK decides at import time whether to trace its own internals; keep the lab's traces
# to the spans the README describes unless the reader asks for more.
os.environ.setdefault("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "false")

import uvicorn  # noqa: E402
from a2a.server.agent_execution import AgentExecutor, RequestContext  # noqa: E402
from a2a.server.events import EventQueue  # noqa: E402
from a2a.server.request_handlers import DefaultRequestHandler  # noqa: E402
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes  # noqa: E402
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater  # noqa: E402
from a2a.types import (  # noqa: E402
    AgentCapabilities, AgentCard, AgentInterface, AgentProvider, AgentSkill, HTTPAuthSecurityScheme,
    Part, SecurityRequirement, SecurityScheme, StringList,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH  # noqa: E402
from a2a.helpers import new_data_part, new_task_from_user_message, new_text_part  # noqa: E402
from opentelemetry.trace import SpanKind  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.authentication import AuthCredentials, SimpleUser  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.types import ASGIApp, Receive, Scope, Send  # noqa: E402

from agent_common import (  # noqa: E402
    BEARER_SCHEME, CALLER_IDENTITY_KEY, CALLER_TOKENS_ENV, TRACE_ID_KEY, TRACEPARENT_KEY, json_line,
    open_log, parse_caller_tokens, refuse, require_agent_identity, subject_for,
)
import client as harness  # noqa: E402  (the part 1 harness)
import trace_setup as tracing  # noqa: E402
from rule_model import parse_question, rule_based_model  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8766
AGENT_NAME = "analyst"
AGENT_VERSION = "0.1.0"
AGENT_DESCRIPTION = ("Summarizes the alerts that fired for one Larkspur Mutual service, read from the "
                     "production namespace through a read-only MCP server.")
SKILL_ID = "summarize-alerts"
ARTIFACT_NAME = "alert-summary"
# The only tool the analyst may run. The server offers two.
ALLOWED: dict[str, set[str]] = {"get_recent_alerts": {"service", "minutes"}}


def agent_card(url: str) -> AgentCard:
    """The card the scribe discovers at /.well-known/agent-card.json."""
    return AgentCard(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        version=AGENT_VERSION,
        provider=AgentProvider(organization="Larkspur Mutual (fictional)",
                               url="https://example.invalid/larkspur"),
        supported_interfaces=[AgentInterface(
            url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True),
        security_schemes={BEARER_SCHEME: SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                scheme="bearer",
                description="A token issued to the calling agent's "
                            "identity. The lab keeps a static token per "
                            "caller; production uses a short-lived JWT "
                            "from the identity provider."))},
        security_requirements=[SecurityRequirement(
            schemes={BEARER_SCHEME: StringList(list=[])})],
        default_input_modes=["text/plain"],
        default_output_modes=["application/json", "text/plain"],
        skills=[AgentSkill(
            id=SKILL_ID,
            name="Summarize alerts",
            description="Given a service name, return the alerts of the "
                        "last hour (or a stated window) with a "
                        "one-sentence summary. Read-only.",
            tags=["operations", "alerts", "read-only"],
            examples=["Summarize the alerts for claims-api",
                      "Summarize the alerts for document-ocr in the last "
                      "30 minutes"],
        )],
    )


class RequireBearer:
    """ASGI middleware: everything except the Agent Card needs the bearer token of a known caller.

    A request without one gets 401 and never reaches the A2A SDK. With one, the token's subject
    becomes the Starlette user, which the SDK hands to the executor as the call context's user.
    """

    def __init__(self, app: ASGIApp, tokens: dict[str, str], log: TextIO) -> None:
        self.app, self.tokens, self.log = app, tokens, log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == AGENT_CARD_WELL_KNOWN_PATH:
            await self.app(scope, receive, send)  # the card is public; it is how callers find the scheme
            return
        scheme, _, token = Headers(scope=scope).get("authorization", "").partition(" ")
        subject = subject_for(token.strip(), self.tokens) if scheme.lower() == "bearer" and token else None
        if subject is None:
            json_line(self.log, event="unauthenticated", path=scope["path"],
                      reason="no bearer token" if not token else "unknown token")
            response = JSONResponse({"error": "a bearer token of a known caller is required"}, status_code=401,
                                    headers={"WWW-Authenticate": 'Bearer realm="larkspur-a2a"'})
            await response(scope, receive, send)
            return
        scope["user"] = SimpleUser(subject)
        scope["auth"] = AuthCredentials(["a2a:invoke"])
        await self.app(scope, receive, send)


class AnalystExecutor(AgentExecutor):
    def __init__(self, identity: str, mcp_server: Any, log: TextIO) -> None:
        self.identity = identity
        self.mcp_server = mcp_server  # StdioServerParameters, or the URL of a running server
        self.log = log

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        task = context.current_task
        if task is None:  # a new task: the Task object must exist before any status update
            task = new_task_from_user_message(message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        meta = context.metadata  # SendMessageRequest.metadata as a plain dict
        user = context.call_context.user
        caller = user.user_name if user.is_authenticated else None  # the token's subject
        claimed = meta.get(CALLER_IDENTITY_KEY)
        headers = context.call_context.state.get("headers", {})
        traceparent, trace_source = ((headers["traceparent"], "header") if headers.get("traceparent")
                                     else (meta.get(TRACEPARENT_KEY), "metadata"))
        text = context.get_user_input()

        if caller is None or (claimed and claimed != caller):
            reason = (f"the request claims to come from {claimed!r} but its token belongs to {caller!r}"
                      if caller else "the request is not authenticated")
            json_line(self.log, event="task_rejected", task_id=task.id, identity=self.identity,
                      caller=caller, claimed=claimed, reason=reason)
            await updater.reject(updater.new_agent_message([new_text_part(f"refused: {reason}")]))
            return

        trace_id = meta.get(TRACE_ID_KEY)
        if not isinstance(trace_id, str) or not trace_id.strip():
            reason = f"request metadata carries no {TRACE_ID_KEY}; the analyst does not run untraced work"
            json_line(self.log, event="task_rejected", task_id=task.id, identity=self.identity,
                      caller=caller, reason=reason)
            await updater.reject(updater.new_agent_message([new_text_part(f"refused: {reason}")]))
            return

        attributes = {
            tracing.GEN_AI_OPERATION_NAME: tracing.OP_INVOKE_AGENT,
            tracing.GEN_AI_AGENT_NAME: AGENT_NAME,
            tracing.GEN_AI_AGENT_DESCRIPTION: AGENT_DESCRIPTION,
            tracing.GEN_AI_CONVERSATION_ID: task.context_id,
            tracing.A2A_TASK_ID: task.id,
            tracing.LARKSPUR_COMPONENT: "analyst",
            tracing.LARKSPUR_IDENTITY: self.identity,
            tracing.LARKSPUR_CALLER_IDENTITY: caller,
            tracing.LARKSPUR_TRACE_ID: trace_id,
        }
        with tracing.start_span(f"{tracing.OP_INVOKE_AGENT} {AGENT_NAME}", kind=SpanKind.SERVER,
                                traceparent=traceparent, trace_id=trace_id,
                                attributes=attributes) as span:
            json_line(self.log, event="task_received", task_id=task.id, trace_id=trace_id,
                      identity=self.identity, caller=caller, trace_source=trace_source, text=text)
            intent = parse_question(text)
            if intent.kind != "alerts" or not intent.service:
                reason = ("the analyst only summarizes alerts for one named service, "
                          "for example 'Summarize the alerts for claims-api'")
                span.set_attribute(tracing.LARKSPUR_REFUSED, True)
                json_line(self.log, event="task_rejected", task_id=task.id, trace_id=trace_id, reason=reason)
                await updater.reject(updater.new_agent_message([new_text_part(f"refused: {reason}")]))
                return

            await updater.start_work(updater.new_agent_message(
                [new_text_part(f"fetching alerts for {intent.service} over {intent.minutes} minutes")]))

            captured: dict[str, Any] = {}

            def model(messages: list[dict]) -> dict:
                # The rule-based model, with the last tool result kept for the artifact.
                if messages[-1]["role"] == "tool":
                    captured["result"] = json.loads(messages[-1]["content"])
                return rule_based_model(messages)

            model.__name__ = rule_based_model.__name__
            answer = await harness.run_harness(self.mcp_server, text, model=model, trace_id=trace_id,
                                               log=self.log, allowed=ALLOWED)
            result = captured.get("result")
            if result is None or "error" in result or answer.startswith("Refused:"):
                span.set_attribute(tracing.LARKSPUR_REFUSED, True)
                json_line(self.log, event="task_failed", task_id=task.id, trace_id=trace_id, answer=answer)
                await updater.failed(updater.new_agent_message([new_text_part(answer)]))
                return

            data = {
                "service": result["service"],
                "window_minutes": result["window_minutes"],
                "count": result["count"],
                "by_severity": {sev: sum(1 for a in result["alerts"] if a["severity"] == sev)
                                for sev in ("critical", "warning", "info")},
                "alerts": result["alerts"],
                "summary": answer,
                "trace_id": trace_id,
                "produced_by": self.identity,
                "requested_by": caller,
            }
            parts: list[Part] = [new_text_part(answer, media_type="text/plain"),
                                 new_data_part(data, media_type="application/json")]
            await updater.add_artifact(parts, name=ARTIFACT_NAME, last_chunk=True)
            json_line(self.log, event="task_completed", task_id=task.id, trace_id=trace_id,
                      service=result["service"], count=result["count"])
            await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id or "", context.context_id or "")
        await updater.cancel()


def build_app(identity: str, url: str, mcp_server: Any, log: TextIO, tokens: dict[str, str]) -> Starlette:
    card = agent_card(url)
    # InMemoryTaskStore loses every task on restart, which is acceptable for a lab whose tasks
    # take seconds. A long task needs a durable store (the SDK ships a database-backed one).
    handler = DefaultRequestHandler(AnalystExecutor(identity, mcp_server, log), InMemoryTaskStore(), card)
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(handler, rpc_url="/")
    return Starlette(routes=routes, middleware=[Middleware(RequireBearer, tokens=tokens, log=log)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port on {HOST} (default {DEFAULT_PORT})")
    parser.add_argument("--mcp-url", help="Streamable HTTP URL of a running MCP server; "
                                          "a stdio subprocess under TOOL_IDENTITY when omitted")
    args = parser.parse_args(argv)

    identity = require_agent_identity()
    try:
        tokens = parse_caller_tokens(os.environ.get(CALLER_TOKENS_ENV, ""))
    except ValueError as exc:
        refuse(f"{CALLER_TOKENS_ENV} is not usable ({exc}). The analyst accepts only callers it can "
               f"authenticate; set it to subject=token pairs, for example larkspur-scribe=<a long random string>.")
    if not args.mcp_url and not os.environ.get("TOOL_IDENTITY", "").strip():
        refuse("TOOL_IDENTITY is not set. The analyst launches the MCP server as a subprocess under "
               "that identity; set it, or pass --mcp-url for a server that is already running.")
    log = open_log()
    setup = tracing.configure(AGENT_NAME, identity)
    url = f"http://{HOST}:{args.port}/"
    mcp_server: Any = args.mcp_url or harness.stdio_server()
    json_line(log, event="agent_start", agent=AGENT_NAME, identity=identity, url=url,
              mcp=args.mcp_url or "stdio subprocess", allowed=sorted(ALLOWED), tracing=setup.destination,
              callers=sorted(set(tokens.values())))
    uvicorn.run(build_app(identity, url, mcp_server, log, tokens), host=HOST, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
