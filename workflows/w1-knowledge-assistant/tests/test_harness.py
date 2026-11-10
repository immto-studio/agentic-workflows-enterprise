"""W1's harness end to end: chapter 5's loop against the knowledge server, with a scripted model behind a stand-in gateway.

The stand-in model (conftest.fake_gateway) searches with the question for as long as it is offered
a tool and answers in the system prompt's refusal words once it isn't, which is how gpt-oss behaved
on questions the engineer can't read: it kept searching.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import re
import sys

import pytest

from conftest import (AUDIT_KEY, FAIL_CHAT, FAIL_EMBEDDING, GATEWAY_KEY, ON_CALL, SECRET, SLOW_EMBEDDING,
                      STUBBORN, USERS, W1, log_events)
from access import issue
from audit_hmac import text_hmac
from store import RANK

_spec = importlib.util.spec_from_file_location("w1_answer_e2e", W1 / "harness" / "answer.py")
answer = importlib.util.module_from_spec(_spec)
sys.modules["w1_answer_e2e"] = answer
_spec.loader.exec_module(answer)


def ask(url: str, gateway: str, user: str, question: str, **token_options):
    token = issue(SECRET, USERS[user], f"{user}@larkspur.example", **token_options)
    log = io.StringIO()
    reply, model = asyncio.run(answer.ask(question, token, url, gateway, GATEWAY_KEY, log=log,
                                          audit={"case": "e2e", "persona": user}))
    return reply, model, [json.loads(line) for line in log.getvalue().splitlines()]


def chat_requests(seen: list[dict]) -> list[dict]:
    return [s for s in seen if s["path"].endswith("/chat/completions")]


def test_an_expired_token_ends_in_couldnt_search_not_in_the_refusal(running_server, fake_gateway, golden):
    # The review's probe 6: five refused searches used to end in "Nothing in the documents...".
    url, _, _ = running_server
    gateway, seen = fake_gateway
    before = len(chat_requests(seen))
    gq08 = next(q for q in golden if q["id"] == "gq-08")
    reply, model, lines = ask(url, gateway, "oncall.engineer", gq08["question"], minutes=-5)
    assert reply == answer.SEARCH_FAILED
    assert model.labels == [] and len(chat_requests(seen)) == before  # no model call at all
    assert [(line["tool"], line["ok"]) for line in lines if line["event"] == "tool_call"] == [("caller_class", False)]


def test_a_failed_search_ends_in_couldnt_search(running_server, fake_gateway):
    url, _, _ = running_server
    gateway, _ = fake_gateway
    reply, model, lines = ask(url, gateway, "oncall.engineer", f"Sev2 acknowledgement time? {FAIL_EMBEDDING}")
    assert reply == answer.SEARCH_FAILED
    assert len(model.labels) == 1  # the call that asked for the search; the failure ends the question
    calls = [(line["tool"], line["ok"]) for line in lines if line["event"] == "tool_call"]
    assert calls == [("caller_class", True), ("search_docs", False)]


def test_a_custodians_question_is_restricted_throughout_and_ends_after_two_searches(
        running_server, fake_gateway, golden):
    url, _, _ = running_server
    gateway, seen = fake_gateway
    before = len(chat_requests(seen))
    gq01 = next(q for q in golden if q["id"] == "gq-01")
    reply, model, lines = ask(url, gateway, "vault.custodian", gq01["question"])
    assert model.floor == "Restricted"
    assert model.labels == [("restricted", "larkspur-chat-restricted")] * 3  # from the first call on
    requests = chat_requests(seen)[before:]
    assert [bool(r.get("tools")) for r in requests] == [True, True, False]  # no third search
    assert all("data_class:restricted" in r["metadata"]["tags"] for r in requests)
    searches = [line for line in lines if line["event"] == "tool_call" and line["tool"] == "search_docs"]
    assert len(searches) == 2 and searches[0]["args"] == {"query": gq01["question"]}
    # The stand-in refused in the system prompt's words and left the route out; the harness adds it.
    assert reply.endswith(answer.ROUTE)


def test_a_search_that_never_comes_back_ends_in_couldnt_search(running_server, fake_gateway, monkeypatch):
    # Chapter 5's bridge gives up after its timeout and raises; W1 still answers SEARCH_FAILED.
    url, _, _ = running_server
    gateway, _ = fake_gateway
    monkeypatch.setattr(sys.modules["client"], "CALL_TIMEOUT_SECONDS", 1)
    reply, model, lines = ask(url, gateway, "oncall.engineer", f"Sev2 acknowledgement time? {SLOW_EMBEDDING}")
    assert reply == answer.SEARCH_FAILED and len(model.labels) == 1
    assert [(line["tool"], line["ok"]) for line in lines if line["event"] == "tool_call"] == \
        [("caller_class", True), ("search_docs", False)]


def test_a_failed_model_call_is_not_passed_off_as_a_failed_search(running_server, fake_gateway):
    url, _, _ = running_server
    gateway, _ = fake_gateway
    with pytest.raises(Exception):
        ask(url, gateway, "oncall.engineer", f"Sev2 acknowledgement time? {FAIL_CHAT}")


def test_a_model_that_asks_for_a_third_search_gets_the_harnesss_refusal(running_server, fake_gateway, golden):
    # gpt-oss asked for a third search on a call that offered it no tool; the harness doesn't run it.
    url, _, _ = running_server
    gateway, seen = fake_gateway
    before = len(chat_requests(seen))
    gq01 = next(q for q in golden if q["id"] == "gq-01")
    reply, model, lines = ask(url, gateway, "oncall.engineer", f"{gq01['question']} {STUBBORN}")
    assert reply == answer.REFUSAL
    assert len(model.labels) == 3 and len(chat_requests(seen)) - before == 3
    assert sum(line["event"] == "tool_call" and line["tool"] == "search_docs" for line in lines) == 2


def test_the_on_call_engineer_starts_at_internal(running_server, fake_gateway, golden):
    url, _, _ = running_server
    gateway, _ = fake_gateway
    gq01 = next(q for q in golden if q["id"] == "gq-01")
    reply, model, _ = ask(url, gateway, "oncall.engineer", gq01["question"])
    assert model.floor == "Internal"
    assert model.labels == [("internal", "larkspur-chat")] * 3
    assert reply.endswith(answer.ROUTE) and "break-glass" not in reply.lower()


def test_the_servers_line_names_each_page_by_an_hmac_of_the_title_the_harnesss_log_keeps(
        running_server, fake_gateway, golden):
    # Chapter 17's rule (companion #126): the knowledge server keeps a title only as an HMAC under the
    # audit key, the harness's log keeps the title, and an auditor with the key matches the two.
    url, server_log, _ = running_server
    gateway, _ = fake_gateway
    gq08 = next(q for q in golden if q["id"] == "gq-08")
    _, model, lines = ask(url, gateway, "oncall.engineer", gq08["question"])
    kept = [line for line in lines if line["event"] == "search_result"]
    audited = [line for line in log_events(server_log) if line["event"] == "search" and line["trace_id"] == model.trace_id]
    assert len(kept) == len(audited) == 2 and all(line["trace_id"] == model.trace_id for line in kept)
    key, other = AUDIT_KEY.encode(), b"another audit key, also 32 bytes or more"
    for harness, server in zip(kept, audited):
        titles = harness["titles"]
        assert titles and server["returned"] == [text_hmac(title, key) for title in titles]
        assert all(re.fullmatch(r"hmac-sha256:[0-9a-f]{64}", h) for h in server["returned"])  # the full digest
        assert not set(server["returned"]) & {text_hmac(title, other) for title in titles}  # the key decides
        # Every other field is a value the test can name, so no part of a title is left in clear.
        assert set(server) == {"ts", "event", "trace_id", "caller", "groups_from", "groups", "returned",
                               "highest_class", "query_class"}
        assert (server["event"], server["caller"], server["groups_from"]) == ("search", USERS["oncall.engineer"], "table")
        assert set(server["groups"]) <= ON_CALL and {server["highest_class"], server["query_class"]} <= set(RANK)
        assert not any(title.lower() in json.dumps(server).lower() for title in titles)
