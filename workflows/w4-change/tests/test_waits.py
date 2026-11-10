"""The rationale seam under a 429 (chapter 16's step 5b, companion #14): a wait the answer asks for is waited out,
within a cap, before the stub stands in; a 429 that names no wait goes to the stub at once, as every other failure
does."""

from __future__ import annotations

import httpx
import pytest

import rationale_model

EVIDENCE = {"change_ref": "claims-api#482", "service": "claims-api"}
SENTENCE = "Low risk: CI passed."
URL = "http://gateway.test/v1"


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch):
    """A scripted gateway behind httpx.post, a sleep that only records, and no jitter."""
    state: dict = {"answers": [], "sent": [], "slept": []}

    def post(url, **kwargs):
        state["sent"].append(kwargs["json"])
        status, headers = state["answers"].pop(0) if len(state["answers"]) > 1 else state["answers"][0]
        body = {"choices": [{"message": {"content": SENTENCE}}]} if status == 200 else {"error": {"message": "no"}}
        return httpx.Response(status, headers=headers, json=body, request=httpx.Request("POST", url))

    monkeypatch.setenv("W4_MODEL_BASE_URL", URL)
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(rationale_model, "pause", state["slept"].append)
    monkeypatch.setattr(rationale_model, "WAIT_JITTER_S", 0.0)
    return state


def test_a_429_with_a_wait_is_waited_out_and_the_model_writes_the_sentence(gateway):
    gateway["answers"] = [(429, {"retry-after": "20"}), (200, {})]
    assert rationale_model.rationale_with_source(EVIDENCE, "Low", ["CI passed"], trace_id="a" * 32) == (SENTENCE, "model")
    assert gateway["slept"] == [20.0] and len(gateway["sent"]) == 2 and gateway["sent"][0] == gateway["sent"][1]


def test_a_providers_wait_through_litellm_counts(gateway):
    gateway["answers"] = [(429, {"llm_provider-retry-after": "3"}), (200, {})]
    assert rationale_model.rationale_with_source(EVIDENCE, "Low", ["CI passed"])[1] == "model"
    assert gateway["slept"] == [3.0]


def test_a_429_that_names_no_wait_goes_to_the_stub_at_once(gateway):
    gateway["answers"] = [(429, {})]
    text, source = rationale_model.rationale_with_source(EVIDENCE, "Low", ["CI passed"])
    assert source == "stub" and len(gateway["sent"]) == 1 and gateway["slept"] == []


def test_a_wait_past_the_cap_goes_to_the_stub_and_six_attempts_at_most(gateway):
    gateway["answers"] = [(429, {"retry-after": "61"})]
    assert rationale_model.rationale_with_source(EVIDENCE, "Low", ["CI passed"])[1] == "stub"
    assert len(gateway["sent"]) == 1 and gateway["slept"] == []
    gateway["sent"].clear()
    gateway["answers"] = [(429, {"retry-after": "1"})]
    assert rationale_model.rationale_with_source(EVIDENCE, "Low", ["CI passed"])[1] == "stub"
    assert len(gateway["sent"]) == rationale_model.WAIT_ATTEMPTS
    assert gateway["slept"] == [1.0] * (rationale_model.WAIT_ATTEMPTS - 1)


def test_any_other_failure_goes_to_the_stub_without_a_second_call(gateway):
    for status in (400, 408, 422, 500, 503):
        gateway["sent"].clear()
        gateway["answers"] = [(status, {"retry-after": "1"})]
        assert rationale_model.rationale_with_source(EVIDENCE, "Low", ["CI passed"])[1] == "stub", status
        assert len(gateway["sent"]) == 1 and gateway["slept"] == [], status


def test_the_wait_comes_from_the_first_header_that_names_one():
    assert rationale_model.retry_after_s({"Retry-After": "9"}) == 9.0
    assert rationale_model.retry_after_s({"retry-after-ms": "1500"}) == 1.5
    assert rationale_model.retry_after_s({"retry-after": "later"}) is None and rationale_model.retry_after_s(None) is None
