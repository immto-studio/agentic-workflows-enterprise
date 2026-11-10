"""The tool catalog and the pinned hashes of its definitions.

Each tool is bound to exactly one identity. The functions check the scope of the identity
they are handed, so a write cannot run under the reader's identity even by mistake.

PINNED is the lockfile for tool definitions: the hash of each definition the author
reviewed, including the identity the tool runs under. A catalog loaded at runtime (from an
MCP server, a registry, a config repo) is checked against it before the model sees a single
description. Re-pin after a deliberate change with:  python tools.py
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from identity import DEPLOYMENT_RESTARTER, POD_READER, Identity


def get_pod_status(identity: Identity, service: str) -> dict:
    if not identity.allows("pods:get"):
        raise PermissionError(f"{identity.name} lacks pods:get")
    return {"service": service, "ready": 2, "desired": 3}


def restart_deployment(identity: Identity, service: str) -> dict:
    if not identity.allows("deployments:restart"):
        raise PermissionError(f"{identity.name} lacks deployments:restart")
    return {"service": service, "restarted": True}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # the model reads this, so it is part of the attack surface
    args: frozenset[str]
    identity: Identity
    run: Callable[..., dict]

    def digest(self) -> str:
        # Everything the author reviewed: what the model reads (name, description, arguments)
        # and what the tool may do (the identity it runs under, its scopes, whether it needs an
        # approval). Rebinding a read tool to a write identity changes the hash as a new
        # description does. The code behind `run` is not covered; that is a supply-chain check.
        material = json.dumps({
            "name": self.name, "description": self.description, "args": sorted(self.args),
            "identity": self.identity.name, "scopes": sorted(self.identity.scopes),
            "requires_approval": self.identity.requires_approval,
        }, sort_keys=True)  # JSON, so no two different definitions encode alike
        return hashlib.sha256(material.encode()).hexdigest()


CATALOG: dict[str, Tool] = {
    "get_pod_status": Tool(
        name="get_pod_status",
        description=(
            "Return the ready and desired pod counts for one deployment in the production "
            "cluster. Read-only."
        ),
        args=frozenset({"service"}),
        identity=POD_READER,
        run=get_pod_status,
    ),
    "restart_deployment": Tool(
        name="restart_deployment",
        description=(
            "Perform a rolling restart of one deployment in the production cluster. "
            "Disruptive; requires an approved change."
        ),
        args=frozenset({"service"}),
        identity=DEPLOYMENT_RESTARTER,
        run=restart_deployment,
    ),
}

# Reviewed on 2026-10-29. If a test says these do not match, somebody changed a tool
# definition; read the diff before you re-pin.
PINNED: dict[str, str] = {
    "get_pod_status": "7a2196f8b56be639949c6814b45ea64825e86aa2e116676cbc0fd8a6774ed90b",
    "restart_deployment": "3e7eddaf7c7341a8522b8a38b8e1935fb2275fd7bcd0d625b0be2dbe38e438fb",
}


if __name__ == "__main__":
    for tool in CATALOG.values():
        print(f'    "{tool.name}": "{tool.digest()}",')
