"""analyst: an A2A agent that gathers the evidence for one change. Owned by the platform team.

Chapter 13, W4-D3. The analyst serves an Agent Card and one skill, `assess-change`. A task of the form
"assess <repo>#<number>" makes it gather the facts about that change and return them as one artifact: a
one-line summary and a structured-data part the risk scorer reads. It is read-only and holds no write
identity. In step 2 the gathering is a stub (`evidence.gather_evidence`); step 3 reads the GitHub, CI,
Terraform-plan, and ServiceNow fakes there. The analyst treats a pull request's title and body as
untrusted text (W4-D12): it reports them as fields, it does not act on them.

Four rules, each checked before any work is done, as chapter 5's analyst had:

1. Identity. The process refuses to start unless `AGENT_IDENTITY` is set.
2. Authentication. The card declares a bearer scheme; every request but the card needs a token of a
   known caller (`ANALYST_CALLER_TOKENS`), or it gets 401 before the SDK sees it. The caller is the
   token's subject; a request whose `agent_identity` metadata names someone else is rejected.
3. Trace id. A task whose request metadata carries no `trace_id` is rejected (A2A state REJECTED).
4. Scope. The one skill is assessing a change. A task with no change reference is rejected.

Run:  AGENT_IDENTITY=larkspur-analyst ANALYST_CALLER_TOKENS=larkspur-scribe=<a long random string> \
      python analyst.py
Binds 127.0.0.1 only. The A2A SDK's own spans are off by default here (see chapter 5's README).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TextIO

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
    BEARER_SCHEME, CALLER_IDENTITY_KEY, TRACE_ID_KEY, TRACEPARENT_KEY, json_line, open_log,
    require_agent_identity, require_caller_tokens, subject_for,
)
import trace_setup as tracing  # noqa: E402
import evidence as ev  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8770
AGENT_NAME = "analyst"
AGENT_VERSION = "0.1.0"
AGENT_DESCRIPTION = ("Gathers the evidence for one Larkspur Mutual change (a pull request): the diff, the "
                     "CI result, the Terraform plan, and the service's recent changes. Read-only.")
SKILL_ID = "assess-change"
ARTIFACT_NAME = "change-evidence"
CALLER_TOKENS_ENV = "ANALYST_CALLER_TOKENS"


def agent_card(url: str) -> AgentCard:
    """The card the scribe discovers at /.well-known/agent-card.json."""
    return AgentCard(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        version=AGENT_VERSION,
        provider=AgentProvider(organization="Larkspur Mutual (fictional), platform team",
                               url="https://example.invalid/larkspur"),
        supported_interfaces=[AgentInterface(
            url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True),
        security_schemes={BEARER_SCHEME: SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                scheme="bearer",
                description="A token issued to the calling agent's identity. The lab keeps a static "
                            "token per caller; production uses a short-lived JWT from the identity "
                            "provider."))},
        security_requirements=[SecurityRequirement(schemes={BEARER_SCHEME: StringList(list=[])})],
        default_input_modes=["text/plain"],
        default_output_modes=["application/json", "text/plain"],
        skills=[AgentSkill(
            id=SKILL_ID,
            name="Assess a change",
            description="Given a change reference (repo#number), return the evidence a change advisory "
                        "board needs: the diff summary, the CI result, the Terraform plan, the service's "
                        "recent changes, and the facts a risk score reads. Read-only.",
            tags=["change-management", "evidence", "read-only"],
            examples=["assess claims-api#482", "gather the evidence for fraud-scoring#120"],
        )],
    )


class RequireBearer:
    """ASGI middleware: everything except the Agent Card needs the bearer token of a known caller."""

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
                                traceparent=traceparent, trace_id=trace_id, attributes=attributes) as span:
            json_line(self.log, event="task_received", task_id=task.id, trace_id=trace_id,
                      identity=self.identity, caller=caller, trace_source=trace_source, text=text)
            try:
                change_ref, service = ev.parse_change_ref(text)
            except ValueError as exc:
                reason = (f"{exc}; the analyst assesses one change, for example 'assess claims-api#482'")
                span.set_attribute(tracing.LARKSPUR_REFUSED, True)
                json_line(self.log, event="task_rejected", task_id=task.id, trace_id=trace_id, reason=reason)
                await updater.reject(updater.new_agent_message([new_text_part(f"refused: {reason}")]))
                return

            await updater.start_work(updater.new_agent_message(
                [new_text_part(f"gathering the evidence for {change_ref}")]))
            try:
                data = ev.gather_evidence(change_ref, service)
            except ev.SourceUnavailable as exc:
                # A source the analyst cannot read fails the task, naming the source, so the scribe
                # records an incomplete pack with the message and writes nothing; the task is never
                # left in working for the caller to time out on (the reader review, finding 1).
                span.set_attribute(tracing.ERROR_TYPE, "source:" + exc.source)
                json_line(self.log, event="task_failed", task_id=task.id, trace_id=trace_id,
                          change_ref=change_ref, source=exc.source, reason=str(exc))
                await updater.failed(updater.new_agent_message([new_text_part(f"failed: {exc}")]))
                return
            data["trace_id"] = trace_id
            data["produced_by"] = self.identity
            data["requested_by"] = caller
            summary = (f"{change_ref} on {service}: {data['files_changed']} files, "
                       f"+{data['additions']}/-{data['deletions']}, CI {data['ci_state']}, "
                       f"{data['change_class']} change"
                       + (", rollback named" if data["rollback_plan_present"] else ", no rollback named")
                       + (", touches a tier-0 service" if data["touches_tier0"] else "")
                       + (", touches the payments slice" if data["touches_payments_slice"] else "")
                       + (", in the freeze window" if data["in_freeze_window"] else "") + ".")
            parts: list[Part] = [new_text_part(summary, media_type="text/plain"),
                                 new_data_part(data, media_type="application/json")]
            await updater.add_artifact(parts, name=ARTIFACT_NAME, last_chunk=True)
            json_line(self.log, event="task_completed", task_id=task.id, trace_id=trace_id,
                      change_ref=change_ref, service=service)
            await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id or "", context.context_id or "")
        await updater.cancel()


def build_app(identity: str, url: str, log: TextIO, tokens: dict[str, str]) -> Starlette:
    card = agent_card(url)
    handler = DefaultRequestHandler(AnalystExecutor(identity, log), InMemoryTaskStore(), card)
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
