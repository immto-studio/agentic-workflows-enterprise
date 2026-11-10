"""The sandbox's stand-in for the Teams bot: one HTTPS request to the runtime from inside the VPC.

The lab's runtime accepts an invocation only through Larkspur's interface endpoint for AgentCore
(its resource policy's aws:SourceVpce condition), so a call from a laptop is refused whatever token
it carries. This function runs in the sandbox VPC, where the endpoint's private name resolves, and
posts the request it is given: the runtime's invocation URL, the bearer token the sandbox obtained
for the bot's app, the session ID, and the body. It returns the status, the AWS headers, and the
body, and prints nothing but the status, so the token never reaches a log.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    request = urllib.request.Request(
        event["url"], method="POST", data=json.dumps(event.get("body") or {}).encode("utf-8"),
        headers={"Authorization": f"Bearer {event['token']}", "Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": event["session_id"]})
    try:
        with urllib.request.urlopen(request, timeout=float(event.get("timeout_s", 100))) as reply:
            status, headers, body = reply.status, dict(reply.headers.items()), reply.read()
    except urllib.error.HTTPError as exc:
        status, headers, body = exc.code, dict(exc.headers.items()), exc.read()
    except Exception as exc:  # no route, no DNS, a timeout: the reason is the finding
        print(json.dumps({"event": "invocation_failed", "error": f"{type(exc).__name__}: {exc}"[:300]}))
        return {"status": None, "error": f"{type(exc).__name__}: {exc}"[:300]}
    print(json.dumps({"event": "invocation", "status": status, "bytes": len(body)}))
    kept = {k: v for k, v in headers.items() if k.lower().startswith(("x-amzn", "content-type", "baggage"))}
    return {"status": status, "headers": kept, "body": body.decode("utf-8", "replace")[:6000]}
