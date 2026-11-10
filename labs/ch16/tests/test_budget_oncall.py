"""The on-call lead's kill switch at the gateway, and the change record it leaves (ch02:146, ch02:163).

LiteLLM's admin API is an httpx mock transport here; the drills pull the same lever against the real proxy.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import keys
import oncall
import pytest

TOKEN = "a" * 64  # a hashed key, as /key/list returns it
LEAD = "oncall.lead@larkspur.example"


class FakeAdmin:
    """Answers /key/list, /key/info, /key/block and /key/unblock like LiteLLM 1.106.6, and records each request."""

    def __init__(self) -> None:
        self.blocked = False
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != "Bearer sk-master":
            return httpx.Response(401, json={"error": {"message": "Authentication Error"}})
        path = request.url.path
        if path == "/key/list":
            alias = request.url.params.get("key_alias")
            keys_ = [{"token": TOKEN, "key_alias": "w2-ops-assistant"}, {"token": "b" * 64, "key_alias": "w2-ops"}]
            return httpx.Response(200, json={"keys": [k for k in keys_ if alias in k["key_alias"]]})
        if path == "/key/info":
            return httpx.Response(200, json={"key": TOKEN, "info": {"key_alias": "w2-ops-assistant",
                                                                    "blocked": self.blocked}})
        if path in ("/key/block", "/key/unblock"):
            assert json.loads(request.content) == {"key": TOKEN}  # the hashed token, never the key itself
            self.blocked = path == "/key/block"
            return httpx.Response(200, json={"token": TOKEN, "blocked": self.blocked})
        return httpx.Response(404, json={})


@pytest.fixture
def admin():
    fake = FakeAdmin()
    return keys.Admin("http://gateway.test", "sk-master", httpx.Client(transport=httpx.MockTransport(fake))), fake


def test_kill_blocks_the_workflows_key_found_by_its_alias(admin, tmp_path):
    client, fake = admin
    at = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)
    line = oncall.kill(client, "w2-ops-assistant", by=LEAD, change="EC-20261103-01",
                       reason="cost spike: one run looping", folder=tmp_path, now=at)
    assert fake.blocked
    assert [r.url.path for r in fake.requests] == ["/key/list", "/key/info", "/key/block"]
    assert (line["lever"], line["from"], line["to"]) == ("kill switch, gateway half", "open", "blocked")
    assert line["answer"]["blocked"] is True and line["answer"]["seconds"] >= 0
    assert (line["kind"], line["authority"], line["by"]) == ("emergency", "on-call lead", LEAD)
    assert line["at"] == "2026-11-03T03:00:00.000+00:00"
    assert line["document_by"] == "2026-11-04T03:00:00.000+00:00"  # documented within twenty-four hours
    assert line["review"] == "the next board meeting"


def test_reopen_unblocks_and_both_levers_are_on_the_record(admin, tmp_path):
    client, fake = admin
    oncall.kill(client, "w2-ops-assistant", by=LEAD, change="EC-1", reason="x", folder=tmp_path)
    oncall.reopen(client, "w2-ops-assistant", by=LEAD, change="EC-1", reason="loop fixed", folder=tmp_path)
    assert not fake.blocked
    lines = [json.loads(line) for line in (tmp_path / "changes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(c["lever"], c["from"], c["to"]) for c in lines] == [
        ("kill switch, gateway half", "open", "blocked"), ("kill switch released", "blocked", "open")]


def test_an_alias_must_name_exactly_one_key(admin):
    client, _ = admin
    with pytest.raises(LookupError):
        client.token_for("w2")  # matches no alias exactly
    assert client.token_for("w2-ops") == "b" * 64  # exact, not a prefix of w2-ops-assistant


def test_a_refused_admin_call_raises(admin):
    _, fake = admin
    wrong = keys.Admin("http://gateway.test", "sk-wrong", httpx.Client(transport=httpx.MockTransport(fake)))
    with pytest.raises(keys.AdminError) as refused:
        wrong.block(TOKEN)
    assert refused.value.status == 401
