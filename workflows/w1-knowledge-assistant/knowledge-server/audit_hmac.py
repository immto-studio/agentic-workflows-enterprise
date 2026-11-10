"""The HMAC a tool server's audit line carries in place of a piece of text.

Chapter 17's rule for every tool server's audit line (companion #126): a value from a fixed set, a
number, or a system's identifier is kept as it is, and text, anything a person's name could be in,
a page's title included, is kept only as an HMAC under a key the log archive account holds. The text
itself stays in the harness's log for the run, where one person's entries can be found and deleted.
An auditor who holds the key matches the two by computing the HMAC of the text in the harness's log,
and once that log is erased, the line keeps a hash that nobody without the key can turn back into
a name.

`text_hmac` is HMAC-SHA256 of the text's UTF-8 bytes, written as `hmac-sha256:` and the full hex
digest. An auditor matches on it, so it is never cut short the way W5's state masks are
(workflows/w5-drift/servers/common.py keeps eight hex digits, enough to tell two versions apart).

The key is the UTF-8 bytes of AUDIT_HMAC_KEY, at least 32 of them, since RFC 2104 discourages a key
shorter than the hash's output. When the variable is unset, the process makes a random key of its
own the first time a line needs one and says so once on stderr: its lines can't be matched once it
exits, and no key written in code stands in. W1's knowledge server and W2's servers, which W3 runs
as well, check a key that is set when they start (check_audit_key) and refuse a short one, so a
server that never writes text, such as W2's Kubernetes reader, never warns.

W2's and W5's servers already import W1's access.py from this folder; this module sits beside it
for the same reason.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
from collections.abc import Mapping
from typing import TextIO

KEY_ENV = "AUDIT_HMAC_KEY"
PREFIX = "hmac-sha256:"
MIN_KEY_BYTES = 32  # SHA-256's output length

_process_key: bytes | None = None  # the random key, made once, when AUDIT_HMAC_KEY is unset


class AuditKeyError(ValueError):
    """AUDIT_HMAC_KEY is set but too short to key the HMAC."""


def audit_key(environ: Mapping[str, str] = os.environ, warn: TextIO | None = None) -> bytes:
    """The audit key: AUDIT_HMAC_KEY's bytes, or, when it is unset, one random key for this process,
    with a warning on stderr (or `warn`) the first time it is made."""
    global _process_key
    value = environ.get(KEY_ENV, "").strip()
    if value:
        key = value.encode("utf-8")
        if len(key) < MIN_KEY_BYTES:
            raise AuditKeyError(f"{KEY_ENV} is shorter than {MIN_KEY_BYTES} bytes, the length RFC 2104 "
                                "asks of an HMAC-SHA256 key.")
        return key
    if _process_key is None:
        _process_key = secrets.token_bytes(MIN_KEY_BYTES)
        print(f"warning: {KEY_ENV} is not set, so this process keys the HMACs in its audit lines with a "
              "random key of its own, and no auditor can match them to the harness's log. Set it to the "
              "key the log archive account holds.", file=warn or sys.stderr, flush=True)
    return _process_key


def check_audit_key(environ: Mapping[str, str] = os.environ) -> None:
    """A server's start: an AUDIT_HMAC_KEY that is set must be long enough (AuditKeyError otherwise). An
    unset one is left for audit_key to make, with its warning, when a line first needs it."""
    if environ.get(KEY_ENV, "").strip():
        audit_key(environ)


def text_hmac(text: str, key: bytes | None = None) -> str:
    """`hmac-sha256:` and the hex HMAC-SHA256 of the text's UTF-8 bytes under `key`, by default the
    audit key."""
    digest = hmac.new(audit_key() if key is None else key, text.encode("utf-8"), hashlib.sha256)
    return PREFIX + digest.hexdigest()
