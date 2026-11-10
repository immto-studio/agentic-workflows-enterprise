"""The sandbox's Entra calls: Microsoft Graph with the author's Azure CLI session, and a client
credentials token for an app that holds a certificate (the bot, in `invoke.py`).

The sandbox registers no app; the four registrations are the author's (book #69), made from a
browser sign-in, and this module only adds a certificate to one, reads it back, and deletes them at
the end. The Graph token comes from `az account get-access-token`, from the profile AZURE_CONFIG_DIR
names (the author's), and lives in memory for the call. Nothing here prints a token or a key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
import uuid
from typing import Any

import httpx

AZ = os.environ.get("AZ_CMD", r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd")
GRAPH = "https://graph.microsoft.com/v1.0"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def graph_token() -> str:
    run = subprocess.run([AZ, "account", "get-access-token", "--resource-type", "ms-graph",
                          "--query", "accessToken", "-o", "tsv"], capture_output=True, text=True, check=True)
    return run.stdout.strip()


def graph(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """One Graph call as the author; a non-2xx answer is raised with Graph's error text."""
    reply = httpx.request(method, GRAPH + path, json=body, timeout=30.0,
                          headers={"Authorization": f"Bearer {graph_token()}", "Content-Type": "application/json"})
    if reply.status_code >= 300:
        raise RuntimeError(f"Graph {method} {path}: {reply.status_code} {reply.text[:300]}")
    return reply.json() if reply.content else {}


def set_certificate(app_object_id: str, cert_der: bytes, display_name: str) -> dict[str, Any]:
    """Make the certificate the app's one key credential (replaces the list), and read it back."""
    graph("PATCH", f"/applications/{app_object_id}", {"keyCredentials": [
        {"type": "AsymmetricX509Cert", "usage": "Verify", "key": base64.b64encode(cert_der).decode("ascii"),
         "displayName": display_name}]})
    app = graph("GET", f"/applications/{app_object_id}?$select=id,appId,displayName,keyCredentials")
    return {"app": app.get("displayName"), "keys": [{k: c.get(k) for k in ("displayName", "type", "usage", "endDateTime")}
                                                    for c in app.get("keyCredentials", [])]}


def delete_application(app_object_id: str) -> None:
    graph("DELETE", f"/applications/{app_object_id}")


def thumbprints(cert_der: bytes) -> dict[str, str]:
    """x5t (SHA-1) and x5t#S256, base64url, as JWT headers name them."""
    return {"x5t": b64url(hashlib.sha1(cert_der).digest()), "x5t#S256": b64url(hashlib.sha256(cert_der).digest())}


def client_assertion(tenant: str, client_id: str, cert_der: bytes, private_key: Any) -> str:
    """A private-key JWT for the token endpoint, signed with the app's certificate key (RS256)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", **thumbprints(cert_der)}
    claims = {"aud": f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", "iss": client_id,
              "sub": client_id, "jti": str(uuid.uuid4()), "nbf": now - 60, "exp": now + 600}
    signing_input = ".".join(b64url(json.dumps(part, separators=(",", ":")).encode("utf-8")) for part in (header, claims))
    signature = private_key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return signing_input + "." + b64url(signature)


def token_for(tenant: str, client_id: str, scope: str, cert_der: bytes, private_key: Any,
              attempts: int = 6) -> dict[str, Any]:
    """Client credentials with the certificate; retried while Entra propagates a new credential."""
    url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    last = ""
    for attempt in range(attempts):
        reply = httpx.post(url, timeout=30.0, data={
            "grant_type": "client_credentials", "client_id": client_id, "scope": scope,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": client_assertion(tenant, client_id, cert_der, private_key)})
        if reply.status_code == 200:
            return reply.json()
        last = reply.text[:300]
        if "AADSTS700027" not in last and "AADSTS7000215" not in last and attempt > 1:
            break
        time.sleep(10)
    raise RuntimeError(f"no token for {client_id}: {last}")


def claims_of(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
