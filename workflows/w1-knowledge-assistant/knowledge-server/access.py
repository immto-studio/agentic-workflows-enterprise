"""Who is asking, and which groups they hold: the delegated identity and the membership table.

Chapter 10. The knowledge server never takes groups from a tool argument or from the model. It
takes the engineer's identity from the token in X-Larkspur-Actor and the engineer's groups from
the membership table that membership/sync.py writes.

The token (W1-D19, W1-D20). In production the bot hands W1's runtime one token; inside the
runtime, AgentCore Identity's on-behalf-of exchange turns it into a token for the knowledge
server, and the tool gateway passes it through (W1-D14). Beyond its signature, issuer, audience
and expiry, the server checks three things:

- that a user is behind it. An app-only token (`idtyp` app, or no `scp` at all) is refused,
  because a daemon's service principal can be a member of a group too.
- that it carries the server's delegated scope, Knowledge.Search, in `scp`.
- that the client that asked for it (`azp`) is on the allowlist: W1's runtime.

A v2.0 Entra token names the API by its client ID, a GUID, in `aud`.

The groups (W1-D16, W1-D27). Larkspur's tokens for this server carry no groups claim, since a
header value can't exceed 4 KB, so the table decides alone. The sync rebuilds it every night and
applies Graph's delta every five minutes: a direct member removed from a tracked group stops
reading within minutes, and a change inside a nested group waits for the night. Once the table's
last rebuild is more than 36 hours old, the server grants only the broad groups, the ones nearly
everyone holds, and its audit line says "stale table". The branches for a token that does list
groups, or that carries the overage pointer instead, stay as defense in depth: a list in the token
can only narrow the table, and the pointer's URL is never called. Narrowing changes what the
server grants, never the class a conversation carries: that comes from the groups the table lists
(`Caller.held`), since a narrower grant today doesn't erase what the engineer has already read.

The server reloads the table when its file changes (MembershipFile), as it would reload a new
version of the S3 object in production.

The lab signs tokens with HS256 and a shared secret, so it needs no key infrastructure. In
production the server checks Entra's RS256 signature against the tenant's published keys, and
everything else the same way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import jwt

ISSUER = "https://login.example.invalid/larkspur/v2.0"  # stands in for Entra's v2.0 issuer
AUDIENCE = "7ce36275-ecd1-5626-b463-2d09882f9077"  # the knowledge server app's client ID
SCOPE = "Knowledge.Search"  # the delegated scope the server's app exposes
W1_RUNTIME = "7bd64bf9-ed61-5026-ba97-4c2e5c5e8e8e"  # W1's runtime app: the OBO exchange's client
CLIENTS = frozenset({W1_RUNTIME})  # the azp values the server accepts
ALGORITHM = "HS256"


@dataclass(frozen=True)
class TokenPolicy:
    """What a server's app expects of a token: its own client ID as audience, its delegated scope, and
    the runtimes allowed to ask for it. W1's values are the default; W2's servers pass their own."""
    audience: str = AUDIENCE
    scope: str = SCOPE
    clients: frozenset[str] = CLIENTS


W1_POLICY = TokenPolicy()
MAX_TABLE_AGE = timedelta(hours=36)  # a day and a half: past it, broad groups only
CLOCK_SKEW = timedelta(minutes=5)  # a table stamped further ahead than this has no known age


class AccessError(Exception):
    """The request has no identity the server can accept."""


@dataclass(frozen=True)
class Caller:
    oid: str
    upn: str
    groups: frozenset[str]  # what the server grants now, as the wiki's access metadata names groups
    source: str  # "table", or "stale table"; "and token" or "(overage)" when the token says more
    # The groups the table lists for the caller, before a stale table or a token narrows them. A
    # narrower grant today doesn't erase what the engineer has read, so the class of what they may
    # type into a question comes from these (caller_class).
    held: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MembershipTable:
    synced_at: str  # the last nightly rebuild, ISO 8601 in UTC
    group_names: Mapping[str, str]  # group object ID -> the name in the reviewed map
    members: Mapping[str, frozenset[str]]  # user object ID -> group names
    broad: frozenset[str] = frozenset()  # what a stale table still grants
    delta_applied_at: str | None = None  # the last five-minute delta

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MembershipTable":
        """The table as the sync writes it (membership/sync.py)."""
        return cls(synced_at=data["synced_at"], group_names=dict(data["groups"]),
                   members={oid: frozenset(names) for oid, names in data["members"].items()},
                   broad=frozenset(data.get("broad", ())), delta_applied_at=data.get("delta_applied_at"))

    @classmethod
    def load(cls, path: Path) -> "MembershipTable":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def stale(self, now: datetime) -> bool:
        """Older than a day and a half, or of no known age, which includes a time in the future."""
        try:
            synced = datetime.fromisoformat(self.synced_at)
        except ValueError:
            return True
        if synced.tzinfo is None:
            synced = synced.replace(tzinfo=timezone.utc)
        return not -CLOCK_SKEW <= now - synced <= MAX_TABLE_AGE


class MembershipFile:
    """The table as the server sees it: read again whenever the file changes (W1-D27)."""

    def __init__(self, path: Path):
        self.path = path
        self._seen: tuple[int, int] | None = None
        self._table: MembershipTable | None = None

    def current(self) -> MembershipTable:
        try:
            stat = self.path.stat()
            seen = (stat.st_mtime_ns, stat.st_size)
            if seen != self._seen:
                self._table, self._seen = MembershipTable.load(self.path), seen
        except Exception:
            if self._table is None:
                raise
            # A missing or unreadable file keeps the last good table, which then ages; the next
            # call reads the file again.
        return self._table


def verify(token: str, secret: str,
           policy: TokenPolicy = W1_POLICY) -> dict[str, Any]:
    """The claims, if this is a user's token for this server."""
    try:
        claims = jwt.decode(
            token, secret, algorithms=[ALGORITHM],
            audience=policy.audience, issuer=ISSUER,
            options={"require": ["exp", "iss", "aud", "oid"]})
    except jwt.PyJWTError as exc:
        raise AccessError(f"token refused: {exc}") from exc
    if claims.get("idtyp") == "app" or "scp" not in claims:
        raise AccessError("token refused: an app-only token")
    if policy.scope not in str(claims["scp"]).split():
        raise AccessError(f"token refused: no {policy.scope} scope")
    if claims.get("azp") not in policy.clients:
        raise AccessError("token refused: azp not on the allowlist")
    return claims


def resolve(claims: Mapping[str, Any], table: MembershipTable,
            now: datetime) -> Caller:
    """The table's groups, only the broad ones from a stale table;
    a token that lists groups can only narrow them."""
    oid = str(claims["oid"])
    upn = str(claims.get("preferred_username")
              or claims.get("upn") or "")
    held = table.members.get(oid, frozenset())
    groups, source = held, "table"
    if table.stale(now):  # W1-D27
        groups, source = held & table.broad, "stale table"
    listed = claims.get("groups")
    overage = claims.get("_claim_names") or {}
    if isinstance(listed, list):  # not on Larkspur's tokens
        named = {table.group_names[g] for g in listed
                 if g in table.group_names}  # IDs to names
        groups, source = groups & named, f"{source} and token"
    elif "groups" in overage or claims.get("hasgroups"):
        source = f"{source} (overage)"
    return Caller(oid, upn, groups, source, held)


def caller_from_headers(headers: Mapping[str, str] | None, table: MembershipTable, secret: str,
                        now: datetime | None = None, policy: TokenPolicy = W1_POLICY) -> Caller:
    """The engineer behind a tool call, from the forwarded token; no token, no search."""
    if headers is None:
        raise AccessError("no request headers: the server takes the caller from X-Larkspur-Actor over HTTP")
    token = next((v for k, v in headers.items() if k.lower() == "x-larkspur-actor"), "")
    if token.lower().startswith("bearer "):
        token = token[7:]
    if not token:
        raise AccessError("no X-Larkspur-Actor token on the request")
    return resolve(verify(token, secret, policy), table, now or datetime.now(timezone.utc))


def issue(secret: str, oid: str, upn: str, groups: list[str] | None = None, overage: bool = False,
          minutes: int = 60, scope: str = SCOPE, client: str = W1_RUNTIME, audience: str = AUDIENCE) -> str:
    """A lab token, shaped like the one Entra's on-behalf-of exchange issues to W1's runtime for the server."""
    now = int(datetime.now(timezone.utc).timestamp())
    claims: dict[str, Any] = {"iss": ISSUER, "aud": audience, "ver": "2.0", "oid": oid,
                              "preferred_username": upn, "scp": scope, "azp": client, "idtyp": "user",
                              "iat": now, "nbf": now, "exp": now + minutes * 60}
    if overage:  # the documented shape; the URL is legacy Azure AD Graph, and nothing here calls it
        claims["_claim_names"] = {"groups": "src1"}
        claims["_claim_sources"] = {"src1": {"endpoint": f"https://graph.windows.net/{{tenant}}/users/{oid}/getMemberObjects"}}
    elif groups is not None:
        claims["groups"] = groups
    return jwt.encode(claims, secret, algorithm=ALGORITHM)
