"""scribe: the client agent. Discovers the analyst, sends it one task, writes the artifact.

Chapter 5, part 2. The scribe does what a workflow step does in chapter 13: it finds another
agent through its Agent Card, hands it a task, follows the task through its states, and keeps
the artifact. It runs under its own identity (`AGENT_IDENTITY`, required) and authenticates with
its own token (`AGENT_TOKEN`, required), which it sends only to an agent whose card declares a
bearer scheme. Every request carries the W3C `traceparent` of the scribe's span as an HTTP header
and, as a workaround for the SDK, in the metadata too, with the plain trace id next to it, so
the analyst, the harness inside it and the MCP server behind that all end up in the same trace.

Run:  AGENT_IDENTITY=larkspur-scribe AGENT_TOKEN=<the token the analyst knows> \
      python scribe.py --service claims-api --out summary.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse

os.environ.setdefault("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "false")  # see analyst.py

import httpx  # noqa: E402
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory  # noqa: E402
from a2a.helpers import get_data_parts, get_text_parts, new_text_message  # noqa: E402
from a2a.types import AgentCard, GetTaskRequest, Role, SendMessageRequest, Task, TaskState  # noqa: E402
from opentelemetry.trace import SpanKind  # noqa: E402

from agent_common import (  # noqa: E402
    CALLER_IDENTITY_KEY, TRACE_ID_KEY, TRACEPARENT_KEY, json_line, open_log, require_agent_identity,
    require_token,
)
import trace_setup as tracing  # noqa: E402

AGENT_NAME = "scribe"
DEFAULT_ANALYST_URL = "http://127.0.0.1:8766"
REQUEST_TIMEOUT_SECONDS = 60.0


@dataclass
class TaskRun:
    """What the scribe saw of one task, from the first event to the final GetTask."""
    task_id: str = ""
    context_id: str = ""
    states: list[str] = field(default_factory=list)
    status_messages: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    final: Task | None = None

    @property
    def final_state(self) -> str:
        return TaskState.Name(self.final.status.state) if self.final else "unknown"


def whole_numbers(value: Any) -> Any:
    """Undo protobuf's number handling: a data part stores every number as a double."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: whole_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [whole_numbers(v) for v in value]
    return value


def artifact_record(artifact: Any) -> dict[str, Any]:
    data = [whole_numbers(d) for d in get_data_parts(artifact.parts)]
    return {
        "artifact_id": artifact.artifact_id,
        "name": artifact.name,
        "text": "\n".join(get_text_parts(artifact.parts)),
        "data": data[0] if len(data) == 1 else data,
    }


class NoBearerScheme(Exception):
    """The agent's card declares no bearer scheme, so the scribe will not send it a token."""


class ForeignInterface(Exception):
    """The card names an interface on another origin; the token would leave for a host nobody chose."""


def same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    port = {"http": 80, "https": 443}
    return ((pa.scheme, pa.hostname, pa.port or port.get(pa.scheme))
            == (pb.scheme, pb.hostname, pb.port or port.get(pb.scheme)))


def bearer_schemes(card: AgentCard) -> list[str]:
    return [name for name, scheme in card.security_schemes.items()
            if scheme.HasField("http_auth_security_scheme")
            and scheme.http_auth_security_scheme.scheme.lower() == "bearer"]


async def discover(http: httpx.AsyncClient, url: str, log: TextIO) -> AgentCard:
    """Fetch the Agent Card from the well-known path, without credentials: the card is public."""
    card = await A2ACardResolver(http, url).get_agent_card()
    json_line(log, event="agent_card", name=card.name, version=card.version,
              skills=[skill.id for skill in card.skills],
              interfaces=[(i.protocol_binding, i.url) for i in card.supported_interfaces],
              streaming=card.capabilities.streaming, bearer_schemes=bearer_schemes(card))
    return card


def connect(card: AgentCard, token: str, *, origin: str, traceparent: str | None = None,
            timeout: float = REQUEST_TIMEOUT_SECONDS) -> tuple[Client, httpx.AsyncClient]:
    """An A2A client whose every request carries the token and, when given, the `traceparent`.

    The token goes only to the origin the card was fetched from: a card is data the other side
    controls, and an interface URL on another host would carry the token there.
    """
    if not bearer_schemes(card):
        raise NoBearerScheme(f"{card.name!r} declares no bearer scheme; not sending it a token")
    foreign = [i.url for i in card.supported_interfaces if not same_origin(i.url, origin)]
    if foreign:
        raise ForeignInterface(f"{card.name!r} names interfaces outside {origin}: {foreign}")
    headers = {"Authorization": f"Bearer {token}"}
    if traceparent:
        headers["traceparent"] = traceparent
    http = httpx.AsyncClient(timeout=httpx.Timeout(timeout), headers=headers)
    return ClientFactory(ClientConfig(httpx_client=http, streaming=True)).create(card), http


async def send_task(client: Client, text: str, metadata: dict[str, Any], log: TextIO) -> TaskRun:
    """Send one message, follow the task's events to a terminal state, fetch the final task."""
    request = SendMessageRequest(message=new_text_message(text, role=Role.ROLE_USER))
    request.metadata.update(metadata)
    run = TaskRun()
    json_line(log, event="task_sent", text=text, **metadata)
    async for event in client.send_message(request):
        kind = event.WhichOneof("payload")  # task, status_update, artifact_update or message
        if event.HasField("task"):
            run.task_id, run.context_id = event.task.id, event.task.context_id
            run.states.append(TaskState.Name(event.task.status.state))
        elif event.HasField("status_update"):
            status = event.status_update.status
            run.states.append(TaskState.Name(status.state))
            if status.HasField("message"):
                run.status_messages.append("\n".join(get_text_parts(status.message.parts)))
        elif event.HasField("artifact_update"):
            run.artifacts.append(artifact_record(event.artifact_update.artifact))
        json_line(log, event="task_event", task_id=run.task_id, kind=kind,
                  state=run.states[-1] if run.states else None)
    if run.task_id:
        run.final = await client.get_task(GetTaskRequest(id=run.task_id))
    return run


async def run_scribe(analyst_url: str, service: str, out: Path, identity: str, token: str, *,
                     minutes: int | None = None, trace_id: str | None = None,
                     log: TextIO = sys.stderr) -> dict[str, Any]:
    """Discover the analyst, ask it to summarize one service's alerts, write the result to `out`."""
    text = f"Summarize the alerts for {service}" + (f" in the last {minutes} minutes" if minutes else "")
    parsed = urlparse(analyst_url)
    attributes = {
        tracing.GEN_AI_OPERATION_NAME: tracing.OP_INVOKE_AGENT,
        tracing.GEN_AI_AGENT_NAME: "analyst",  # the agent being invoked
        tracing.SERVER_ADDRESS: parsed.hostname,
        tracing.SERVER_PORT: parsed.port,
        tracing.LARKSPUR_COMPONENT: AGENT_NAME,
        tracing.LARKSPUR_IDENTITY: identity,
    }
    with tracing.start_span(f"{tracing.OP_INVOKE_AGENT} analyst", kind=SpanKind.CLIENT,
                            trace_id=trace_id, attributes=attributes) as span:
        # The span's trace id is the trace id, when a provider is installed; otherwise the
        # string given or generated is used alone and the spans are not recorded.
        trace_id = tracing.current_trace_id() or trace_id or tracing.new_trace_id()
        span.set_attribute(tracing.LARKSPUR_TRACE_ID, trace_id)
        metadata = {TRACE_ID_KEY: trace_id, CALLER_IDENTITY_KEY: identity}
        traceparent = tracing.current_traceparent()
        if traceparent:
            metadata[TRACEPARENT_KEY] = traceparent
        async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS)) as plain:
            card = await discover(plain, analyst_url, log)
        client, http = connect(card, token, origin=analyst_url, traceparent=traceparent)
        async with http:
            run = await send_task(client, text, metadata, log)
        span.set_attribute(tracing.A2A_TASK_ID, run.task_id)
        span.set_attribute("a2a.task.state", run.final_state)
        if run.final_state != "TASK_STATE_COMPLETED":
            span.set_attribute(tracing.ERROR_TYPE, run.final_state)

    result = {
        "trace_id": trace_id,
        "requested_by": identity,
        "analyst": {"name": card.name, "version": card.version, "url": analyst_url},
        "request": text,
        "task_id": run.task_id,
        "context_id": run.context_id,
        "states": run.states,
        "final_state": run.final_state,
        "status_messages": run.status_messages,
        "artifacts": [artifact_record(a) for a in run.final.artifacts] if run.final else run.artifacts,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    json_line(log, event="artifact_written", trace_id=trace_id, task_id=run.task_id,
              final_state=run.final_state, path=str(out))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--analyst-url", default=DEFAULT_ANALYST_URL)
    parser.add_argument("--service", default="claims-api")
    parser.add_argument("--minutes", type=int, help="alert window; the analyst defaults to 60")
    parser.add_argument("--out", type=Path, default=Path("summary.json"))
    parser.add_argument("--trace-id", help="32 hex characters; generated when omitted")
    args = parser.parse_args(argv)

    identity = require_agent_identity()
    token = require_token()
    if args.trace_id and not tracing.is_trace_id(args.trace_id):
        print("refusing to run: --trace-id must be 32 lowercase hex characters", file=sys.stderr)
        return 2
    log = open_log()
    setup = tracing.configure(AGENT_NAME, identity)
    json_line(log, event="agent_start", agent=AGENT_NAME, identity=identity, tracing=setup.destination)
    result = asyncio.run(run_scribe(args.analyst_url, args.service, args.out, identity, token,
                                    minutes=args.minutes, trace_id=args.trace_id, log=log))
    print(json.dumps({"trace_id": result["trace_id"], "final_state": result["final_state"],
                      "states": result["states"], "out": str(args.out)}))
    return 0 if result["final_state"] == "TASK_STATE_COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
