"""W3 under a 429 or a 408 (chapter 16's step 5b, companion #14): a wait the answer asks for is waited out when it
ends inside the incident's time budget, and otherwise the run ends as "model unavailable", refused in W3's store and
handed to a person, before any write. Step 5's outage drill had W3 raise on both."""

from __future__ import annotations

import json

import httpx
import pytest
from loop import CHAT_ALIAS, MODEL_UNAVAILABLE, TIME_BUDGET_S, WAIT_ATTEMPTS, W3GatewayModel, run_steps
from machine import State

from conftest import ALLOWED, ENGINEER, WRITES, Reads, harness_over

SERVICE = "claims-api"
ANSWER = {"choices": [{"message": {"role": "assistant", "content": "claims-api has 1 of 3 pods ready"}}],
          "usage": {"prompt_tokens": 40, "completion_tokens": 9}}


class Clock:
    """A clock that only the fake sleep moves."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def gateway(*answers: httpx.Response):
    """A gateway that gives these answers in order, then the last one for ever, each as a fresh response; it
    records each request."""
    seen: list[dict] = []
    queue = list(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        template = queue.pop(0) if len(queue) > 1 else queue[0]
        headers = {k: v for k, v in template.headers.items() if k.lower() != "content-length"}
        return httpx.Response(template.status_code, headers=headers, content=template.content)

    return handler, seen


def model(handler, clock: Clock, **fields) -> W3GatewayModel:
    return W3GatewayModel(gateway_url="http://gateway.test", alias=CHAT_ALIAS, api_key="sk-test",
                          tools=[{"type": "function", "function": {"name": "get_pod_status", "parameters": {}}}],
                          client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=clock.sleep,
                          clock=clock, jitter=lambda: 0.0, **fields)


def throttled(status: int = 429, **headers: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": "slow down"}}, headers=headers)


QUESTION = [{"role": "user", "content": f"{SERVICE} is paging"}]


def test_a_429_that_fits_the_time_budget_is_waited_out_and_the_same_call_goes_again():
    clock = Clock()
    handler, seen = gateway(throttled(**{"retry-after": "30"}), httpx.Response(200, json=ANSWER))
    m = model(handler, clock)
    assert m(QUESTION) == {"answer": "claims-api has 1 of 3 pods ready", "reasoning": None}
    assert clock.slept == [30.0] and m.waits == [{"status": 429, "asked_s": 30.0, "waited_s": 30.0, "at_s": 0.0}]
    assert len(seen) == 2 and seen[0] == seen[1], "the same request, sent again"
    assert m.labels == [("confidential", CHAT_ALIAS)], "one call, labelled once"
    assert len(m.calls) == 1 and m.unavailable is None


def test_the_providers_wait_through_litellm_counts_and_a_jitter_is_added():
    clock = Clock()
    handler, _ = gateway(throttled(**{"llm_provider-retry-after": "4"}), httpx.Response(200, json=ANSWER))
    m = model(handler, clock)
    m.jitter = lambda: 0.5
    assert "answer" in m(QUESTION)
    assert clock.slept == [4.5]


def test_a_wait_that_would_end_past_the_time_budget_ends_the_run_as_model_unavailable():
    clock = Clock()
    handler, seen = gateway(throttled(**{"retry-after": "30"}))
    m = model(handler, clock, time_budget_s=20.0)
    assert m(QUESTION) == {"model_unavailable": True, "reasoning": None}
    assert clock.slept == [] and len(seen) == 1
    assert m.unavailable == "429 asking 30 s, 0.0 s into a 20 s time budget"


def test_the_budget_counts_from_the_triages_first_model_call():
    clock = Clock()
    handler, _ = gateway(httpx.Response(200, json=ANSWER), throttled(**{"retry-after": "30"}))
    m = model(handler, clock)
    m(QUESTION)
    clock.now += TIME_BUDGET_S - 20  # the triage's reads took most of the budget
    assert m(QUESTION + [{"role": "user", "content": "and now?"}]) == {"model_unavailable": True, "reasoning": None}
    assert clock.slept == [] and m.unavailable.startswith("429 asking 30 s, 100.0 s into")


def test_a_429_or_a_408_that_names_no_wait_is_never_sent_again():
    for status in (429, 408):
        clock = Clock()
        handler, seen = gateway(throttled(status))
        m = model(handler, clock)
        assert m(QUESTION) == {"model_unavailable": True, "reasoning": None}, status
        assert len(seen) == 1 and clock.slept == [] and m.unavailable == f"{status} with no wait to wait out"


def test_a_408_with_a_wait_is_waited_out_like_a_429():
    clock = Clock()
    handler, _ = gateway(throttled(408, **{"retry-after": "2"}), httpx.Response(200, json=ANSWER))
    m = model(handler, clock)
    assert "answer" in m(QUESTION) and clock.slept == [2.0]


def test_six_attempts_at_most():
    clock = Clock()
    handler, seen = gateway(throttled(**{"retry-after": "1"}))
    m = model(handler, clock)
    assert m(QUESTION) == {"model_unavailable": True, "reasoning": None}
    assert len(seen) == WAIT_ATTEMPTS and len(clock.slept) == WAIT_ATTEMPTS - 1


def test_a_5xx_or_a_refused_connection_still_ends_the_run_and_another_4xx_still_raises():
    clock = Clock()
    handler, _ = gateway(httpx.Response(503, json={"error": "no healthy upstream"}))
    m = model(handler, clock)
    assert m(QUESTION) == {"model_unavailable": True, "reasoning": None} and m.unavailable == "the gateway answered 503"

    def refused_connection(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    m = model(refused_connection, clock)
    assert m(QUESTION)["model_unavailable"] and m.unavailable == "the route is unreachable (ConnectError)"
    handler, _ = gateway(httpx.Response(400, json={"detail": "data class 'restricted' may not go to 'larkspur-chat'"}))
    with pytest.raises(httpx.HTTPStatusError):
        model(handler, clock)(QUESTION)
    assert clock.slept == []


def test_the_loop_ends_a_triage_whose_wait_doesnt_fit_as_model_unavailable():
    clock = Clock()
    handler, _ = gateway(throttled(**{"retry-after": "30"}))
    outcome = run_steps("q", model(handler, clock, time_budget_s=10.0), Reads().tools(), ALLOWED, set(WRITES))
    assert outcome.kind == "unavailable" and outcome.text == MODEL_UNAVAILABLE and outcome.reason == "model unavailable"


def test_the_harness_records_the_run_refused_and_hands_it_to_a_person_before_any_write(store_path, parts):
    """The cooldown's 429 with retry-after 30, past a ten-second budget: the run is refused in W3's store with the
    fixed sentence, which tells the engineer to work the incident without W3, and no approval or write follows."""
    clock = Clock()
    handler, _ = gateway(throttled(**{"retry-after": "30"}))
    harness = harness_over(store_path, model(handler, clock, time_budget_s=10.0), parts)
    run = harness.start(f"{SERVICE} is paging", ENGINEER, trace_id="t-cooldown")
    assert run.state is State.REFUSED
    payload = harness.machine.payload("t-cooldown", State.REFUSED)
    assert payload["reason"] == "model unavailable" and payload["text"] == MODEL_UNAVAILABLE
    assert parts["writer"].calls == [] and parts["approvals"].requests == {}
    assert harness.machine.load("t-cooldown").terminal, "not left in triaging for a restarted harness"


def test_a_run_whose_wait_fits_goes_on_to_its_answer(store_path, parts):
    clock = Clock()
    handler, _ = gateway(throttled(**{"retry-after": "30"}), httpx.Response(200, json=ANSWER))
    harness = harness_over(store_path, model(handler, clock), parts)
    run = harness.start(f"{SERVICE} is paging", ENGINEER, trace_id="t-waited")
    assert run.state is State.DONE and clock.slept == [30.0]
    assert harness.machine.payload("t-waited", State.DONE)["answer"] == "claims-api has 1 of 3 pods ready"
