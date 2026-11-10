"""A read-only MCP server with a scoped identity, pinned tool definitions and a call log.

Chapter 5, part 1. The server exposes two tools over a fake Kubernetes namespace and a fake
alert store (see `fake_platform.py`). Three things make it an enterprise server rather than a
demo, and each is checked before the first request is served:

1. Identity. The process refuses to start unless `TOOL_IDENTITY` is set. Every call is logged
   under that identity, so the audit trail always says who the tools ran as.
2. Pinned definitions. `tools.lock.json` holds a SHA-256 of every tool's definition as a
   client sees it in tools/list: name, title, description, input and output schemas, and
   annotations. If any of them changed and the lock did not, the server refuses to start. The
   description is prompt text the model reads, the schemas decide what it can pass, and the
   annotations are what a client trusts about side effects; a change to any of them is a change
   to the agent, and it is reviewed like one.
3. A call log. Every tool call is one JSON line (stderr, or the file named by `TOOL_LOG_FILE`)
   with a trace id taken from the request `_meta` or generated, the tool name, the arguments
   and the identity. The harness in `../harness` writes the same trace id on its side.

Part 2 adds one `execute_tool` span per call through `../tracing/trace_setup.py`. The MCP SDK
already opens a server span from the W3C `traceparent` the client puts in `_meta`, so this span
lands inside the caller's trace; it adds the identity, and the arguments only when
LARKSPUR_TRACE_TOOL_ARGS is set (they are content; see trace_setup.tool_arguments).

Run over stdio:            TOOL_IDENTITY=larkspur-ops-reader python server.py
Run over Streamable HTTP:  TOOL_IDENTITY=larkspur-ops-reader python server.py --transport streamable-http
Rewrite the lock on purpose:  python server.py --write-lock

The server binds 127.0.0.1 only. It is a local lab; nothing here is reachable from the network.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from fake_platform import (MAX_WINDOW_MINUTES, AlertList, PodStatus, UnknownService, pod_status,
                           recent_alerts)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tracing"))
import trace_setup as tracing  # noqa: E402

LOCK_PATH = HERE / "tools.lock.json"
TRACE_META_KEY = "trace_id"  # the `_meta` key the harness writes and this server reads
HOST = "127.0.0.1"  # local only, on purpose; there is no flag to change it
DEFAULT_PORT = 8765
SERVER_NAME = "larkspur-ops-reader"

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                            open_world_hint=False)


# --- startup checks -------------------------------------------------------------------------

class LockMismatch(Exception):
    """The advertised tool definitions do not match tools.lock.json."""


def refuse(message: str) -> None:
    """Refuse to start: say why on stderr and exit with status 2."""
    print(f"refusing to start: {message}", file=sys.stderr)
    raise SystemExit(2)


def require_identity(environ: dict[str, str] | os._Environ[str] = os.environ) -> str:
    identity = environ.get("TOOL_IDENTITY", "").strip()
    if not identity:
        refuse("TOOL_IDENTITY is not set. This server only runs under a named identity, "
               "for example TOOL_IDENTITY=larkspur-ops-reader.")
    if any(c.isspace() for c in identity):
        refuse(f"TOOL_IDENTITY {identity!r} contains whitespace; use one token such as larkspur-ops-reader.")
    return identity


# The fields of a tools/list entry the lock pins, in their wire spelling: everything a model
# reads or a client acts on, including `execution` (task support). `_meta` and `icons` are left
# out: neither reaches the model or changes what a call may do.
LOCKED_FIELDS = ("name", "title", "description", "inputSchema", "outputSchema", "annotations",
                 "execution")


def canonical_definition(tool: Any) -> dict[str, Any]:
    """A tool as the lock sees it: the locked fields that are present, as plain JSON values."""
    data = tool if isinstance(tool, dict) else tool.model_dump(by_alias=True, exclude_none=True, mode="json")
    return {key: data[key] for key in LOCKED_FIELDS if data.get(key) is not None}


def definition_hash(definition: dict[str, Any]) -> str:
    """SHA-256 of the definition as sorted, compact JSON, so key order and spacing do not count."""
    text = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_lock(path: Path) -> dict[str, str]:
    """tool name -> sha256 of its definition, as recorded in the lock file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name: entry["sha256"] for name, entry in data["tools"].items()}


def write_lock(definitions: dict[str, dict[str, Any]], path: Path) -> None:
    data = {
        "comment": "SHA-256 of each tool's definition (name, title, description, input and output "
                   "schemas, annotations). Regenerate with `python server.py --write-lock` and review "
                   "the diff: the description is prompt text the model reads, and the schemas and "
                   "annotations decide what it can ask for.",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "tools": {
            name: {"sha256": definition_hash(definition), "definition": definition}
            for name, definition in sorted(definitions.items())
        },
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verify_lock(definitions: dict[str, dict[str, Any]], lock: dict[str, str]) -> None:
    """Raise LockMismatch unless every advertised definition hashes to its locked value."""
    problems = []
    for name, definition in sorted(definitions.items()):
        if name not in lock:
            problems.append(f"{name}: not in the lock file")
        elif lock[name] != definition_hash(definition):
            problems.append(f"{name}: definition changed (lock {lock[name][:12]}..., "
                            f"now {definition_hash(definition)[:12]}...)")
    for name in sorted(set(lock) - set(definitions)):
        problems.append(f"{name}: in the lock file but not served")
    if problems:
        raise LockMismatch("; ".join(problems))


def advertised_definitions(server: MCPServer) -> dict[str, dict[str, Any]]:
    """What a client will see in tools/list, which is what the lock pins."""
    tools = asyncio.run(server.list_tools())
    return {tool.name: canonical_definition(tool) for tool in tools}


# --- logging --------------------------------------------------------------------------------

def open_log(environ: dict[str, str] | os._Environ[str] = os.environ) -> TextIO:
    """stderr by default: on stdio, stdout belongs to the protocol."""
    path = environ.get("TOOL_LOG_FILE")
    if path:
        return open(path, "a", encoding="utf-8")
    return sys.stderr


def json_line(stream: TextIO, **fields: Any) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **fields}
    stream.write(json.dumps(record, sort_keys=False) + "\n")
    stream.flush()


def trace_id_from(ctx: Context) -> tuple[str, str]:
    """The caller's trace id from request `_meta`, or a fresh one. Returns (id, source)."""
    meta = ctx.request_context.meta or {}
    value = meta.get(TRACE_META_KEY)
    if isinstance(value, str) and value.strip():
        return value.strip(), "request"
    return uuid.uuid4().hex, "generated"


# --- the server -----------------------------------------------------------------------------

def build_server(identity: str, log: TextIO, transport: str) -> MCPServer:
    server = MCPServer(
        SERVER_NAME,
        instructions="Read-only view of the Larkspur Mutual production namespace. "
                     "Nothing here changes anything.",
    )

    def run_tool(ctx: Context, tool: str, args: dict[str, Any], fn: Any) -> dict[str, Any]:
        trace_id, source = trace_id_from(ctx)
        entry: dict[str, Any] = {
            "event": "tool_call", "trace_id": trace_id, "trace_source": source,
            "tool": tool, "args": args, "identity": identity, "transport": transport,
        }
        attributes = {
            tracing.GEN_AI_OPERATION_NAME: tracing.OP_EXECUTE_TOOL,
            tracing.GEN_AI_TOOL_NAME: tool,
            tracing.GEN_AI_TOOL_TYPE: tracing.TOOL_TYPE_FUNCTION,
            tracing.GEN_AI_TOOL_CALL_ARGUMENTS: tracing.tool_arguments(args),  # opt-in
            tracing.LARKSPUR_COMPONENT: "mcp-server",
            tracing.LARKSPUR_IDENTITY: identity,
            tracing.LARKSPUR_TRACE_ID: trace_id,
        }
        with tracing.start_span(f"{tracing.OP_EXECUTE_TOOL} {tool}", attributes=attributes) as span:
            try:
                result = fn(**args)
            except (UnknownService, ValueError) as exc:
                span.set_attribute(tracing.ERROR_TYPE, type(exc).__name__)
                json_line(log, **entry, ok=False, error=str(exc))
                raise ToolError(str(exc)) from exc
        json_line(log, **entry, ok=True)
        return result

    @server.tool(
        description="Pod counts and restarts for one deployment. Read-only.",
        annotations=READ_ONLY,
    )
    def get_pod_status(service: str, ctx: Context) -> PodStatus:
        return run_tool(ctx, "get_pod_status", {"service": service}, pod_status)

    @server.tool(
        description="Return the alerts that fired for one deployment within the last N minutes "
                    f"(1 to {MAX_WINDOW_MINUTES}), newest first, with severity and summary. Read-only.",
        annotations=READ_ONLY,
    )
    def get_recent_alerts(service: str, minutes: int, ctx: Context) -> AlertList:
        return run_tool(ctx, "get_recent_alerts", {"service": service, "minutes": minutes},
                        recent_alerts)

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Streamable HTTP port on {HOST} (default {DEFAULT_PORT})")
    parser.add_argument("--lock", type=Path, default=LOCK_PATH, help="path to tools.lock.json")
    parser.add_argument("--write-lock", action="store_true",
                        help="rewrite the lock file from the current definitions and exit")
    args = parser.parse_args(argv)

    if args.write_lock:
        definitions = advertised_definitions(build_server("lock-writer", io.StringIO(), "none"))
        write_lock(definitions, args.lock)
        print(f"wrote {args.lock} with {len(definitions)} tools")
        return 0

    identity = require_identity()
    log = open_log()
    server = build_server(identity, log, args.transport)

    definitions = advertised_definitions(server)
    try:
        verify_lock(definitions, read_lock(args.lock))
    except FileNotFoundError:
        refuse(f"{args.lock} not found; create it with --write-lock and commit it.")
    except LockMismatch as exc:
        refuse(f"tool definitions do not match {args.lock.name}: {exc}. "
               "If the change is intended, rerun with --write-lock and review the diff.")

    setup = tracing.configure("mcp-server", identity)
    json_line(log, event="server_start", identity=identity, transport=args.transport,
              tools={name: definition_hash(d)[:12] for name, d in definitions.items()},
              lock=str(args.lock), tracing=setup.destination)
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=HOST, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
