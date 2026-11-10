"""W3's MCP server base: W2's server with a write path and W3's own token policy.

Chapter 12, W3-D4. W3's writes and its ServiceNow reads run on servers of their own, under W3's runtime
and W3's servers' app, so W2's three servers stay read-only in every annotation and every identity. The
caller check, the service-map visibility rule, the one log line, and the span are W2's (common.Server);
`run_write` adds what a write needs that a read does not: the trace identifier and the approval number
reach the write function, the result is the write's record and is not redacted, and an approval that
does not cover the call, or that could not be checked, becomes a refusal the harness can read.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
W2_SERVERS = HERE.parents[1] / "w2-ops-assistant" / "servers"
for folder in (HERE, W2_SERVERS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from mcp.server.mcpserver import Context  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

import common  # noqa: E402
from common import REFUSAL, Server, W3_RUNTIME  # noqa: E402
from common import ch05, tracing  # noqa: E402
from access import TokenPolicy  # noqa: E402
from writer import ApprovalNotCovered, ApprovalUnchecked  # noqa: E402

# W3's servers share one app registration and one delegated scope, with W3's runtime the only client. The
# values are synthetic, like W1's and W2's.
W3_SERVERS_APP = "e1f2a3b4-c5d6-5e7f-8a9b-0c1d2e3f4a5b"
W3_SCOPE = "Incident.Act"
W3_POLICY = TokenPolicy(audience=W3_SERVERS_APP, scope=W3_SCOPE, clients=frozenset({W3_RUNTIME}))

WRITE_NOT_COVERED = "the approval does not cover this call, so the step was not taken"
WRITE_NOT_CHECKED = "the approval service could not be asked, so the step was not taken"
APPROVAL_META_KEY = "approval_id"  # the harness puts the approval's number in _meta, never in the model's arguments


def approval_from(ctx: Context) -> str:
    """The approval's number from request `_meta`; a write tool runs only when the harness set it."""
    meta = ctx.request_context.meta or {}
    value = getattr(meta, APPROVAL_META_KEY, None)
    if value is None and isinstance(meta, dict):
        value = meta.get(APPROVAL_META_KEY)
    if not (isinstance(value, str) and value.strip()):
        raise ToolError(WRITE_NOT_COVERED)
    return value.strip()


class W3Server(Server):
    """A W2 server with W3's token policy by default and a write path."""

    def __init__(self, name: str, instructions: str, identity: str, log, transport,
                 table: Callable[[], Any], service_map, secret: str) -> None:
        super().__init__(name, instructions, identity, log, transport, table, service_map, secret, policy=W3_POLICY)

    def run_write(self, ctx: Context, tool: str, service: str, fn: Callable[..., Any]) -> Any:
        """A write: the caller check and the service-map rule, then `fn(trace_id=...)`, then one log line. The
        result is the write's record and is not redacted. An approval that does not cover the call is a refusal,
        and so is one the approval service could not be asked about."""
        trace_id, source = ch05.trace_id_from(ctx)
        caller = self.caller(ctx, trace_id, tool)
        entry: dict[str, Any] = {"event": "tool_call", "trace_id": trace_id, "trace_source": source, "tool": tool,
                                 "service": service, "identity": self.identity, "caller": caller.oid,
                                 "transport": self.transport}
        attributes = {tracing.GEN_AI_OPERATION_NAME: tracing.OP_EXECUTE_TOOL, tracing.GEN_AI_TOOL_NAME: tool,
                      tracing.LARKSPUR_COMPONENT: "mcp-server", tracing.LARKSPUR_IDENTITY: self.identity,
                      tracing.LARKSPUR_CALLER_IDENTITY: caller.oid, tracing.LARKSPUR_TRACE_ID: trace_id}
        with tracing.start_span(f"{tracing.OP_EXECUTE_TOOL} {tool}", attributes=attributes) as span:
            if service not in self.service_map.visible(caller.groups):
                span.set_attribute(tracing.LARKSPUR_REFUSED, True)
                ch05.json_line(self.log, **entry, ok=False, refused="service not visible")
                raise ToolError(REFUSAL)
            try:
                result = fn(trace_id=trace_id)
            except ApprovalNotCovered as exc:
                span.set_attribute(tracing.LARKSPUR_REFUSED, True)
                ch05.json_line(self.log, **entry, ok=False, refused=f"approval not covered: {exc}")
                raise ToolError(WRITE_NOT_COVERED) from exc
            except ApprovalUnchecked as exc:
                span.set_attribute(tracing.LARKSPUR_REFUSED, True)
                ch05.json_line(self.log, **entry, ok=False, refused=f"approval not checked: {exc}")
                raise ToolError(WRITE_NOT_CHECKED) from exc
            except common.ch05.UnknownService as exc:
                span.set_attribute(tracing.ERROR_TYPE, type(exc).__name__)
                ch05.json_line(self.log, **entry, ok=False, error=str(exc))
                raise ToolError(str(exc)) from exc
            except ValueError as exc:
                span.set_attribute(tracing.ERROR_TYPE, type(exc).__name__)
                ch05.json_line(self.log, **entry, ok=False, error=common.BAD_ARGUMENT + str(exc))
                raise ToolError(common.BAD_ARGUMENT + str(exc)) from exc
        ch05.json_line(self.log, **entry, ok=True)
        return result
