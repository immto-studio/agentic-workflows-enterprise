"""W2's model client under a 429 (chapter 16's step 5b, companion #14): a wait the answer asks for is waited out,
within a cap, and the same call goes again; a 429 that names no wait is never sent again. W3 reads the same wait
with `retry_after_s`."""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from conftest import W2

sys.path.insert(0, str(W2 / "harness"))
import answer  # noqa: E402

QUESTION = [{"role": "user", "content": "Is claims-api healthy?"}]
ANSWER = {"choices": [{"message": {"role": "assistant", "content": "claims-api has 3 of 3 pods ready."}}],
          "usage": {"prompt_tokens": 60, "completion_tokens": 9}}


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


def model(handler, clock: Clock, jitter: float = 0.0):
    client = answer.WaitingClient(transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock,
                                  jitter=lambda: jitter)
    m = answer.BoundedGatewayModel(gateway_url="http://gateway.test", alias=answer.CHAT_ALIAS, tools=[], api_key="k",
                                   trace_id="t1", client=client)
    return m, client


def throttled(**headers: str) -> tuple[int, dict[str, str], dict]:
    return 429, headers, {"error": {"message": "slow down"}}


def test_the_wait_comes_from_the_first_header_that_names_one():
    assert answer.retry_after_s({"Retry-After": "30"}) == 30.0
    assert answer.retry_after_s(httpx.Headers({"retry-after-ms": "250"})) == 0.25
    assert answer.retry_after_s({"llm_provider-retry-after-ms": "900", "llm_provider-retry-after": "1"}) == 0.9
    assert answer.retry_after_s({"retry-after": "soon"}) is None and answer.retry_after_s({}) is None


def test_a_model_built_without_a_client_waits():
    built = answer.BoundedGatewayModel(gateway_url="http://gateway.test", alias=answer.CHAT_ALIAS, tools=[])
    assert isinstance(built.client, answer.WaitingClient) and built.client.timeout.read == built.timeout_s


def test_the_cooldowns_429_is_waited_out_with_a_jitter_and_the_same_call_goes_again():
    """LiteLLM's cooled-down group answers 429 with retry-after 30 (chapter 16's step 5)."""
    clock = Clock()
    handler, seen = gateway(throttled(**{"retry-after": "30"}), (200, {}, ANSWER))
    m, client = model(handler, clock, jitter=0.5)
    assert m(QUESTION) == {"answer": "claims-api has 3 of 3 pods ready."}
    assert clock.slept == [30.5] and client.waits == [30.5]
    assert len(seen) == 2 and seen[0] == seen[1]
    assert m.labels == [("internal", answer.CHAT_ALIAS)] and len(m.calls) == 1


def test_a_429_that_names_no_wait_is_raised_at_once():
    clock = Clock()
    handler, seen = gateway((429, {}, {"error": {"message": "request refused: 'w2-ops-assistant' is over 120 "
                                                            "requests per minute"}}))
    m, _ = model(handler, clock)
    with pytest.raises(httpx.HTTPStatusError):
        m(QUESTION)
    assert len(seen) == 1 and clock.slept == []


def test_a_wait_past_the_cap_or_the_sixth_attempt_ends_it():
    clock = Clock()
    handler, seen = gateway(throttled(**{"retry-after": "61"}))
    m, _ = model(handler, clock)
    with pytest.raises(httpx.HTTPStatusError):
        m(QUESTION)
    assert len(seen) == 1 and clock.slept == []
    clock = Clock()
    handler, seen = gateway(throttled(**{"llm_provider-retry-after": "2"}))
    m, _ = model(handler, clock)
    with pytest.raises(httpx.HTTPStatusError):
        m(QUESTION)
    assert len(seen) == answer.WAIT_ATTEMPTS and clock.slept == [2.0] * (answer.WAIT_ATTEMPTS - 1)


def test_any_other_status_is_never_sent_again():
    for status in (400, 401, 408, 422, 500, 503):
        clock = Clock()
        handler, seen = gateway((status, {"retry-after": "1"}, {"error": {"message": "no"}}))
        m, _ = model(handler, clock)
        with pytest.raises(httpx.HTTPStatusError):
            m(QUESTION)
        assert len(seen) == 1 and clock.slept == [], status
