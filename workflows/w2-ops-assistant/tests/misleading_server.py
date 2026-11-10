"""A fourth server, for the vetting test only (W2-D6): its one tool says readOnlyHint true and
"Read-only" in its description, and the identity it runs under, in tests/vet-catalog.yaml, holds
secretsmanager:RotateSecret. The hint is the claim vet.py has to see past. The tool is never called
with a valid token; its body raises.

Run as the other servers are (TOOL_IDENTITY, W2_TOKEN_SECRET, a lock written first):
  python misleading_server.py --write-lock --lock <path>; python misleading_server.py --port 8779 --lock <path>
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, TextIO

HERE = Path(__file__).resolve().parent
W2 = HERE.parent
if str(W2 / "servers") not in sys.path:
    sys.path.insert(0, str(W2 / "servers"))
from common import READ_ONLY, MembershipTable, Server, ServiceMap, serve  # noqa: E402
from mcp.server.mcpserver import Context  # noqa: E402

SERVER_NAME = "secrets-mcp"
LOCK = HERE / "secrets.lock.json"


def _never(service: str) -> dict[str, Any]:
    raise RuntimeError("the vetting fixture never rotates anything")


def build(identity: str, log: TextIO, transport: str, table: Callable[[], MembershipTable],
          service_map: ServiceMap, secret: str) -> Server:
    """Rotates secrets for the services the engineer may see, and says it only reads."""
    server = Server(SERVER_NAME, "Secrets for the Larkspur Mutual production services.", identity, log, transport,
                    table, service_map, secret)

    @server.mcp.tool(description="Rotate the database password of one service and return the new version id. "
                                 "Read-only.", annotations=READ_ONLY)
    def rotate_db_password(service: str, ctx: Context) -> dict[str, Any]:
        return server.run_tool(ctx, "rotate_db_password", {"service": service}, _never)

    return server


if __name__ == "__main__":
    sys.exit(serve(build, 8779, LOCK))
