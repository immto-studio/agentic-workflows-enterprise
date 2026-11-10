"""risk_scorer: an A2A agent that scores one change from its evidence. Owned by the change-management team.

Chapter 13, W4-D3 and W4-D9. The risk scorer serves one skill, `score-change`. The scribe sends it the
analyst's evidence as a structured-data part; it returns a risk class (Low, Medium, High) from the fixed
rubric plus a rationale, as one artifact. It reaches no source: it scores the evidence it is handed,
nothing else. The class is a pure function of the evidence fields (`rubric.score`), so a hijacked
analyst message cannot move it past the facts (W4-D12); the model writes only the rationale, behind the
`rubric.rationale` seam that step 5 fills.

Why this is a separate agent over A2A, not a tool inside the scribe (W4-D2): it belongs to the
change-management team, under its own identity, so A2A pays for itself (the fact sheet, A.1).

A change is one trace. The scribe's span holds the analyst's and this agent's through the `traceparent` in
the A2A request, and this agent hands its own span's `traceparent` to the rationale seam, so the gateway's
span lands under it (chapter 16's step 3b found the call a second root, beside the scribe's).

Run:  AGENT_IDENTITY=larkspur-risk-scorer RISK_SCORER_CALLER_TOKENS=larkspur-scribe=<a long random string> \
      python risk_scorer.py
Binds 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, TextIO

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
from a2a.helpers import get_data_parts, new_data_part, new_task_from_user_message, new_text_part  # noqa: E402
from opentelemetry.trace import SpanKind  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.authentication import AuthCredentials, SimpleUser  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.types import ASGIApp, Receive, Scope, Send  # noqa: E402

from agent_common import (  # noqa: E402
    BEARER_SCHEME, CALLER_IDENTITY_KEY, TRACE_ID_KEY, TRACEPARENT_KEY, json_line, open_log,
    require_agent_identity, require_caller_tokens, subject_for, whole_numbers,
)
import trace_setup as tracing  # noqa: E402
import rationale_model  # noqa: E402
import rubric  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8771
AGENT_NAME = "risk-scorer"
AGENT_VERSION = "0.1.0"
AGENT_DESCRIPTION = ("Scores one Larkspur Mutual change from the evidence it is given: a risk class and a "
                     "rationale for the change advisory board. Reads no source of its own.")
SKILL_ID = "score-change"
ARTIFACT_NAME = "risk-score"
CALLER_TOKENS_ENV = "RISK_SCORER_CALLER_TOKENS"


def agent_card(url: str) -> AgentCard:
    return AgentCard(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        version=AGENT_VERSION,
        provider=AgentProvider(organization="Larkspur Mutual (fictional), change-management team",
                               url="https://example.invalid/larkspur"),
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True),
        security_schemes={BEARER_SCHEME: SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                scheme="bearer",
                description="A token issued to the calling agent's identity. The lab keeps a static "
                            "token per caller; production uses a short-lived JWT from the identity "
                            "provider."))},
        security_requirements=[SecurityRequirement(schemes={BEARER_SCHEME: StringList(list=[])})],
        default_input_modes=["application/json", "text/plain"],
        default_output_modes=["application/json", "text/plain"],
        skills=[AgentSkill(
            id=SKILL_ID,
            name="Score a change",
            description="Given a change-evidence artifact, return a risk class (Low, Medium, or High) "
                        "and a rationale. The class is a fixed rule over the evidence; the score is "
                        "advisory, for the change advisory board, and authorizes nothing.",
            tags=["change-management", "risk", "advisory"],
            examples=["score the attached change evidence"],
        )],
    )


class RequireBearer:
    """ASGI middleware: everything except the Agent Card needs the bearer token of a known caller."""

    def __init__(self, app: ASGIApp, tokens: dict[str, str], log: TextIO) -> None:
        self.app, self.tokens, self.log = app, tokens, log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == AGENT_CARD_WELL_KNOWN_PATH:
            await self.app(scope, receive, send)
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


class RiskScorerExecutor(AgentExecutor):
    def __init__(self, identity: str, log: TextIO) -> None:
        self.identity = identity
        self.log = log

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        meta = context.metadata
        user = context.call_context.user
        caller = user.user_name if user.is_authenticated else None
        claimed = meta.get(CALLER_IDENTITY_KEY)
        headers = context.call_context.state.get("headers", {})
        traceparent = headers.get("traceparent") or meta.get(TRACEPARENT_KEY)

        if caller is None or (claimed and claimed != caller):
            reason = (f"the request claims to come from {claimed!r} but its token belongs to {caller!r}"
                      if caller else "the request is not authenticated")
            json_line(self.log, event="task_rejected", task_id=task.id, identity=self.identity,
                      caller=caller, claimed=claimed, reason=reason)
            await updater.reject(updater.new_agent_message([new_text_part(f"refused: {reason}")]))
            return

        trace_id = meta.get(TRACE_ID_KEY)
        if not isinstance(trace_id, str) or not trace_id.strip():
            reason = f"request metadata carries no {TRACE_ID_KEY}; the risk scorer does not run untraced work"
            json_line(self.log, event="task_rejected", task_id=task.id, identity=self.identity,
                      caller=caller, reason=reason)
            await updater.reject(updater.new_agent_message([new_text_part(f"refused: {reason}")]))
            return

        # The substance is the data part, not the text. The evidence is
        # data, never an instruction: the class comes from the rubric over
        # its fields, not from any prose in it (W4-D12).
        data_parts = [whole_numbers(d)
                      for d in get_data_parts(message.parts)]
        evidence = next(
            (d for d in data_parts
             if isinstance(d, dict) and "change_ref" in d), None)
        if evidence is None:
            reason = ("the risk scorer scores a change-evidence "
                      "artifact; the request carried none")
            json_line(self.log, event="task_rejected", task_id=task.id,
                      trace_id=trace_id, reason=reason)
            await updater.reject(updater.new_agent_message(
                [new_text_part(f"refused: {reason}")]))
            return

        attributes = {
            tracing.GEN_AI_OPERATION_NAME: tracing.OP_INVOKE_AGENT,
            tracing.GEN_AI_AGENT_NAME: AGENT_NAME,
            tracing.GEN_AI_AGENT_DESCRIPTION: AGENT_DESCRIPTION,
            tracing.GEN_AI_CONVERSATION_ID: task.context_id,
            tracing.A2A_TASK_ID: task.id,
            tracing.LARKSPUR_COMPONENT: "risk-scorer",
            tracing.LARKSPUR_IDENTITY: self.identity,
            tracing.LARKSPUR_CALLER_IDENTITY: caller,
            tracing.LARKSPUR_TRACE_ID: trace_id,
        }
        with tracing.start_span(f"{tracing.OP_INVOKE_AGENT} {AGENT_NAME}", kind=SpanKind.SERVER,
                                traceparent=traceparent, trace_id=trace_id, attributes=attributes):
            json_line(self.log, event="task_received", task_id=task.id, trace_id=trace_id,
                      identity=self.identity, caller=caller, change_ref=evidence.get("change_ref"))
            await updater.start_work(updater.new_agent_message([new_text_part("scoring the change")]))
            scored = rubric.score(evidence)
            text, source = rationale_model.rationale_with_source(
                evidence, scored["risk_class"], scored["reasons"],
                trace_id=trace_id,
                traceparent=tracing.current_traceparent())
            result: dict[str, Any] = {
                "change_ref": evidence.get("change_ref"),
                "service": evidence.get("service"),
                "risk_class": scored["risk_class"],
                "reasons": scored["reasons"],
                "rationale": text,
                # "model" or "stub": a run says how many the model wrote
                "rationale_source": source,
                "trace_id": trace_id,
                "produced_by": self.identity,
                "requested_by": caller,
            }
            parts: list[Part] = [new_text_part(text, media_type="text/plain"),
                                 new_data_part(result, media_type="application/json")]
            await updater.add_artifact(parts, name=ARTIFACT_NAME, last_chunk=True)
            json_line(self.log, event="task_completed", task_id=task.id, trace_id=trace_id,
                      change_ref=result["change_ref"], risk_class=result["risk_class"])
            await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id or "", context.context_id or "")
        await updater.cancel()


def build_app(identity: str, url: str, log: TextIO, tokens: dict[str, str]) -> Starlette:
    card = agent_card(url)
    handler = DefaultRequestHandler(RiskScorerExecutor(identity, log), InMemoryTaskStore(), card)
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(handler, rpc_url="/")
    return Starlette(routes=routes, middleware=[Middleware(RequireBearer, tokens=tokens, log=log)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port on {HOST} (default {DEFAULT_PORT})")
    args = parser.parse_args(argv)

    identity = require_agent_identity()
    tokens = require_caller_tokens(CALLER_TOKENS_ENV)
    log = open_log()
    setup = tracing.configure(AGENT_NAME, identity)
    url = f"http://{HOST}:{args.port}/"
    json_line(log, event="agent_start", agent=AGENT_NAME, identity=identity, url=url,
              tracing=setup.destination, callers=sorted(set(tokens.values())))
    uvicorn.run(build_app(identity, url, log, tokens), host=HOST, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
