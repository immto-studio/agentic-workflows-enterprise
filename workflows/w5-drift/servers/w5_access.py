"""W5's token: the agent's own, from the client-credentials grant, checked on top of W1's verifier.

Chapter 14, W5-D11; chapter 4's "some workflows act for nobody". W1's access module takes an engineer's
delegated token and refuses an app-only one on purpose, because a daemon's service principal can be a
member of a group too. W5 is that daemon. Its runtime asks Entra for a token with its own client
credentials, leased from Vault, and the token names no user: `idtyp` is `app`, there is no `scp`, and the
permission is an app role in `roles`, Drift.Read, granted to the agent's service principal on W5's servers
app. The subject (`sub` and `oid`) is that service principal, the audience W5's servers app, and `azp`
W5's runtime.

`verify` calls W1's for the signature, the issuer, the audience, the expiry, and the required claims, and
takes W1's own refusal of an app-only token as the shape it wants; everything after that is W5's: the app
shape (a delegated token is refused, because W5's servers never act for a person), the role, the client,
and the subject. A refusal names the claim and never the value. `caller_from_headers` is what
common.Server calls in place of W1's; `mint_app_token` is the lab's stand-in for Entra, for the harness
and the tests.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jwt

HERE = Path(__file__).resolve().parent
W1 = HERE.parents[1] / "w1-knowledge-assistant" / "knowledge-server"
for folder in (W1, W1 / "membership"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import access  # noqa: E402  (W1's module: the signature, the issuer, the audience, the expiry)
from access import ALGORITHM, ISSUER, AccessError, Caller, MembershipTable, TokenPolicy, resolve  # noqa: E402

__all__ = ["W5_SERVERS_APP", "W5_RUNTIME", "W5_ROLE", "W5_SCOPE", "W5_AGENT_OID", "W5_AGENT_NAME", "W5_AGENT_GROUP",
           "W5_POLICY", "APP_ONLY", "verify", "caller_from_headers", "mint_app_token", "AccessError", "Caller"]

# The four servers share one app registration (one audience, one role), and only W5's runtime may ask for
# a token for it. The agent acts for nobody, so the subject is its own service principal (W5_AGENT_OID),
# the one member of catalog/membership.json. The values are synthetic.
W5_SERVERS_APP = "c4d5e6f7-a8b9-5c0d-9e1f-2a3b4c5d6e7f"
W5_RUNTIME = "d5e6f7a8-b9c0-5d1e-8f2a-3b4c5d6e7f80"
W5_ROLE = "Drift.Read"  # an app role in the `roles` claim, not a delegated scope in `scp`
W5_SCOPE = W5_ROLE  # the name step 2 used; the catalog records it as `role`
W5_AGENT_OID = "e6f7a8b9-c0d1-5e2f-9a3b-4c5d6e7f8091"  # the service principal's object id
W5_AGENT_NAME = "larkspur-w5-drift"  # its display name; a service principal has no UPN
W5_AGENT_GROUP = "w5-drift-agent"
W5_POLICY = TokenPolicy(audience=W5_SERVERS_APP, scope=W5_ROLE, clients=frozenset({W5_RUNTIME}))
APP_ONLY = "token refused: an app-only token"  # W1's words for the shape W5 wants
REQUIRED = ["exp", "iss", "aud", "oid", "sub"]


def verify(token: str, secret: str, policy: TokenPolicy = W5_POLICY) -> dict[str, Any]:
    """The claims, if this is the agent's own token for W5's servers."""
    try:
        access.verify(token, secret, policy)
    except AccessError as exc:
        if str(exc) != APP_ONLY:
            raise  # the signature, the issuer, the audience, the expiry, or a missing claim: W1's refusal stands
    else:
        raise AccessError("token refused: a delegated token; this server takes the agent's own")
    # W1 refused the shape and nothing before it: the signature and the expiry held. The rest is W5's.
    try:
        claims = jwt.decode(token, secret, algorithms=[ALGORITHM], audience=policy.audience, issuer=ISSUER,
                            options={"require": REQUIRED})
    except jwt.PyJWTError as exc:
        raise AccessError(f"token refused: {exc}") from exc
    if claims.get("idtyp") != "app" or "scp" in claims:
        raise AccessError("token refused: not an app token")
    roles = claims.get("roles")
    if not isinstance(roles, list) or policy.scope not in roles:
        raise AccessError(f"token refused: no {policy.scope} in roles")
    if claims.get("azp") not in policy.clients:
        raise AccessError("token refused: azp not on the allowlist")
    if claims.get("sub") != claims.get("oid"):
        raise AccessError("token refused: the subject is not the service principal")
    return claims


def caller_from_headers(headers: Mapping[str, str] | None, table: MembershipTable, secret: str,
                        now: datetime | None = None, policy: TokenPolicy = W5_POLICY) -> Caller:
    """The agent behind a tool call, from its own token in X-Larkspur-Actor; no token, no read. The groups
    come from W5's membership table, as W1's resolve reads them, never from the token or an argument."""
    if headers is None:
        raise AccessError("no request headers: the server takes the caller from X-Larkspur-Actor over HTTP")
    token = next((v for k, v in headers.items() if k.lower() == "x-larkspur-actor"), "")
    if token.lower().startswith("bearer "):
        token = token[7:]
    if not token:
        raise AccessError("no X-Larkspur-Actor token on the request")
    return resolve(verify(token, secret, policy), table, now or datetime.now(timezone.utc))


def mint_app_token(secret: str, oid: str = W5_AGENT_OID, *, roles: Sequence[str] = (W5_ROLE,), client: str = W5_RUNTIME,
                   audience: str = W5_SERVERS_APP, minutes: int = 60, delegated: bool = False) -> str:
    """A lab token shaped like the one Entra issues to W5's runtime through the client-credentials grant: no
    user behind it, the role in `roles`, the service principal as `sub` and `oid`. `delegated` mints the
    other shape (a user's token with the same values in `scp`) so a test can show it refused; `minutes`
    below zero mints an expired one."""
    now = int(datetime.now(timezone.utc).timestamp())
    claims: dict[str, Any] = {"iss": ISSUER, "aud": audience, "ver": "2.0", "oid": oid, "sub": oid, "azp": client,
                              "iat": now, "nbf": now + min(minutes, 0) * 60, "exp": now + minutes * 60}
    if delegated:
        claims |= {"idtyp": "user", "scp": " ".join(roles), "preferred_username": f"{W5_AGENT_NAME}@larkspur.example"}
    else:
        claims |= {"idtyp": "app", "roles": list(roles)}
    return jwt.encode(claims, secret, algorithm=ALGORITHM)
