"""vet.py: what a reviewer looks at before a Larkspur workflow may call an MCP server (W2-D6).

Reads a server's tools/list and prints, for each tool, the description, the input and output schemas,
the annotations with the specification's defaults filled in where the server left one out, the hash
pinned in the lock beside the hash of what the server serves now, and what the server's identity may
do, from the catalog. Before that it prints the server's name and version, the negotiated protocol
version, its declared capabilities, its instructions, and the transport; with --probe-auth it also
makes one call that carries no actor token and reports what the server answered.

The hints are the server's claims about itself. The 2026-07-28 schema says of ToolAnnotations that
"all properties ... are hints. They are not guaranteed to provide a faithful description of tool
behavior", and the tools page says clients "MUST consider tool annotations to be untrusted unless they
come from trusted servers" (LINKS.md, chapter 11, sections A.1 and A.2). What decides whether a
tool can write is the identity the server runs under, so the report puts the identity's actions
beside every readOnlyHint and flags the ones that disagree. No third-party server runs in the lab;
the lab vets its own three with this script, and a fourth, test-only server carries a misleading
hint for the test to catch (tests/misleading_server.py).

Usage, from workflows/w2-ops-assistant, with the server up:
  python vet.py http://127.0.0.1:8771/mcp --server kubernetes-mcp
  python vet.py <url> --server <name> [--catalog catalog/tools.yaml] [--lock servers/<name>.lock.json]
                [--token <jwt>] [--probe-auth] [--json]
Exit status 1 when a served definition doesn't match the lock, a tool is missing from the lock or the
catalog, the catalog's arguments differ from the schema's, or a read-only hint sits on an identity
that can write; 0 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
W1 = HERE.parent / "w1-knowledge-assistant"
for folder in (HERE / "servers", W1 / "knowledge-server"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
from actor_transport import ActorMCP  # noqa: E402
from common import ch05  # noqa: E402
from mcp import Client  # noqa: E402

CATALOG_PATH = HERE / "catalog" / "tools.yaml"
LOCK_DIR = HERE / "servers"

# The schema's defaults (A.1), filled in when a server leaves a hint out: a tool with no annotations
# is, by the specification's own defaults, a writing, destructive, open-world tool.
HINT_DEFAULTS = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}

# An AWS action is a read when its verb is one of these; anything else counts as able to write.
# The Service Authorization Reference's access levels would settle it per action (fact sheet, F);
# until they are read, the verb is the rule, with one exception below.
READ_VERBS = ("Get", "List", "Describe", "Filter", "Search", "Lookup", "Query", "Head", "View", "BatchGet")
# Reads whose result is a credential: chapter 4's never-list calls reading a secret a write, so the
# vetting rule does too, whatever the verb says.
SENSITIVE_READS = ("secretsmanager:GetSecretValue", "ssm:GetParameter", "kms:Decrypt", "sts:GetSessionToken",
                   "sts:GetFederationToken")
# A Google or Azure role, or an EKS access policy, reads when its name says so.
READ_ROLE_WORDS = ("viewer", "reader", "view")


def is_read_action(action: str) -> bool:
    if action.startswith(SENSITIVE_READS):
        return False
    verb = action.split(":", 1)[-1]
    return verb.startswith(READ_VERBS)


def is_read_role(name: str) -> bool:
    return any(word in name.lower() for word in READ_ROLE_WORDS)


def identity_scope(entry: dict[str, Any]) -> dict[str, Any]:
    """The identity's grants from a catalog server entry, each marked read or write."""
    grants: list[dict[str, Any]] = []
    aws = entry.get("aws", {})
    for action in aws.get("role_actions", []):
        grants.append({"platform": "aws", "grant": action, "read": is_read_action(action)})
    if "eks_access" in aws:
        policy = aws["eks_access"].get("policy", "")
        grants.append({"platform": "aws", "grant": f"eks access policy {policy}", "read": is_read_role(policy),
                       "namespaces": aws["eks_access"].get("namespaces")})
    google = entry.get("google", {})
    if "role" in google:
        grants.append({"platform": "google", "grant": google["role"], "read": is_read_role(google["role"])})
    if "cluster_rbac" in google:
        grants.append({"platform": "google", "grant": f"cluster role {google['cluster_rbac']}",
                       "read": is_read_role(str(google["cluster_rbac"]))})
    azure = entry.get("azure", {})
    if "role" in azure:
        grants.append({"platform": "azure", "grant": azure["role"], "read": is_read_role(azure["role"])})
    writes = [g["grant"] for g in grants if not g["read"]]
    return {"identity": entry.get("identity"), "grants": grants, "writes": writes, "read_only": not writes}


def hints_of(definition: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each hint with its value and whether the server stated it or the default applies."""
    stated = definition.get("annotations") or {}
    out = {}
    for name, default in HINT_DEFAULTS.items():
        if name in stated and stated[name] is not None:
            out[name] = {"value": bool(stated[name]), "source": "stated"}
        else:
            out[name] = {"value": default, "source": "default"}
    return out


def schema_summary(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if not schema:
        return None
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    return {name: {"type": spec.get("type", spec.get("anyOf", "?")), "required": name in required}
            for name, spec in props.items()}


def probe_arguments(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Arguments of the right shape and no meaning, for the one call --probe-auth makes."""
    args: dict[str, Any] = {}
    for name, spec in ((schema or {}).get("properties") or {}).items():
        kind = spec.get("type")
        args[name] = {"integer": 1, "number": 1, "boolean": False, "array": [], "object": {}}.get(kind, "vet-probe")
    return args


def review_tool(tool: Any, lock: dict[str, str], catalog_tools: dict[str, Any], server: str,
                scope: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    definition = ch05.canonical_definition(tool)
    name = definition["name"]
    served = ch05.definition_hash(definition)
    pinned = lock.get(name)
    findings = []
    if pinned is None:
        lock_state = "not pinned"
        findings.append(f"{name}: not in the lock")
    elif pinned == served:
        lock_state = "matches"
    else:
        lock_state = "MISMATCH"
        findings.append(f"{name}: served definition {served[:12]} differs from the lock's {pinned[:12]}")
    entry = catalog_tools.get(name)
    schema_args = sorted((definition.get("inputSchema") or {}).get("properties") or {})
    catalog_state: dict[str, Any] = {"listed": entry is not None}
    if entry is None:
        findings.append(f"{name}: not in the catalog")
    else:
        catalog_state["server"] = entry.get("server")
        catalog_state["args"] = entry.get("args")
        catalog_state["reads"] = entry.get("reads")
        if entry.get("server") != server:
            findings.append(f"{name}: the catalog puts it on {entry.get('server')}, not {server}")
        if sorted(entry.get("args", [])) != schema_args:
            findings.append(f"{name}: the catalog's arguments {sorted(entry.get('args', []))} differ from the "
                            f"schema's {schema_args}")
    hints = hints_of(definition)
    if hints["readOnlyHint"]["value"] and scope["writes"]:
        findings.append(f"{name}: readOnlyHint is true, and the identity {scope['identity']} holds "
                        f"{', '.join(scope['writes'])}: the hint is not what decides")
    report = {
        "name": name,
        "title": definition.get("title"),
        "description": definition.get("description"),
        "input": schema_summary(definition.get("inputSchema")),
        "output": schema_summary(definition.get("outputSchema")),
        "annotations": hints,
        "lock": {"state": lock_state, "pinned": pinned, "served": served},
        "catalog": catalog_state,
    }
    return report, findings


async def inspect(url: str, server: str, catalog_path: Path, lock_path: Path | None, token: str | None,
                  probe_auth: bool) -> dict[str, Any]:
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    entry = catalog.get("servers", {}).get(server)
    scope = identity_scope(entry) if entry else {"identity": None, "grants": [], "writes": [], "read_only": None}
    findings: list[str] = []
    if entry is None:
        findings.append(f"server {server} is not in the catalog")
    lock = ch05.read_lock(lock_path) if lock_path and lock_path.exists() else {}
    if lock_path and not lock_path.exists():
        findings.append(f"no lock at {lock_path}")
    transport = "streamable-http" if url.startswith(("http://", "https://")) else "stdio"
    async with Client(ActorMCP(url, token) if token else url) as client:
        info = client.server_info
        capabilities = client.server_capabilities.model_dump(by_alias=True, exclude_none=True)
        protocol_version, instructions = client.protocol_version, client.instructions
        listing = (await client.list_tools()).tools
        tools = []
        for tool in listing:
            report, more = review_tool(tool, lock, catalog.get("tools", {}), server, scope)
            tools.append(report)
            findings.extend(more)
        for pinned_name in lock:
            if pinned_name not in {t["name"] for t in tools}:
                findings.append(f"{pinned_name}: in the lock, not served")
        auth: dict[str, Any]
        if token:
            auth = {"probed": False, "note": "a token was given; the probe would be a real read, so it was skipped"}
        elif probe_auth and listing:
            first = listing[0]
            result = await client.call_tool(first.name, probe_arguments(ch05.canonical_definition(first).get("inputSchema")))
            text = " ".join(getattr(c, "text", "") for c in result.content)[:300]
            auth = {"probed": True, "tool": first.name, "refused": bool(result.is_error), "text": text}
            if not result.is_error:
                findings.append(f"{first.name}: answered a call that carried no actor token")
        else:
            auth = {"probed": False, "note": "pass --probe-auth to make one call without an actor token"}
    return {
        "url": url,
        "server": server,
        "server_info": info.model_dump(by_alias=True, exclude_none=True) if info else None,
        "protocol_version": protocol_version,
        "capabilities": capabilities,
        "instructions": instructions,
        "transport": transport,
        "authentication": auth,
        "identity": scope,
        "tools": tools,
        "findings": findings,
    }


def render(report: dict[str, Any]) -> str:
    lines = [f"server {report['server']} at {report['url']}"]
    info = report["server_info"] or {}
    lines.append(f"  name/version: {info.get('name', '?')} {info.get('version', '')}".rstrip())
    lines.append(f"  protocol: {report['protocol_version']}   transport: {report['transport']}")
    lines.append(f"  capabilities: {', '.join(sorted(report['capabilities'])) or 'none declared'}")
    if report["instructions"]:
        lines.append(f"  instructions: {report['instructions']}")
    auth = report["authentication"]
    if auth["probed"]:
        verdict = "refused" if auth["refused"] else "ANSWERED"
        lines.append(f"  authentication: a call to {auth['tool']} without an actor token was {verdict}: {auth['text']}")
    else:
        lines.append(f"  authentication: {auth['note']}")
    scope = report["identity"]
    lines.append(f"  identity: {scope['identity'] or 'not in the catalog'}")
    for grant in scope["grants"]:
        extra = f" (namespaces {', '.join(grant['namespaces'])})" if grant.get("namespaces") else ""
        lines.append(f"    {grant['platform']:6s} {grant['grant']}{extra}: {'read' if grant['read'] else 'WRITE'}")
    for tool in report["tools"]:
        lines.append("")
        lines.append(f"tool {tool['name']}" + (f" ({tool['title']})" if tool.get("title") else ""))
        lines.append(f"  description: {tool['description']}")
        lines.append(f"  input: {json.dumps(tool['input'])}")
        lines.append(f"  output: {'none' if tool['output'] is None else json.dumps(tool['output'])}")
        hints = "  ".join(f"{k}={v['value']}{'' if v['source'] == 'stated' else ' (default)'}"
                          for k, v in tool["annotations"].items())
        lines.append(f"  annotations: {hints}")
        lock = tool["lock"]
        pinned = (lock["pinned"] or "")[:12] or "none"
        lines.append(f"  lock: {lock['state']}  pinned {pinned}  served {lock['served'][:12]}")
        cat = tool["catalog"]
        if cat["listed"]:
            lines.append(f"  catalog: {cat['server']}, args {cat['args']}; reads {cat['reads']}")
        else:
            lines.append("  catalog: not listed")
    lines.append("")
    if report["findings"]:
        lines.append("findings:")
        lines.extend(f"  - {f}" for f in report["findings"])
    else:
        lines.append("findings: none")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url", help="the server's MCP endpoint, http(s)://host:port/mcp")
    parser.add_argument("--server", required=True, help="the server's name in the catalog, such as kubernetes-mcp")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--lock", type=Path, help="the server's lock file (default: servers/<name>.lock.json)")
    parser.add_argument("--token", help="an actor token; with one, the authentication probe is skipped")
    parser.add_argument("--probe-auth", action="store_true", help="make one call without an actor token and report it")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    lock = args.lock or LOCK_DIR / f"{args.server.removesuffix('-mcp')}.lock.json"
    report = asyncio.run(inspect(args.url, args.server, args.catalog, lock, args.token, args.probe_auth))
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
