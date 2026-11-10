"""The sandbox's MCP stand-in: one Lambda function behind an internal load balancer, answering as the
two MCP servers the tool gateway's targets name (k8s-mcp and knowledge-mcp, by the Host header).

It speaks the Streamable HTTP transport's request side: a JSON-RPC 2.0 request in a POST, a JSON
reply. `initialize` answers with the protocol version the client asked for, `tools/list` with the
catalog's tools for that server (tools.json, the definitions the image's lock was written from), and
`tools/call` with a synthetic result in the tool's output shape. Nothing here is Larkspur's server:
the bearer token the gateway presents is logged by its claims (never the token itself), not checked,
because what the sandbox tests is the gateway's side of the exchange.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

TOOLS = json.loads((Path(__file__).resolve().parent / "tools.json").read_text(encoding="utf-8"))
SERVERS = {f"{server}.sandbox.larkspur.example": names for server, names in TOOLS["servers"].items()}
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def claims_of(authorization: str) -> dict[str, Any]:
    """The bearer token's header and claims, unverified, for the log: who the gateway said it was."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token.count(".") != 2:
        return {"present": bool(token)}
    try:
        header, payload = (json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))) for part in token.split(".")[:2])
    except Exception:
        return {"present": True, "parsed": False}
    return {"present": True, "header": {k: header.get(k) for k in ("alg", "typ", "x5t", "kid")},
            "claims": {k: payload.get(k) for k in ("aud", "iss", "azp", "appid", "tid", "roles", "ver")}}


def result_for(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    service = str(arguments.get("service", "claims-api"))
    if name == "get_pod_status":
        return {"service": service, "namespace": "claims", "ready": 3, "desired": 3, "image": "claims-api:2026.11.1",
                "pods": [{"name": f"{service}-{i}", "phase": "Running", "restarts": 0} for i in ("a", "b", "c")]}
    if name == "get_recent_alerts":
        return {"service": service, "window_minutes": int(arguments.get("minutes", 60)), "count": 0, "alerts": []}
    if name == "restart_deployment":
        return {"service": service, "namespace": "claims", "restarted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if name == "search_runbooks":
        return {"query": str(arguments.get("query", "")),
                "passages": [{"runbook": "rb-claims-api-restart", "score": 0.91,
                              "text": "Synthetic passage: check the pod status, then restart the deployment once."}]}
    raise KeyError(name)


def reply(request_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    body["error" if error else "result"] = error or result
    return body


def handle(method: str, params: dict[str, Any], request_id: Any, host: str) -> dict[str, Any] | None:
    names = SERVERS.get(host.split(":", 1)[0].lower())
    if names is None:
        return reply(request_id, error={"code": -32000, "message": f"no MCP server at {host}"})
    if method == "initialize":
        asked = str(params.get("protocolVersion", ""))
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return reply(request_id, {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                                  "serverInfo": {"name": host.split(".", 1)[0], "version": "sandbox-stand-in"}})
    if method == "ping":
        return reply(request_id, {})
    if method == "tools/list":
        return reply(request_id, {"tools": [TOOLS["tools"][name] for name in names]})
    if method == "tools/call":
        name = str(params.get("name", ""))
        if name not in names:
            return reply(request_id, error={"code": -32602, "message": f"unknown tool: {name}"})
        structured = result_for(name, params.get("arguments") or {})
        return reply(request_id, {"content": [{"type": "text", "text": json.dumps(structured)}],
                                  "structuredContent": structured, "isError": False})
    if method.startswith("notifications/"):
        return None  # accepted, no body
    # A method the specification does not name (AgentCore Gateway probes with `server/discover` before
    # `initialize`): refused as the specification says, and logged with its params, so the sandbox records
    # what the gateway asked for.
    print(json.dumps({"event": "unknown_method", "host": host, "method": method, "params": json.dumps(params)[:600]}))
    return reply(request_id, error={"code": -32601, "message": f"method not found: {method}"})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    host = headers.get("host", "")
    method = event.get("httpMethod", "")
    if method != "POST":
        print(json.dumps({"event": "refused", "host": host, "http_method": method}))
        return {"statusCode": 405, "headers": {"Allow": "POST"}, "body": ""}
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return {"statusCode": 400, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(reply(None, error={"code": -32700, "message": "parse error"}))}
    rpc_method = str(message.get("method", ""))
    print(json.dumps({"event": "request", "host": host, "method": rpc_method, "path": event.get("path"),
                      "session": headers.get("mcp-session-id"), "protocol_header": headers.get("mcp-protocol-version"),
                      "token": claims_of(headers.get("authorization", "")),
                      "actor_header": "x-larkspur-actor" in headers}))
    answer = handle(rpc_method, message.get("params") or {}, message.get("id"), host)
    if answer is None:
        return {"statusCode": 202, "headers": {}, "body": ""}
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(answer)}
