"""OpenTelemetry setup shared by the harness, the MCP server and both A2A agents.

Chapter 5, part 2. One module, imported by every process in the lab, so that every process
exports spans the same way and the same trace id can be followed from the scribe's request to
the MCP server's log:

- `configure(service_name, identity)` installs a tracer provider for the process. Spans go to
  the OTLP HTTP endpoint named by `OTEL_EXPORTER_OTLP_ENDPOINT` when that variable is set, and to
  a JSON lines file otherwise (`TRACE_FILE`, default `labs/ch05/traces.jsonl`). The file path is
  the lab's default because it needs nothing running; point `OTEL_EXPORTER_OTLP_ENDPOINT` at a
  local collector, Jaeger or Grafana Tempo and the same spans arrive there instead.
- `start_span(...)` opens a span under the current one, or under a W3C `traceparent` carried in
  a request. Outside any trace it can adopt a bare trace id (32 lowercase hex characters, the
  `trace_id` the part 1 harness already puts in `_meta`): the span is then a real root whose
  trace id is that string, so the logs and the spans carry the same id. `open_span(...)` does the
  same without making the span current, for callers that set their own start and end times.
- The attribute names come from the OpenTelemetry GenAI semantic conventions. Every `gen_ai.*`
  name is still marked "in development" (the installed semconv package ships them only under
  `_incubating`); the README lists them. They are spelled out here as constants rather than
  imported from that private module, and a test checks they match the package.

Nothing here depends on the rest of the lab, so a reader can lift this file into another project.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult,
)
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
from opentelemetry.trace import Span, SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

LAB = Path(__file__).resolve().parent.parent
TRACE_FILE_ENV = "TRACE_FILE"
OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
TRACE_TOOL_ARGS_ENV = "LARKSPUR_TRACE_TOOL_ARGS"
DEFAULT_TRACE_FILE = LAB / "traces.jsonl"
INSTRUMENTATION_NAME = "larkspur.lab.ch05"
SERVICE_NAMESPACE = "larkspur-lab-ch05"

# --- attribute names ------------------------------------------------------------------------
# GenAI semantic conventions, all still in development (see the README table).
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_AGENT_NAME = "gen_ai.agent.name"
GEN_AI_AGENT_DESCRIPTION = "gen_ai.agent.description"
GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_TYPE = "gen_ai.tool.type"
GEN_AI_TOOL_CALL_ARGUMENTS = "gen_ai.tool.call.arguments"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
# Well-known values for gen_ai.operation.name and gen_ai.tool.type.
OP_INVOKE_AGENT = "invoke_agent"
OP_EXECUTE_TOOL = "execute_tool"
OP_CHAT = "chat"  # a model call; the gateway's span
TOOL_TYPE_FUNCTION = "function"  # a tool the client (here: the harness) executes on the model's behalf
# Stable conventions.
SERVICE_NAME = "service.name"
SERVICE_NAMESPACE_ATTR = "service.namespace"
SERVER_ADDRESS = "server.address"
SERVER_PORT = "server.port"
ERROR_TYPE = "error.type"
# Lab-specific names. There is no convention yet for "the identity this process runs under";
# the `larkspur.` prefix says so.
LARKSPUR_IDENTITY = "larkspur.identity"
LARKSPUR_CALLER_IDENTITY = "larkspur.caller_identity"
LARKSPUR_COMPONENT = "larkspur.component"
LARKSPUR_TRACE_ID = "larkspur.trace_id"
LARKSPUR_REFUSED = "larkspur.refused"
A2A_TASK_ID = "a2a.task.id"

_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_PROPAGATOR = TraceContextTextMapPropagator()


# --- exporters ------------------------------------------------------------------------------

def span_record(span: ReadableSpan) -> dict[str, Any]:
    """One span as a flat JSON-able dict. Ids are lowercase hex, as in W3C trace context."""
    ctx = span.get_span_context()
    parent = span.parent

    def when(ns: int | None) -> str | None:
        if ns is None:
            return None
        return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat(timespec="microseconds")

    return {
        "name": span.name,
        "trace_id": trace.format_trace_id(ctx.trace_id),
        "span_id": trace.format_span_id(ctx.span_id),
        "parent_span_id": trace.format_span_id(parent.span_id) if parent else None,
        "kind": span.kind.name,
        "start": when(span.start_time),
        "end": when(span.end_time),
        "status": span.status.status_code.name,
        "status_description": span.status.description,
        "attributes": dict(span.attributes or {}),
        "events": [{"name": e.name, "attributes": dict(e.attributes or {})} for e in span.events],
        "resource": dict(span.resource.attributes),
        "scope": span.instrumentation_scope.name if span.instrumentation_scope else None,
    }


_LOCK_OFFSET = 1 << 40  # one byte at 1 TiB


@contextmanager
def _append_lock(fd: int) -> Iterator[None]:
    """Serialize appends from several processes where the OS does not (Windows); a no-op elsewhere."""
    if os.name != "nt":
        yield
        return
    import msvcrt

    # Windows byte-range locks are mandatory, so the lock sits on a byte far past the end of any
    # trace file: writers queue on it, and readers of the real content never touch it.
    os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)  # a cross-process mutex; LK_LOCK retries for about 10 s
    try:
        yield
    finally:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


class JsonLinesSpanExporter(SpanExporter):
    """Append one JSON line per span. Several processes may append to the same file.

    The analyst, the MCP server, the gateway and the harness all write here during one run, so a
    line must reach the file whole. On Linux and macOS a single `write` to a descriptor opened
    with O_APPEND is appended whole by the kernel (on a local file system). On Windows Python
    emulates O_APPEND as "seek to the end, then write", and two processes can write at the same
    offset, so there each batch holds a lock on the file's first byte while it appends. A buffered
    text file is not enough on either system: it flushes in 8 KB chunks that can end mid-line,
    which is how the first version of this exporter split a line.
    """

    _FLAGS = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [(json.dumps(span_record(span), default=str) + "\n").encode("utf-8") for span in spans]
        fd = os.open(self.path, self._FLAGS, 0o644)
        try:
            with _append_lock(fd):
                for line in lines:
                    if os.write(fd, line) != len(line):
                        return SpanExportResult.FAILURE  # a short write; never append the rest separately
        finally:
            os.close(fd)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def read_spans(path: Path) -> list[dict[str, Any]]:
    """The spans in a JSON lines trace file, in the order they were written.

    A last line without its newline is a span still being written by another process; it is left
    for the next read.
    """
    text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
    return [json.loads(line) for line in text.split("\n")[:-1] if line.strip()]


# --- provider -------------------------------------------------------------------------------

_ADOPTED: ContextVar[str | None] = ContextVar("larkspur_adopted_trace_id", default=None)


class AdoptingIdGenerator(RandomIdGenerator):
    """Random ids, except for a root span opened while a trace id is being adopted.

    The SDK asks the generator for a trace id only when a span has no valid parent, so this is
    the one place a root span can be given an id chosen elsewhere, without inventing a parent.
    """

    def generate_trace_id(self) -> int:
        adopted = _ADOPTED.get()
        return int(adopted, 16) if adopted else super().generate_trace_id()


@dataclass
class TracingSetup:
    provider: TracerProvider
    exporter: SpanExporter
    destination: str  # the endpoint or the file path, for the start-up log line


def build_provider(service_name: str, identity: str | None = None, *,
                   environ: Mapping[str, str] = os.environ) -> TracingSetup:
    """A tracer provider with the exporter chosen from the environment. Does not install it."""
    attributes: dict[str, Any] = {SERVICE_NAME: service_name, SERVICE_NAMESPACE_ATTR: SERVICE_NAMESPACE}
    if identity:
        attributes[LARKSPUR_IDENTITY] = identity
    provider = TracerProvider(resource=Resource.create(attributes), id_generator=AdoptingIdGenerator())
    endpoint = environ.get(OTLP_ENDPOINT_ENV, "").strip()
    exporter: SpanExporter
    if endpoint:
        # The exporter reads OTEL_EXPORTER_OTLP_ENDPOINT itself and appends /v1/traces.
        exporter = OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        destination = endpoint
    else:
        path = Path(environ.get(TRACE_FILE_ENV) or DEFAULT_TRACE_FILE)
        exporter = JsonLinesSpanExporter(path)
        # Simple, not batched: a span is on disk when it ends, so a short-lived process
        # (the MCP server subprocess, the scribe CLI) loses nothing on exit.
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        destination = str(path)
    return TracingSetup(provider, exporter, destination)


_INSTALLED: TracingSetup | None = None


def configure(service_name: str, identity: str | None = None, *,
              environ: Mapping[str, str] = os.environ) -> TracingSetup:
    """Install the provider for this process. The first call wins; later calls return it."""
    global _INSTALLED
    if _INSTALLED is None:
        _INSTALLED = build_provider(service_name, identity, environ=environ)
        trace.set_tracer_provider(_INSTALLED.provider)
        atexit.register(_INSTALLED.provider.shutdown)  # flushes the batch processor on exit
    return _INSTALLED


def tracer() -> trace.Tracer:
    return trace.get_tracer(INSTRUMENTATION_NAME)


# --- content in spans -----------------------------------------------------------------------

def tool_arguments(args: Mapping[str, Any], *, environ: Mapping[str, str] = os.environ) -> str | None:
    """The tool arguments as a span attribute value, or None (the attribute is left out).

    Arguments are content: a service name in this lab, a claim number or a customer's name in a
    real workflow. The GenAI conventions make `gen_ai.tool.call.arguments` opt-in and warn that it
    may hold sensitive information, and a trace store is rarely cleared for Restricted data. So
    the lab leaves them out unless LARKSPUR_TRACE_TOOL_ARGS is 1, true or yes, which is what a
    workflow whose manifest says `trace_content: true` would set. The JSON log keeps the
    arguments either way; it is the audit record, and its retention is decided separately.
    """
    if environ.get(TRACE_TOOL_ARGS_ENV, "").strip().lower() in {"1", "true", "yes"}:
        return json.dumps(dict(args), sort_keys=True)
    return None


# --- trace ids and spans --------------------------------------------------------------------

def is_trace_id(value: Any) -> bool:
    """A W3C trace id: 32 lowercase hex characters, not all zero."""
    return isinstance(value, str) and bool(_TRACE_ID.match(value)) and value != "0" * 32


def new_trace_id() -> str:
    return uuid.uuid4().hex  # 16 random bytes, which is exactly what a trace id is


def current_trace_id() -> str | None:
    """The trace id of the current span as 32 hex characters, or None outside any trace."""
    ctx = trace.get_current_span().get_span_context()
    return trace.format_trace_id(ctx.trace_id) if ctx.is_valid else None


def current_traceparent() -> str | None:
    """The W3C `traceparent` header value for the current span, to put in a request."""
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    return carrier.get("traceparent")


def parent_from(traceparent: str | None = None) -> otel_context.Context | None:
    """The context carried in a W3C `traceparent`, or None when there is none or it is invalid."""
    if traceparent:
        ctx = _PROPAGATOR.extract({"traceparent": traceparent})
        if trace.get_current_span(ctx).get_span_context().is_valid:
            return ctx
    return None


def open_span(name: str, *, kind: SpanKind = SpanKind.INTERNAL,
              attributes: Mapping[str, Any] | None = None, traceparent: str | None = None,
              trace_id: str | None = None, context: otel_context.Context | None = None,
              start_time: int | None = None, use_tracer: trace.Tracer | None = None,
              ignore_current: bool = False) -> Span:
    """Start a span, without making it current, under the first of these that exists: `context`,
    a carried `traceparent`, the current span. With none of them and a valid bare `trace_id`, the
    span is a new root with that trace id. Inside an existing trace the id is left alone, because
    one trace cannot be two. At a trust boundary, adopt nothing: start a new trace and record the
    caller's id as an attribute or a link, so a caller cannot choose where your spans land.

    `ignore_current` is for code that runs inside someone else's spans, such as a callback inside
    a web framework that traces its own requests: the ambient span is neither parent nor reason
    to skip adopting the trace id. `use_tracer` takes a tracer from a provider of the caller's own.
    """
    explicit = context if context is not None else parent_from(traceparent)
    in_ambient_trace = not ignore_current and trace.get_current_span().get_span_context().is_valid
    adopt = explicit is None and not in_ambient_trace and is_trace_id(trace_id)
    parent = explicit if explicit is not None else (otel_context.Context() if ignore_current else None)
    token = _ADOPTED.set(trace_id if adopt else None)
    try:
        clean = {k: v for k, v in (attributes or {}).items() if v is not None}
        return (use_tracer or tracer()).start_span(name, context=parent, kind=kind, attributes=clean,
                                                   start_time=start_time)
    finally:
        _ADOPTED.reset(token)


@contextmanager
def start_span(name: str, *, kind: SpanKind = SpanKind.INTERNAL,
               attributes: Mapping[str, Any] | None = None,
               traceparent: str | None = None, trace_id: str | None = None,
               context: otel_context.Context | None = None) -> Iterator[Span]:
    """`open_span`, made current for the block and ended when the block exits."""
    span = open_span(name, kind=kind, attributes=attributes, traceparent=traceparent,
                     trace_id=trace_id, context=context)
    with trace.use_span(span, end_on_exit=True) as current:
        yield current
