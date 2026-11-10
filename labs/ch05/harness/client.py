"""The chapter 1 agent loop, with its tool behind the chapter 5 MCP server.

Chapter 5, part 1. The harness is the part that owns the decisions:

- it connects to the server (a stdio subprocess by default, or a Streamable HTTP URL),
- it lists the server's tools and verifies every definition hash (description, schemas,
  annotations) against `tools.lock.json` before the model sees a single description,
- it runs `run_agent` from `labs/ch01` unchanged, handing it an allowlist that is narrower
  than what the server offers (the server serves two tools, the harness allows one),
- it writes one JSON line per tool call with the trace id it sends in the request `_meta`,
  so the client log and the server log can be joined on that id.

Part 2 adds the tracing hook (`../tracing/trace_setup.py`): the run is one `invoke_agent` span
and every tool call one `execute_tool` span. When the trace id is 32 hex characters it becomes
the OpenTelemetry trace id as well, so the spans, the `_meta` trace id and both logs agree.
The MCP SDK carries the W3C `traceparent` in `_meta` on its own, so the server's spans join.

Run against a stdio subprocess:   TOOL_IDENTITY=larkspur-ops-reader python client.py
Run against a running HTTP server: python client.py --url http://127.0.0.1:8765/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from mcp import Client, StdioServerParameters
from opentelemetry import context as otel_context

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
SERVER_PY = LAB / "mcp-server" / "server.py"
LOCK_PATH = LAB / "mcp-server" / "tools.lock.json"
TRACE_META_KEY = "trace_id"
CALL_TIMEOUT_SECONDS = 30
# Environment variables handed to the stdio server subprocess; nothing else gets through.
SUBPROCESS_ENV = ("TOOL_IDENTITY", "TOOL_LOG_FILE", "TRACE_FILE", "OTEL_EXPORTER_OTLP_ENDPOINT")

sys.path.insert(0, str(LAB.parent / "ch01"))
sys.path.insert(0, str(LAB / "tracing"))
import trace_setup as tracing  # noqa: E402
from agent_loop import fake_model, run_agent  # noqa: E402  (listing 1.1, reused as is)

# The harness decides what it will run. The server also serves get_recent_alerts; the model
# does not get to call it from here, whatever the model or the server says.
ALLOWED: dict[str, set[str]] = {"get_pod_status": {"service"}}


class LockMismatch(Exception):
    """The server's advertised definitions do not match the lock file the harness trusts."""


class UnexpectedServer(Exception):
    """The server does not serve a tool the harness needs."""


# Deliberately a copy of the server's functions: the harness trusts the lock file, not the
# server's code, and does not import it.
LOCKED_FIELDS = ("name", "title", "description", "inputSchema", "outputSchema", "annotations",
                 "execution")


def canonical_definition(tool: Any) -> dict[str, Any]:
    data = tool if isinstance(tool, dict) else tool.model_dump(by_alias=True, exclude_none=True, mode="json")
    return {key: data[key] for key in LOCKED_FIELDS if data.get(key) is not None}


def definition_hash(definition: dict[str, Any]) -> str:
    text = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_lock(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name: entry["sha256"] for name, entry in data["tools"].items()}


def verify_tools(tools: list[Any], lock: dict[str, str], allowed: dict[str, set[str]]) -> dict[str, str]:
    """Every advertised tool must be in the lock with a matching hash; every allowed tool must be served.

    Returns tool name -> hash prefix for the log.
    """
    served = {tool.name: canonical_definition(tool) for tool in tools}
    problems = []
    for name, definition in sorted(served.items()):
        if name not in lock:
            problems.append(f"{name}: served but not in the lock file")
        elif lock[name] != definition_hash(definition):
            problems.append(f"{name}: definition does not match the lock")
    if problems:
        raise LockMismatch("; ".join(problems))
    missing = sorted(set(allowed) - set(served))
    if missing:
        raise UnexpectedServer(f"allowed tools not served: {', '.join(missing)}")
    return {name: definition_hash(definition)[:12] for name, definition in served.items()}


def json_line(stream: TextIO, **fields: Any) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **fields}
    stream.write(json.dumps(record) + "\n")
    stream.flush()


def stdio_server(identity: str | None = None, log_file: str | None = None) -> StdioServerParameters:
    """Launch `server.py` as a subprocess. The identity comes from the caller's environment unless given."""
    # The subprocess gets a minimal environment; only SUBPROCESS_ENV is passed through.
    env = {name: os.environ[name] for name in SUBPROCESS_ENV if os.environ.get(name)}
    if identity:
        env["TOOL_IDENTITY"] = identity
    if log_file:
        env["TOOL_LOG_FILE"] = log_file
    return StdioServerParameters(command=sys.executable, args=[str(SERVER_PY)], env=env or None)


async def run_harness(
    server: Any,
    question: str = "Is claims-api healthy?",
    *,
    model: Callable[[list[dict]], dict] = fake_model,
    trace_id: str | None = None,
    log: TextIO = sys.stderr,
    lock_path: Path = LOCK_PATH,
    allowed: dict[str, set[str]] = ALLOWED,
    audit: Mapping[str, Any] | None = None,
) -> str:
    """Connect, verify the tools, run the chapter 1 loop, return its answer.

    The whole run is one `invoke_agent` span. A 32-hex `trace_id` is adopted as the span's trace
    id when no trace is in flight; inside one (the analyst calling this), the span joins it.
    `audit` holds fields the caller adds to every log line of the run, after the trace id: the
    runtime adapter puts Foundry's identifier for the caller there.
    """
    trace_id = trace_id or tracing.new_trace_id()
    audit = dict(audit or {})
    # A transport in front of a tool gateway may serve the tools under other names (AgentCore
    # Gateway prefixes the target's). It maps them back before the lock check and forward on a call.
    local_tools = getattr(server, "local_tools", lambda served: served)
    served_name = getattr(server, "served_name", lambda name: name)
    transport = ("http" if isinstance(server, str) else "stdio" if isinstance(server, StdioServerParameters)
                 else getattr(server, "transport_name", "inproc"))  # a transport object may say what it is
    loop = asyncio.get_running_loop()
    attributes = {
        tracing.GEN_AI_OPERATION_NAME: tracing.OP_INVOKE_AGENT,
        tracing.GEN_AI_AGENT_NAME: "harness",
        tracing.GEN_AI_PROVIDER_NAME: "larkspur.fake",  # not a listed provider: the model is a function
        tracing.GEN_AI_REQUEST_MODEL: getattr(model, "__name__", type(model).__name__),
        tracing.LARKSPUR_COMPONENT: "harness",
        tracing.LARKSPUR_TRACE_ID: trace_id,
        "larkspur.transport": transport,
    }

    refusal: Exception | None = None
    answer = ""
    with tracing.start_span(f"{tracing.OP_INVOKE_AGENT} harness", trace_id=trace_id,
                            attributes=attributes) as span:
        span_context = otel_context.get_current()  # handed to the bridges: tool spans nest under this one
        async with Client(server) as client:
            listing = await client.list_tools()
            try:
                hashes = verify_tools(local_tools(listing.tools), read_lock(lock_path), allowed)
            except (LockMismatch, UnexpectedServer) as exc:
                # Remember the refusal and leave the session cleanly. An exception escaping
                # `async with Client` comes back wrapped in an ExceptionGroup; callers should see
                # the plain refusal, so it is raised after the block.
                refusal = exc
                span.set_attribute(tracing.LARKSPUR_REFUSED, True)
                span.set_attribute(tracing.ERROR_TYPE, type(exc).__name__)
                json_line(log, event="refused", trace_id=trace_id, **audit, transport=transport, reason=str(exc))
            else:
                json_line(log, event="tools_verified", trace_id=trace_id, **audit, transport=transport,
                          tools=hashes, lock=str(lock_path))
                tools = {name: bridge(client, name, trace_id, transport, log, loop, span_context, audit,
                                      served_name(name))
                         for name in allowed}
                answer = await asyncio.to_thread(run_agent, question, model=model, tools=tools, allowed=allowed)
                refused = answer.startswith("Refused:")
                span.set_attribute(tracing.LARKSPUR_REFUSED, refused)
                json_line(log, event="answer", trace_id=trace_id, **audit, refused=refused, answer=answer)
    if refusal is not None:
        raise refusal
    return answer


def bridge(client: Client, name: str, trace_id: str, transport: str, log: TextIO,
           loop: asyncio.AbstractEventLoop, span_context: otel_context.Context | None = None,
           audit: Mapping[str, Any] | None = None, served: str | None = None) -> Callable[..., dict]:
    """A synchronous function for `run_agent` that calls one MCP tool with the trace id attached.

    `run_agent` is synchronous, as printed in chapter 1, and runs in a worker thread. Each tool
    call is handed back to the event loop that owns the MCP session and the thread waits for it.
    Only allowed tools get a bridge, so nothing else is callable from the loop's side.

    Each call is one `execute_tool` span under the run's span. The MCP SDK opens its own client
    span inside it and writes the W3C `traceparent` into `_meta`, next to our plain `trace_id`.
    `served` is the tool's name on the wire when a gateway serves it under another; the span and
    the log keep the tool's own name.
    """

    async def call(args: dict[str, Any]) -> dict[str, Any]:
        attributes = {
            tracing.GEN_AI_OPERATION_NAME: tracing.OP_EXECUTE_TOOL,
            tracing.GEN_AI_TOOL_NAME: name,
            tracing.GEN_AI_TOOL_TYPE: tracing.TOOL_TYPE_FUNCTION,
            tracing.GEN_AI_TOOL_CALL_ARGUMENTS: tracing.tool_arguments(args),  # opt-in
            tracing.LARKSPUR_COMPONENT: "harness",
            tracing.LARKSPUR_TRACE_ID: trace_id,
        }
        with tracing.start_span(f"{tracing.OP_EXECUTE_TOOL} {name}", context=span_context,
                                attributes=attributes) as span:
            result = await client.call_tool(served or name, args, meta={TRACE_META_KEY: trace_id})
            if result.is_error:
                span.set_attribute(tracing.ERROR_TYPE, "tool_error")
        json_line(log, event="tool_call", trace_id=trace_id, **(audit or {}), tool=name, args=args,
                  transport=transport, ok=not result.is_error)
        if result.is_error:
            return {"error": "".join(getattr(block, "text", "") for block in result.content)}
        return result.structured_content

    def tool(**args: Any) -> dict:
        return asyncio.run_coroutine_threadsafe(call(args), loop).result(timeout=CALL_TIMEOUT_SECONDS)

    return tool


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", help="Streamable HTTP URL of a running server, e.g. http://127.0.0.1:8765/mcp")
    parser.add_argument("--question", default="Is claims-api healthy?")
    parser.add_argument("--trace-id", help="trace id to send; generated when omitted. 32 hex characters "
                                           "make it the OpenTelemetry trace id too")
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    args = parser.parse_args(argv)

    setup = tracing.configure("harness")
    json_line(sys.stderr, event="tracing", exporter=type(setup.exporter).__name__, destination=setup.destination)
    server: Any = args.url or stdio_server()
    trace_id = args.trace_id or tracing.new_trace_id()
    try:
        answer = asyncio.run(run_harness(server, args.question, trace_id=trace_id, lock_path=args.lock))
    except (LockMismatch, UnexpectedServer) as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2
    print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
