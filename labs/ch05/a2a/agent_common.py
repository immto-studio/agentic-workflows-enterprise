"""What the two A2A agents share: the identity rule, the tokens, the metadata keys, the log format.

Chapter 5, part 2. Deliberately small. Each agent is its own process with its own identity;
this module only makes sure they spell the same things the same way.

Authentication. A2A puts identity at the HTTP layer: the analyst's card declares a bearer scheme,
and every request but the card needs `Authorization: Bearer <token>`. In the lab the analyst
knows its callers from `ANALYST_CALLER_TOKENS` (`subject=token`, comma-separated) and a caller
sends its own `AGENT_TOKEN`. That is a stand-in: in production the token is a short-lived JWT from
the identity provider, and the analyst checks its signature, issuer, audience and expiry instead
of looking it up. The rest of the flow, and what gets logged, does not change.
"""

from __future__ import annotations

import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

LAB = Path(__file__).resolve().parent.parent
for folder in ("harness", "tracing"):
    if str(LAB / folder) not in sys.path:
        sys.path.insert(0, str(LAB / folder))

IDENTITY_ENV = "AGENT_IDENTITY"
LOG_FILE_ENV = "AGENT_LOG_FILE"
TOKEN_ENV = "AGENT_TOKEN"                 # a caller's own bearer token
CALLER_TOKENS_ENV = "ANALYST_CALLER_TOKENS"  # the analyst's callers: subject=token[,subject=token]
BEARER_SCHEME = "larkspur-bearer"         # the scheme's name in the analyst's card
MIN_TOKEN_LENGTH = 16

# Request metadata keys. `trace_id` is the join key for every log in the lab. `traceparent` is
# also sent as the W3C HTTP header, which A2A asks for; the copy in the metadata is a workaround,
# because the A2A Python SDK 1.3.0 does not read the header into its own server spans.
# `agent_identity` is what the caller says it is; the analyst trusts the token, not this field.
TRACE_ID_KEY = "trace_id"
TRACEPARENT_KEY = "traceparent"
CALLER_IDENTITY_KEY = "agent_identity"


def refuse(message: str) -> None:
    """Refuse to start: say why on stderr and exit with status 2 (same as the MCP server)."""
    print(f"refusing to start: {message}", file=sys.stderr)
    raise SystemExit(2)


def require_agent_identity(environ: dict[str, str] | os._Environ[str] = os.environ) -> str:
    """The identity this agent runs under. No identity, no process."""
    identity = environ.get(IDENTITY_ENV, "").strip()
    if not identity:
        refuse(f"{IDENTITY_ENV} is not set. An agent only runs under a named identity, "
               f"for example {IDENTITY_ENV}=larkspur-analyst.")
    if any(c.isspace() for c in identity):
        refuse(f"{IDENTITY_ENV} {identity!r} contains whitespace; use one token such as larkspur-analyst.")
    return identity


def parse_caller_tokens(value: str) -> dict[str, str]:
    """`larkspur-scribe=<token>,other=<token>` as token -> subject. Raises ValueError when malformed."""
    tokens: dict[str, str] = {}
    for item in (part.strip() for part in value.split(",")):
        if not item:
            continue
        subject, sep, token = (x.strip() for x in item.partition("="))
        if not sep or not subject or any(c.isspace() for c in subject):
            raise ValueError(f"expected subject=token, got {item.split('=')[0]!r}=...")
        if len(token) < MIN_TOKEN_LENGTH:
            raise ValueError(f"the token for {subject!r} is shorter than {MIN_TOKEN_LENGTH} characters")
        tokens[token] = subject
    if not tokens:
        raise ValueError("no caller tokens")
    return tokens


def subject_for(token: str, tokens: dict[str, str]) -> str | None:
    """The subject a token belongs to, compared in constant time, or None."""
    found = None
    for known, subject in tokens.items():
        if hmac.compare_digest(known.encode(), token.encode()):
            found = subject
    return found


def require_token(environ: dict[str, str] | os._Environ[str] = os.environ) -> str:
    """The caller's own token. No token, no request."""
    token = environ.get(TOKEN_ENV, "").strip()
    if len(token) < MIN_TOKEN_LENGTH:
        refuse(f"{TOKEN_ENV} is not set (or shorter than {MIN_TOKEN_LENGTH} characters). "
               "The analyst accepts only authenticated callers.")
    return token


def open_log(environ: dict[str, str] | os._Environ[str] = os.environ) -> TextIO:
    path = environ.get(LOG_FILE_ENV)
    if path:
        return open(path, "a", encoding="utf-8")
    return sys.stderr


def json_line(stream: TextIO, **fields: Any) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **fields}
    stream.write(json.dumps(record, default=str) + "\n")
    stream.flush()
