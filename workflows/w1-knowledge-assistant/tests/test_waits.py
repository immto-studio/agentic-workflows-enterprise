"""W1's model client under a 429 (chapter 16's step 5b, companion #14): a wait the answer asks for is waited out,
within a cap, and the same call goes again; a 429 that names no wait is never sent again."""

from __future__ import annotations

import importlib.util
import json
import sys

import httpx
import pytest

from conftest import W1

if "w1_answer" in sys.modules:  # test_answer.py loads it under this name, beside W2's answer.py
    answer = sys.modules["w1_answer"]
else:
    _spec = importlib.util.spec_from_file_location("w1_answer", W1 / "harness" / "answer.py")
    answer = importlib.util.module_from_spec(_spec)
    sys.modules["w1_answer"] = answer
    _spec.loader.exec_module(answer)

QUESTION = [{"role": "user", "content": "How many shards unseal Vault?"}]
ANSWER = {"choices": [{"message": {"role": "assistant", "content": "Three of five (Break-glass, reviewed 2026-06-04)."}}],
          "usage": {"prompt_tokens": 50, "completion_tokens": 12}}


class Clock:
    """A clock that only the fake sleep moves."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def gateway(*answers: tuple[int, dict[str, str], dict]):
    """These answers in order, then the last one for ever; every request is kept."""
    seen: list[dict] = []
    queue = list(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        status, headers, body = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(status, headers=headers, json=body)

    return handler, seen


def model(handler, clock: Clock):
    client = answer.WaitingClient(transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock,
                                  jitter=lambda: 0.0)
    m = answer.ClassifyingGatewayModel(gateway_url="http://gateway.test", alias="larkspur-chat", api_key="k",
                                       tools=answer.pinned_tool_specs(answer.LOCK_PATH, set(answer.ALLOWED)),
                                       trace_id="t1", client=client)
    return m, client


def throttled(**headers: str) -> tuple[int, dict[str, str], dict]:
    return 429, headers, {"error": {"message": "slow down"}}


def test_the_wait_comes_from_the_first_header_that_names_one():
    assert answer.retry_after_s({"Retry-After": "7"}) == 7.0
    assert answer.retry_after_s({"retry-after-ms": "1500", "retry-after": "7"}) == 1.5
    assert answer.retry_after_s({"llm_provider-retry-after": "4"}) == 4.0, "a provider's wait, through LiteLLM"
    assert answer.retry_after_s({"retry-after": "Wed, 04 Nov 2026 07:28:00 GMT"}) is None
    assert answer.retry_after_s({}) is None and answer.retry_after_s(None) is None


def test_a_model_built_without_a_client_waits_and_one_given_a_client_keeps_it():
    built = answer.ClassifyingGatewayModel(gateway_url="http://gateway.test", alias="larkspur-chat", tools=[])
    assert isinstance(built.client, answer.WaitingClient) and built.client.timeout.read == built.timeout_s
    given = httpx.Client()
    assert answer.ClassifyingGatewayModel(gateway_url="http://gateway.test", alias="larkspur-chat", tools=[],
                                          client=given).client is given


def test_a_429_with_a_wait_is_waited_out_and_the_same_call_goes_again():
    clock = Clock()
    handler, seen = gateway(throttled(**{"retry-after": "20"}), (200, {}, ANSWER))
    m, client = model(handler, clock)
    assert m(QUESTION) == {"answer": "Three of five (Break-glass, reviewed 2026-06-04)."}
    assert clock.slept == [20.0] and client.waits == [20.0]
    assert len(seen) == 2 and seen[0] == seen[1]
    assert m.labels == [("internal", "larkspur-chat")] and len(m.calls) == 1


def test_a_429_that_names_no_wait_is_raised_at_once():
    """Chapter 5's per-run budget and request rate answer 429 with no wait; W1 never sends those again."""
    clock = Clock()
    handler, seen = gateway((429, {}, {"error": {"message": "request refused: run t1 has spent $2.0000"}}))
    m, _ = model(handler, clock)
    with pytest.raises(httpx.HTTPStatusError):
        m(QUESTION)
    assert len(seen) == 1 and clock.slept == []


def test_a_wait_past_the_cap_is_not_waited_and_six_attempts_at_most():
    clock = Clock()
    handler, seen = gateway(throttled(**{"retry-after": str(answer.WAIT_CAP_S + 1)}))
    m, _ = model(handler, clock)
    with pytest.raises(httpx.HTTPStatusError):
        m(QUESTION)
    assert len(seen) == 1 and clock.slept == []
    clock = Clock()
    handler, seen = gateway(throttled(**{"retry-after": "1"}))
    m, _ = model(handler, clock)
    with pytest.raises(httpx.HTTPStatusError):
        m(QUESTION)
    assert len(seen) == answer.WAIT_ATTEMPTS and len(clock.slept) == answer.WAIT_ATTEMPTS - 1


def test_the_cap_counts_every_wait_since_the_first_attempt():
    clock = Clock()
    handler, seen = gateway(throttled(**{"retry-after": "25"}))
    m, _ = model(handler, clock)
    with pytest.raises(httpx.HTTPStatusError):
        m(QUESTION)
    assert clock.slept == [25.0, 25.0] and len(seen) == 3, "a third wait would end past a minute"


def test_any_other_status_is_never_sent_again():
    for status in (400, 401, 422, 500, 503):
        clock = Clock()
        handler, seen = gateway((status, {"retry-after": "1"}, {"error": {"message": "no"}}))
        m, _ = model(handler, clock)
        with pytest.raises(httpx.HTTPStatusError):
            m(QUESTION)
        assert len(seen) == 1 and clock.slept == [], status
