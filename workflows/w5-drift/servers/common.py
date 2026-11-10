"""What W5's four MCP servers share: chapter 5's lock and log, W1's caller check, and the workspace map.

Chapter 14. Each server is W2's server (workflows/w2-ops-assistant/servers/common.py) with one
difference in who is asking. W2's caller is an engineer behind an on-behalf-of token; W5's is the
agent itself, acting for nobody (chapter 4: the client-credentials grant; W5-D11). The token still
arrives in X-Larkspur-Actor and W1's access module still checks its signature and expiry, but it is
app-only (w5_access.py): no user, no `scp`, the app role Drift.Read in `roles`, its audience W5's
servers app, its client W5's runtime, and its subject the agent's service principal, which W5's own
membership table (catalog/membership.json) lists under one group, w5-drift-agent. A delegated token,
W1's shape, is refused here. The workspace map (catalog/workspace-map.yaml) says which Terraform workspaces and
which accounts that group may read. The server checks the `workspace` argument where a tool takes
one and the `account` argument otherwise, and never a bucket key, a Region, or a team: the server
derives the key and the account number from the name, as W2's derived the namespace from the service.

A refusal says the same thing whether the workspace exists or not (W1-D5's rule, kept by W2 and here):
the agent, or whatever has hijacked it, learns nothing from the wording about what it cannot read.

Two kinds of redaction. `redact` is W2's, extended by three shapes a state file is known to hold:
every string in a result loses the identifier and credential patterns. `mask_state` is W5's (W5-D4):
every attribute a `terraform show -json` state marks in `sensitive_values`, every attribute whose name
matches the secret patterns, and every attribute that holds JSON or a script (MASKED_ATTRIBUTES, by
resource type) is replaced by a marker and a keyed hash before the state leaves the reader, so two
versions can still be compared and no value reaches the model, a log, or a pull request. The hash is an
HMAC under the reader's key (W5_MASK_KEY), so a reader of the masked state cannot test guesses of a value
against its marker. `mode: data` resources are dropped on the way.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import io
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import yaml
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
LABS = W5.parents[1] / "labs"
W1 = W5.parent / "w1-knowledge-assistant"
for folder in (HERE, W1 / "knowledge-server", W1 / "knowledge-server" / "membership", LABS / "ch05" / "tracing"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import trace_setup as tracing  # noqa: E402
from access import AccessError, Caller, MembershipFile, MembershipTable, TokenPolicy  # noqa: E402
from w5_access import (W5_AGENT_GROUP, W5_AGENT_NAME, W5_AGENT_OID, W5_POLICY, W5_ROLE, W5_RUNTIME,  # noqa: E402
                       W5_SCOPE, W5_SERVERS_APP, caller_from_headers, mint_app_token)

CH05_SERVER = LABS / "ch05" / "mcp-server"
if str(CH05_SERVER) not in sys.path:  # the module imports fake_platform from its own folder
    sys.path.insert(0, str(CH05_SERVER))
_spec = importlib.util.spec_from_file_location("ch05_server", CH05_SERVER / "server.py")
ch05 = importlib.util.module_from_spec(_spec)
sys.modules["ch05_server"] = ch05
_spec.loader.exec_module(ch05)  # type: ignore[union-attr]

HOST = "127.0.0.1"  # local only, as in chapter 5
WORKSPACE_MAP_PATH = W5 / "catalog" / "workspace-map.yaml"
TABLE_PATH = W5 / "catalog" / "membership.json"
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                            open_world_hint=False)
# One sentence per kind of subject, the same for a name that does not exist and for one the agent
# may not read.
REFUSALS = {
    "workspace": "No workspace by that name is among the ones this agent may read.",
    "account": "No account by that name is among the ones this agent may read.",
}
# The mark on a tool error the model caused itself (a window out of range, an unknown version id): the
# harness hands such a result back to the model, and words every other failure itself.
BAD_ARGUMENT = "bad argument: "

# The lab's fixed night (W5-D11): 02:00 ET on 2 November 2026, which is 07:00 UTC, standard time having
# begun on 1 November. Every "last N days" window in the fakes counts back from here, so every run
# gives the same answers.
NIGHT = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc)

# What a result may not carry into the model's context (chapter 4's rule for every tool server): W2's
# patterns, the identifiers chapter 2 classes Confidential and the credential shapes a log line is
# known to hold, plus three shapes a state file or a Lambda's environment is known to hold. The
# patterns are the lab's; a production server takes them from the logging pipeline's own list.
REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bCLM-\d{4}-\d{6}\b"), "[claim redacted]"),
    (re.compile(r"\bPOL-\d{5,}\b"), "[policy redacted]"),
    (re.compile(r"\bQTE-\d{4,}\b"), "[quote redacted]"),
    (re.compile(r"\bCUS-\d{4,}\b"), "[customer redacted]"),
    (re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{16,}"), "[credential redacted]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[access key redacted]"),
    (re.compile(r"\bhvs\.[A-Za-z0-9_-]{20,}"), "[vault token redacted]"),
    (re.compile(r"\b(password|passwd|secret|token|api[_-]?key)=\S+", re.IGNORECASE), r"\1=[redacted]"),
    # W5's three: a private key block, a GitHub token, and the user:password part of a URL.
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
     "[private key redacted]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "[github token redacted]"),
    (re.compile(r"(?<=://)[^/\s:@]+:[^@\s]+(?=@)"), "[credential redacted]"),
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


# --- the state masking (W5-D4) ------------------------------------------------------------------

# An attribute whose name says it holds a secret is masked whatever the provider's schema says: the
# schema marks an RDS password sensitive and says nothing about an API key in a Lambda's environment.
# W2's name list plus the two shapes a state is known to carry.
SECRET_NAME = re.compile(r"password|passwd|secret|token|api[_-]?key|private[_-]?key|connection[_-]?string",
                         re.IGNORECASE)
# Attributes that hold JSON or a script, where a secret sits inside one string that neither the name rule nor
# W2's value patterns can see into: an ECS task definition's container definitions carry each container's
# environment as `{"name": "DB_PASSWORD", "value": "..."}`, and user data is a boot script. The 6.71.0 schema
# marks none of them sensitive, so the reader masks each one whole, by resource type and attribute name.
MASKED_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "aws_ecs_task_definition": ("container_definitions",),
    "aws_instance": ("user_data", "user_data_base64"),
    "aws_launch_template": ("user_data",),
    "aws_launch_configuration": ("user_data", "user_data_base64"),
}
MASK = "[masked hmac-sha256:{}]"
MASK_KEY_ENV = "W5_MASK_KEY"
# The key when W5_MASK_KEY is unset: fixed, so every run of the lab gives the same markers, and not a secret.
# Deployed, the key is leased from Vault like the token secret; detect/drift.py holds the same one (mask_live).
LAB_MASK_KEY = "larkspur-w5-lab-mask-key, fixed for the lab and not a secret"


def mask_key() -> bytes:
    """The masking key: W5_MASK_KEY from the environment, or the lab's fixed default."""
    return (os.environ.get(MASK_KEY_ENV, "").strip() or LAB_MASK_KEY).encode("utf-8")


def mask_value(value: Any, key: bytes | None = None) -> str:
    """The marker for one masked value: the first eight hex digits of an HMAC-SHA256 of the value under the
    reader's key, so two versions of a state can be told apart without either value leaving the reader,
    and a reader of the masked state, who lacks the key, cannot test a guessed value against the marker as
    a plain SHA-256 would let it."""
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"),
                                                          ensure_ascii=False)
    return MASK.format(hmac.new(key or mask_key(), raw.encode("utf-8"), hashlib.sha256).hexdigest()[:8])


def _mask_values(values: Any, sensitive: Any) -> Any:
    """`values` with every attribute masked that `sensitive_values` marks or whose name matches."""
    if isinstance(values, dict):
        marks = sensitive if isinstance(sensitive, dict) else {}
        out: dict[str, Any] = {}
        for key, item in values.items():
            if marks.get(key) is True or SECRET_NAME.search(key):
                out[key] = None if item is None else mask_value(item)
            else:
                out[key] = _mask_values(item, marks.get(key))
        return out
    if isinstance(values, list):
        marks = sensitive if isinstance(sensitive, list) else []
        return [_mask_values(item, marks[i] if i < len(marks) else None) for i, item in enumerate(values)]
    return values


def _mask_resource(resource: dict[str, Any]) -> dict[str, Any]:
    """One resource with its values masked: what `sensitive_values` marks, what the name rule matches, and,
    whole, every attribute MASKED_ATTRIBUTES lists for its type."""
    raw = resource.get("values") or {}
    values = _mask_values(raw, resource.get("sensitive_values", {}))
    for attribute in MASKED_ATTRIBUTES.get(resource.get("type", ""), ()):
        if raw.get(attribute) is not None:
            values[attribute] = mask_value(raw[attribute])
    return {**resource, "values": values}


def _mask_module(module: dict[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in module.items() if key not in ("resources", "child_modules")}
    out["resources"] = [
        _mask_resource(resource)
        for resource in module.get("resources", [])
        if resource.get("mode") != "data"  # a data resource is a read the configuration made, not an object
    ]
    if "child_modules" in module:
        out["child_modules"] = [_mask_module(child) for child in module["child_modules"]]
    return out


def mask_state(state: dict[str, Any]) -> dict[str, Any]:
    """A `terraform show -json` state with its secrets masked and its data resources dropped: the only
    form of a state that leaves the state reader."""
    values = state.get("values", {})
    outputs: dict[str, Any] = {}
    for name, output in values.get("outputs", {}).items():
        masked = dict(output)
        if (output.get("sensitive") or SECRET_NAME.search(name)) and output.get("value") is not None:
            masked["value"] = mask_value(output["value"])
        outputs[name] = masked
    masked_values = {key: value for key, value in values.items() if key not in ("outputs", "root_module")}
    masked_values["outputs"] = outputs
    masked_values["root_module"] = _mask_module(values.get("root_module", {}))
    return {**{key: value for key, value in state.items() if key != "values"}, "values": masked_values}


# W5's token (w5_access.py): the four servers share one app registration (one audience, one app role),
# and only W5's runtime may ask for a token for it. The agent acts for nobody, so the subject is its own
# service principal (W5_AGENT_OID), the one member of catalog/membership.json. The constants are imported
# above and re-exported here, so the readers, the harness, and the tests read them from one place.


class MissingInSource(Exception):
    """A name the map allows and the source does not hold: not the model's doing, so the read ends as
    an outage rather than as a bad argument handed back to the model."""


__all__ = ["ch05", "tracing", "READ_ONLY", "HOST", "NIGHT", "WorkspaceMap", "load_workspace_map", "Server",
           "serve", "Caller", "AccessError", "MissingInSource", "REFUSALS", "W5_POLICY", "W5_SERVERS_APP",
           "W5_RUNTIME", "W5_SCOPE", "W5_ROLE", "W5_AGENT_OID", "W5_AGENT_NAME", "W5_AGENT_GROUP", "BAD_ARGUMENT",
           "mint_app_token", "caller_from_headers", "redact", "mask_state", "mask_value", "mask_key", "SECRET_NAME",
           "MASKED_ATTRIBUTES", "MASK", "MASK_KEY_ENV", "LAB_MASK_KEY", "MembershipTable", "TABLE_PATH"]


# --- the workspace map: which teams may read which workspaces and accounts ----------------------------

@dataclass(frozen=True)
class WorkspaceMap:
    reviewed: str
    workspaces: dict[str, frozenset[str]]  # team (a group name from the membership table) -> workspaces
    accounts: dict[str, frozenset[str]]  # team -> account names

    def visible(self, groups: frozenset[str], kind: str = "workspace") -> frozenset[str]:
        """The workspaces (or accounts) the caller's groups may read."""
        table = self.workspaces if kind == "workspace" else self.accounts
        seen: set[str] = set()
        for group in groups:
            seen |= table.get(group, frozenset())
        return frozenset(seen)


def load_workspace_map(path: Path = WORKSPACE_MAP_PATH) -> WorkspaceMap:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return WorkspaceMap(reviewed=str(data["reviewed"]),
                        workspaces={team: frozenset(names) for team, names in data["teams"].items()},
                        accounts={team: frozenset(names) for team, names in data.get("accounts", {}).items()})


# --- one server, built like chapter 5's and W2's ---------------------------------------------------

class Server:
    """A W5 MCP server: a name, an identity, the tools it serves, and the caller check before each read."""

    def __init__(self, name: str, instructions: str, identity: str, log: TextIO, transport: str,
                 table: Callable[[], MembershipTable], workspace_map: WorkspaceMap, secret: str,
                 policy: TokenPolicy = W5_POLICY) -> None:
        self.mcp = MCPServer(name, instructions=instructions)
        self.identity, self.log, self.transport = identity, log, transport
        self.table, self.workspace_map, self.secret, self.policy = table, workspace_map, secret, policy
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

    def run_tool(self, ctx: Context, tool: str, args: dict[str, Any], fn: Callable[..., Any], *,
                 scoped: bool = False) -> Any:
        """The caller check, the map check, the read, one log line, one span: the shape of chapter 5's
        run_tool. With `scoped`, the read is handed the caller's visible workspaces (a listing)."""
        trace_id, source = ch05.trace_id_from(ctx)
        caller = self.caller(ctx, trace_id, tool)  # token, then table
        entry: dict[str, Any] = {
            "event": "tool_call", "trace_id": trace_id, "trace_source": source, "tool": tool, "args": args,
            "identity": self.identity, "caller": caller.oid, "transport": self.transport,
        }
        attributes = {
            tracing.GEN_AI_OPERATION_NAME: tracing.OP_EXECUTE_TOOL,
            tracing.GEN_AI_TOOL_NAME: tool,
            tracing.GEN_AI_TOOL_TYPE: tracing.TOOL_TYPE_FUNCTION,
            tracing.GEN_AI_TOOL_CALL_ARGUMENTS: tracing.tool_arguments(args),
            tracing.LARKSPUR_COMPONENT: "mcp-server",
            tracing.LARKSPUR_IDENTITY: self.identity,
            tracing.LARKSPUR_CALLER_IDENTITY: caller.oid,
            tracing.LARKSPUR_TRACE_ID: trace_id,
        }
        with tracing.start_span(f"{tracing.OP_EXECUTE_TOOL} {tool}", attributes=attributes) as span:
            subject = "workspace" if "workspace" in args else "account" if "account" in args else None
            if subject is not None and args[subject] not in self.workspace_map.visible(caller.groups, subject):
                # One sentence for a name that doesn't exist and for one the agent may not read.
                span.set_attribute(tracing.LARKSPUR_REFUSED, True)
                ch05.json_line(self.log, **entry, ok=False, refused=f"{subject} not visible")
                raise ToolError(REFUSALS[subject])
            try:
                if scoped:
                    result = fn(**args, visible=self.workspace_map.visible(caller.groups, "workspace"))
                else:
                    result = fn(**args)
                result = redact(result)  # chapter 4: redact first
            except MissingInSource as exc:
                # Visible in the map, absent from the source: not the model's doing.
                span.set_attribute(tracing.ERROR_TYPE, type(exc).__name__)
                ch05.json_line(self.log, **entry, ok=False, error=str(exc))
                raise ToolError(str(exc)) from exc
            except ValueError as exc:
                # The model's own argument: marked, and handed back to it.
                span.set_attribute(tracing.ERROR_TYPE, type(exc).__name__)
                ch05.json_line(self.log, **entry, ok=False, error=BAD_ARGUMENT + str(exc))
                raise ToolError(BAD_ARGUMENT + str(exc)) from exc
        ch05.json_line(self.log, **entry, ok=True)  # never the result
        return result


def serve(build: Callable[[str, TextIO, str, Callable[[], MembershipTable], WorkspaceMap, str], Server],
          default_port: int, lock_path: Path, argv: list[str] | None = None) -> int:
    """The chapter 5 command line: --write-lock, the lock check, the identity, then the transport."""
    parser = argparse.ArgumentParser(description=build.__doc__.split("\n")[0] if build.__doc__ else "W5 server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="streamable-http")
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--lock", type=Path, default=lock_path)
    parser.add_argument("--write-lock", action="store_true")
    args = parser.parse_args(argv)

    empty_table = MembershipTable(synced_at="1970-01-01T00:00:00Z", group_names={}, members={})
    if args.write_lock:
        server = build("lock-writer", io.StringIO(), "none", lambda: empty_table, load_workspace_map(), "x" * 32)
        definitions = ch05.advertised_definitions(server.mcp)
        ch05.write_lock(definitions, args.lock)
        print(f"wrote {args.lock} with {len(definitions)} tools")
        return 0

    identity = ch05.require_identity()
    secret = os.environ.get("W5_TOKEN_SECRET", "").strip()
    if len(secret) < 32:
        ch05.refuse("W5_TOKEN_SECRET is not set or shorter than 32 bytes.")
    table_path = Path(os.environ.get("MEMBERSHIP_TABLE", str(TABLE_PATH)))
    membership = MembershipFile(table_path)
    log = ch05.open_log()
    server = build(identity, log, args.transport, membership.current, load_workspace_map(), secret)

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
                   lock=str(args.lock), workspace_map=str(WORKSPACE_MAP_PATH), tracing=setup.destination)
    if args.transport == "stdio":
        server.mcp.run("stdio")
    else:
        server.mcp.run("streamable-http", host=HOST, port=args.port)
    return 0
