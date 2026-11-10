"""The HMAC an audit line carries in place of text (knowledge-server/audit_hmac.py, companion #126): the
algorithm and its full digest, where the key comes from, and what happens without one."""

from __future__ import annotations

import io
import os
import subprocess
import sys

import pytest

import audit_hmac
from audit_hmac import KEY_ENV, AuditKeyError, audit_key, check_audit_key, text_hmac
from conftest import AUDIT_KEY, GATEWAY_KEY, SECRET, SERVER_PY, free_port


def test_the_hmac_is_hmac_sha256_of_the_utf8_text_with_its_full_digest():
    # The HMAC-SHA256 example Wikipedia's HMAC article lists; a key this short is fine for a test vector.
    fox = text_hmac("The quick brown fox jumps over the lazy dog", b"key")
    assert fox == "hmac-sha256:f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"
    assert text_hmac("Zoë", b"key") != text_hmac("Zoe", b"key")  # the text's own bytes, accents included
    assert len(text_hmac("", b"key")) == len("hmac-sha256:") + 64  # an empty text is hashed like any other


def test_the_key_is_the_variables_and_a_short_one_is_refused():
    assert audit_key({KEY_ENV: f"  {AUDIT_KEY}\n"}) == AUDIT_KEY.encode("utf-8")
    assert text_hmac("Dana Whitfield", AUDIT_KEY.encode()) != text_hmac("Dana Whitfield", b"x" * 32)
    with pytest.raises(AuditKeyError, match=KEY_ENV):
        audit_key({KEY_ENV: "x" * 31})
    with pytest.raises(AuditKeyError, match=KEY_ENV):
        check_audit_key({KEY_ENV: "x" * 31})
    check_audit_key({KEY_ENV: AUDIT_KEY})


def test_without_a_key_a_process_makes_a_random_one_and_warns_once(monkeypatch):
    monkeypatch.setattr(audit_hmac, "_process_key", None)
    check_audit_key({})  # a server's start: nothing to check, and nothing made until a line needs it
    assert audit_hmac._process_key is None
    warned = io.StringIO()
    first = audit_key({}, warn=warned)
    assert audit_key({}, warn=warned) == first and len(first) == 32
    assert warned.getvalue().count("\n") == 1 and KEY_ENV in warned.getvalue()
    monkeypatch.setattr(audit_hmac, "_process_key", None)  # another process
    assert audit_key({}, warn=io.StringIO()) != first  # no key written in code stands in
    monkeypatch.delenv(KEY_ENV, raising=False)
    assert text_hmac("Dana Whitfield") == text_hmac("Dana Whitfield", audit_hmac._process_key)


def test_the_knowledge_server_refuses_to_start_on_a_short_key():
    env = {**os.environ, "TOOL_IDENTITY": "larkspur-knowledge-reader", "W1_TOKEN_SECRET": SECRET,
           "GATEWAY_KEY": GATEWAY_KEY, KEY_ENV: "too short"}
    run = subprocess.run([sys.executable, str(SERVER_PY), "--port", str(free_port())], env=env,
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 2 and f"refusing to start: {KEY_ENV} is shorter than 32 bytes" in run.stderr
