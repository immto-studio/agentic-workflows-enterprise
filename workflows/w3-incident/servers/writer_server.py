"""W3's writer MCP server: the two write tools, each held for an approval, under identities of their own.

Chapter 12, W3-D4. restart_deployment patches a deployment's pod template (the restartedAt annotation);
scale_deployment patches the scale subresource. The model proposes a write with the service only; the
approval's number never appears in a tool's arguments (W3-D5). When the harness executes an approved
write it puts the number in `_meta`, the server asks the approval service whether a recorded yes covers
exactly this call in this run, marks the approval applied, and only then changes the cluster. W2's three
servers stay read-only; the writes live here.

Run:  TOOL_IDENTITY=larkspur-ops-restarter W2_TOKEN_SECRET=<32 bytes> APPROVAL_URL=http://127.0.0.1:8780 \
      APPROVAL_KEY=<key> CLUSTER_STATE_FILE=/path/cluster.json python writer_server.py --port 8774
Rewrite the lock on purpose:  python writer_server.py --write-lock
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

HERE = Path(__file__).resolve().parent
W2_SERVERS = HERE.parents[1] / "w2-ops-assistant" / "servers"
for _folder in (HERE, W2_SERVERS):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))
from mcp.server.mcpserver import Context  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from common import MembershipTable, ServiceMap, serve  # noqa: E402
from w3_server import W3Server, approval_from  # noqa: E402
from writer import Writer  # noqa: E402

APPROVAL = HERE.parent / "approval"
if str(APPROVAL) not in sys.path:
    sys.path.insert(0, str(APPROVAL))
from approval_client import ApprovalClient  # noqa: E402

SERVER_NAME = "larkspur-ops-writer"
DEFAULT_PORT = 8774
LOCK_PATH = HERE / "writer.lock.json"
# A write tool is not read-only: the annotation says so, which is what the vetting script of chapter 11
# would flag if the identity were a reader's. The approval's number makes a non-idempotent write apply once.
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)


def _writer() -> Writer:
    url = os.environ.get("APPROVAL_URL", "").strip()
    key = os.environ.get("APPROVAL_KEY", "").strip()
    state = os.environ.get("CLUSTER_STATE_FILE", "").strip()
    if not (url and key and state):
        raise RuntimeError("writer_server needs APPROVAL_URL, APPROVAL_KEY, and CLUSTER_STATE_FILE")
    return Writer(ApprovalClient(url, key), state)


def build(identity: str, log: TextIO, transport: str, table: Callable[[], MembershipTable],
          service_map: ServiceMap, secret: str) -> W3Server:
    """The two writes, each held for an approval; the result is the write's record, not a read."""
    writer = None if transport == "none" else _writer()  # --write-lock builds with no approval service
    server = W3Server(SERVER_NAME, "The incident workflow's two writes on Larkspur Mutual's production namespace, "
                                   "each taken only under an approval. Not read-only.",
                      identity, log, transport, table, service_map, secret)
    mcp = server.mcp

    @mcp.tool(description="Restart one deployment by rolling its pods, after an approval. The restart runs only "
                          "if a recorded yes covers exactly this restart in this run, and runs once. Not "
                          "read-only.", annotations=WRITE)
    def restart_deployment(service: str, ctx: Context) -> dict[str, Any]:
        approval_id = approval_from(ctx)
        return server.run_write(ctx, "restart_deployment", service,
                                lambda *, trace_id: writer.restart_deployment({"service": service}, approval_id,
                                                                              trace_id=trace_id))

    @mcp.tool(description="Scale one deployment to `replicas` (1 to 8), after an approval. The scale runs only if "
                          "a recorded yes covers exactly this scale in this run, and runs once. Not read-only.",
              annotations=WRITE)
    def scale_deployment(service: str, replicas: int, ctx: Context) -> dict[str, Any]:
        approval_id = approval_from(ctx)
        return server.run_write(ctx, "scale_deployment", service,
                                lambda *, trace_id: writer.scale_deployment({"service": service, "replicas": replicas},
                                                                            approval_id, trace_id=trace_id))

    return server


if __name__ == "__main__":
    sys.exit(serve(build, DEFAULT_PORT, LOCK_PATH))
