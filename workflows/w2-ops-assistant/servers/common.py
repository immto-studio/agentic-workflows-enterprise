"""What W2's three MCP servers share: chapter 5's lock and log, W1's caller check, and the service map.

Chapter 11. Each server is chapter 5's server grown by one thing: before it reads anything for a
service, it asks who the engineer is (the forwarded token in X-Larkspur-Actor, W1's access.py) and
whether the service map lets that engineer's teams see the service (W2-D4). The tool argument
names a service and never a namespace, a log group, or a team: the server derives the first two
from the service and takes the third from the map.

A refusal says the same thing whether the service exists or not (W1-D5's rule, kept): the
engineer learns nothing from the wording about what they can't see.

Each call's log line keeps an argument that is a value (a service from the map, a window, a count,
a series from a fixed set) as it is, and an argument a tool marks as text, which only search_logs'
`contains` is, as an HMAC under AUDIT_HMAC_KEY (W1's audit_hmac.py, chapter 17's rule, companion
#126). The text stays in the harness's log, which keeps every call's arguments, and an auditor who
holds the key matches the two through the HMAC. A search for the empty string is kept the same way,
as the HMAC of the empty string.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import yaml
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

HERE = Path(__file__).resolve().parent
W2 = HERE.parent
LABS = W2.parents[1] / "labs"
W1 = W2.parent / "w1-knowledge-assistant"
for folder in (HERE, W1 / "knowledge-server", W1 / "knowledge-server" / "membership", LABS / "ch05" / "tracing"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import trace_setup as tracing  # noqa: E402
from access import (AccessError, Caller, MembershipFile, MembershipTable, TokenPolicy,  # noqa: E402
                    caller_from_headers)
from audit_hmac import AuditKeyError, check_audit_key, text_hmac  # noqa: E402

CH05_SERVER = LABS / "ch05" / "mcp-server"
if str(CH05_SERVER) not in sys.path:  # the module imports fake_platform from its own folder
    sys.path.insert(0, str(CH05_SERVER))
_spec = importlib.util.spec_from_file_location("ch05_server", CH05_SERVER / "server.py")
ch05 = importlib.util.module_from_spec(_spec)
sys.modules["ch05_server"] = ch05
_spec.loader.exec_module(ch05)  # type: ignore[union-attr]

HOST = "127.0.0.1"  # local only, as in chapter 5
SERVICE_MAP_PATH = W2 / "catalog" / "service-map.yaml"
TABLE_PATH = W1 / "knowledge-server" / "membership" / "table.json"
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                            open_world_hint=False)
REFUSAL = "No service by that name is among the ones you can ask about."
# The mark on a tool error the model caused itself (a window out of range, an unknown metric): the
# harness hands such a result back to the model, and words every other failure itself.
BAD_ARGUMENT = "bad argument: "

# What a result may not carry into the model's context (chapter 4's rule for every tool server): the
# identifiers chapter 2 classes Confidential, and the credential shapes a log line is known to hold.
# The patterns are the lab's; a production server takes them from the logging pipeline's own list.
REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bCLM-\d{4}-\d{6}\b"), "[claim redacted]"),
    (re.compile(r"\bPOL-\d{5,}\b"), "[policy redacted]"),
    (re.compile(r"\bQTE-\d{4,}\b"), "[quote redacted]"),
    (re.compile(r"\bCUS-\d{4,}\b"), "[customer redacted]"),
    (re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{16,}"), "[credential redacted]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[access key redacted]"),
    (re.compile(r"\bhvs\.[A-Za-z0-9_-]{20,}"), "[vault token redacted]"),
    (re.compile(r"\b(password|passwd|secret|token|api[_-]?key)=\S+", re.IGNORECASE), r"\1=[redacted]"),
)


def redact(value: Any) -> Any:
    """Every string in a result, with the known identifier and credential shapes replaced."""
    if isinstance(value, str):
        for pattern, replacement in REDACTIONS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value

# W2's token: the three servers share one app registration (one audience, one delegated scope), and
# only W2's runtime may ask for a token for it. The values are synthetic, like W1's.
W2_SERVERS_APP = "3f1c9a52-6d4e-5b7a-9c0d-1e2f3a4b5c6d"
W2_RUNTIME = "a7b8c9d0-e1f2-5a3b-8c4d-5e6f7a8b9c0d"
W2_SCOPE = "Ops.Read"
# W3's runtime (chapter 12) triages with W2's reads, so it may ask for a token for W2's servers too, as
# chapter 11 said W2's runtime does for the knowledge server's app. W3's own servers have an app of their own.
W3_RUNTIME = "b8c9d0e1-f2a3-5b4c-9d5e-6f7a8b9c0d1e"
W2_POLICY = TokenPolicy(audience=W2_SERVERS_APP, scope=W2_SCOPE, clients=frozenset({W2_RUNTIME, W3_RUNTIME}))

__all__ = ["ch05", "tracing", "READ_ONLY", "HOST", "ServiceMap", "load_service_map", "Server", "serve",
           "Caller", "AccessError", "REFUSAL", "W2_POLICY", "W2_SERVERS_APP", "W2_RUNTIME", "W2_SCOPE", "W3_RUNTIME",
           "BAD_ARGUMENT", "redact"]


# --- the service map: which teams may ask about which services (W2-D4) ----------------------------

@dataclass(frozen=True)
class ServiceMap:
    reviewed: str
    teams: dict[str, frozenset[str]]  # team (an Entra group name from W1's reviewed map) -> services
    broad: frozenset[str]  # the groups that see every service a team sees? No: the services everyone sees.

    def visible(self, groups: frozenset[str]) -> frozenset[str]:
        """The services the caller's groups may ask about."""
        seen = set(self.broad)
        for group in groups:
            seen |= self.teams.get(group, frozenset())
        return frozenset(seen)


def load_service_map(path: Path = SERVICE_MAP_PATH) -> ServiceMap:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ServiceMap(reviewed=str(data["reviewed"]),
                      teams={team: frozenset(services) for team, services in data["teams"].items()},
                      broad=frozenset(data.get("everyone", [])))


# --- one server, built like chapter 5's -------------------------------------------------------

class Server:
    """A W2 MCP server: a name, an identity, the tools it serves, and the caller check before each read."""

    def __init__(self, name: str, instructions: str, identity: str, log: TextIO, transport: str,
                 table: Callable[[], MembershipTable], service_map: ServiceMap, secret: str,
                 policy: TokenPolicy = W2_POLICY) -> None:
        self.mcp = MCPServer(name, instructions=instructions)
        self.identity, self.log, self.transport = identity, log, transport
        self.table, self.service_map, self.secret, self.policy = table, service_map, secret, policy
        self._served: list[MembershipTable] = []

    def caller(self, ctx: Context, trace_id: str, tool: str) -> Caller:
        current = self.table()
        if not self._served or self._served[-1] is not current:
            self._served[:] = [current]
            ch05.json_line(self.log, event="membership", synced_at=current.synced_at,
                           delta_applied_at=current.delta_applied_at, users=len(current.members))
        headers = getattr(ctx.request_context.request, "headers", None)
        try:
            return caller_from_headers(dict(headers) if headers is not None else None, current, self.secret,
                                       policy=self.policy)
        except AccessError as exc:
            ch05.json_line(self.log, event="refused", trace_id=trace_id, tool=tool, identity=self.identity,
                           reason=str(exc))
            raise ToolError(str(exc)) from exc

    def run_tool(self, ctx: Context, tool: str, args: dict[str, Any],
                 fn: Callable[..., Any], *, text: tuple[str, ...] = ()) -> Any:
        """The caller check, the read, one log line, one span: the shape
        of chapter 5's run_tool. `text` names the arguments that are
        text, which the log line keeps only as HMACs."""
        trace_id, source = ch05.trace_id_from(ctx)
        caller = self.caller(ctx, trace_id, tool)  # token, then table
        # Values as they are, text as an HMAC (chapter 17). Every
        # argument `text` doesn't name is a value: a service from the
        # map, a window, a count, or a series. The trace id, the tool,
        # the server's identity and the engineer's object ID are system
        # identifiers; the event, trace_source and transport come from
        # fixed sets.
        logged = {name: text_hmac(value) if name in text else value
                  for name, value in args.items()}
        entry: dict[str, Any] = {
            "event": "tool_call", "trace_id": trace_id,
            "trace_source": source, "tool": tool, "args": logged,
            "identity": self.identity, "caller": caller.oid,
            "transport": self.transport,
        }
        attributes = {
            tracing.GEN_AI_OPERATION_NAME: tracing.OP_EXECUTE_TOOL,
            tracing.GEN_AI_TOOL_NAME: tool,
            tracing.GEN_AI_TOOL_TYPE: tracing.TOOL_TYPE_FUNCTION,
            tracing.GEN_AI_TOOL_CALL_ARGUMENTS:
                tracing.tool_arguments(args),
            tracing.LARKSPUR_COMPONENT: "mcp-server",
            tracing.LARKSPUR_IDENTITY: self.identity,
            tracing.LARKSPUR_CALLER_IDENTITY: caller.oid,
            tracing.LARKSPUR_TRACE_ID: trace_id,
        }
        span_name = f"{tracing.OP_EXECUTE_TOOL} {tool}"
        with tracing.start_span(span_name, attributes=attributes) as span:
            service = args.get("service")
            if service not in self.service_map.visible(caller.groups):  # <1>
                # One sentence for a service that doesn't exist and for
                # one the caller may not see.
                span.set_attribute(tracing.LARKSPUR_REFUSED, True)
                ch05.json_line(self.log, **entry, ok=False,
                               refused="service not visible")
                raise ToolError(REFUSAL)  # <2>
            try:
                result = redact(fn(**args))  # chapter 4: redact first
            except ch05.UnknownService as exc:
                # Visible in the map, unknown to the platform: not the
                # model's doing, so it ends the question as an outage.
                span.set_attribute(tracing.ERROR_TYPE, type(exc).__name__)
                ch05.json_line(self.log, **entry, ok=False,
                               error=str(exc))
                raise ToolError(str(exc)) from exc
            except ValueError as exc:
                # The model's own argument: marked, and handed back to it.
                span.set_attribute(tracing.ERROR_TYPE, type(exc).__name__)
                ch05.json_line(self.log, **entry, ok=False,
                               error=BAD_ARGUMENT + str(exc))
                raise ToolError(BAD_ARGUMENT + str(exc)) from exc  # <3>
        ch05.json_line(self.log, **entry, ok=True)  # never the result <4>
        return result


def serve(build: Callable[[str, TextIO, str, Callable[[], MembershipTable], ServiceMap, str], Server],
          default_port: int, lock_path: Path, argv: list[str] | None = None) -> int:
    """The chapter 5 command line: --write-lock, the lock check, the identity, then the transport."""
    parser = argparse.ArgumentParser(description=build.__doc__.split("\n")[0] if build.__doc__ else "W2 server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="streamable-http")
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--lock", type=Path, default=lock_path)
    parser.add_argument("--write-lock", action="store_true")
    args = parser.parse_args(argv)

    empty_table = MembershipTable(synced_at="1970-01-01T00:00:00Z", group_names={}, members={})
    if args.write_lock:
        server = build("lock-writer", io.StringIO(), "none", lambda: empty_table, load_service_map(), "x" * 32)
        definitions = ch05.advertised_definitions(server.mcp)
        ch05.write_lock(definitions, args.lock)
        print(f"wrote {args.lock} with {len(definitions)} tools")
        return 0

    identity = ch05.require_identity()
    secret = os.environ.get("W2_TOKEN_SECRET", "").strip()
    if len(secret) < 32:
        ch05.refuse("W2_TOKEN_SECRET is not set or shorter than 32 bytes.")
    try:
        check_audit_key()  # a short key is refused; an unset one is made, with a warning, when a line needs it
    except AuditKeyError as exc:
        ch05.refuse(str(exc))
    table_path = Path(os.environ.get("MEMBERSHIP_TABLE", str(TABLE_PATH)))
    membership = MembershipFile(table_path)
    log = ch05.open_log()
    server = build(identity, log, args.transport, membership.current, load_service_map(), secret)

    definitions = ch05.advertised_definitions(server.mcp)
    try:
        ch05.verify_lock(definitions, ch05.read_lock(args.lock))
    except FileNotFoundError:
        ch05.refuse(f"{args.lock} not found; create it with --write-lock and commit it.")
    except ch05.LockMismatch as exc:
        ch05.refuse(f"tool definitions do not match {args.lock.name}: {exc}. "
                    "If the change is intended, rerun with --write-lock and review the diff.")

    setup = tracing.configure(server.mcp.name, identity)
    ch05.json_line(log, event="server_start", identity=identity, transport=args.transport,
                   tools={name: ch05.definition_hash(d)[:12] for name, d in definitions.items()},
                   lock=str(args.lock), service_map=str(SERVICE_MAP_PATH), tracing=setup.destination)
    if args.transport == "stdio":
        server.mcp.run("stdio")
    else:
        server.mcp.run("streamable-http", host=HOST, port=args.port)
    return 0
