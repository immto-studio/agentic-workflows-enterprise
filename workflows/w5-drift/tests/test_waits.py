"""The prose seam under a 429 (chapter 16's step 5b, companion #14): a wait the answer asks for is waited out,
within a cap, before the stub stands in; a 429 that names no wait goes to the stub at once, as every other failure
does. The gateway is httpx's mock transport, so no socket opens."""

from __future__ import annotations

import json

import fixture_night
import httpx
import prose
import pytest

REPLY = "TITLE: The billing worker group gained a rule outside Terraform\nBODY: A Jenkins job added an 8080 rule."
BASE = "http://gateway.test/v1"


@pytest.fixture(scope="module")
def finding():
    workspace = list(fixture_night.PAIRS)[0]
    return fixture_night.findings_for(workspace)[0]


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waits: list[float] = []
    monkeypatch.setattr(prose, "pause", waits.append)
    monkeypatch.setattr(prose, "WAIT_JITTER_S", 0.0)
    return waits


def gateway(*answers: tuple[int, dict[str, str]]):
    """These answers in order, then the last one for ever, through the mock transport; every request is kept."""
    sent: list[dict] = []
    queue = list(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        status, headers = queue.pop(0) if len(queue) > 1 else queue[0]
        if status == 200:
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": REPLY}}],
                                             "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        return httpx.Response(status, headers=headers, json={"error": {"message": "no"}})

    return httpx.Client(transport=httpx.MockTransport(handler)), sent


def test_a_429_with_a_wait_is_waited_out_and_the_model_writes(finding, slept):
    client, sent = gateway((429, {"retry-after": "30"}), (200, {}))
    p = prose.write(finding, trace_id="t", client=client, base=BASE)
    assert p.body_source == "model" and p.title.startswith("The billing worker group")
    assert slept == [30.0] and len(sent) == 2 and sent[0] == sent[1]


def test_a_429_that_names_no_wait_goes_to_the_stub_at_once(finding, slept):
    client, sent = gateway((429, {}))
    assert prose.write(finding, trace_id="t", client=client, base=BASE).body_source == "stub"
    assert len(sent) == 1 and slept == []


def test_a_wait_past_the_cap_goes_to_the_stub_and_six_attempts_at_most(finding, slept):
    client, sent = gateway((429, {"llm_provider-retry-after": "61"}))
    assert prose.write(finding, trace_id="t", client=client, base=BASE).body_source == "stub"
    assert len(sent) == 1 and slept == []
    client, sent = gateway((429, {"retry-after": "1"}))
    assert prose.write(finding, trace_id="t", client=client, base=BASE).body_source == "stub"
    assert len(sent) == prose.WAIT_ATTEMPTS and slept == [1.0] * (prose.WAIT_ATTEMPTS - 1)


def test_any_other_failure_goes_to_the_stub_without_a_second_call(finding, slept):
    for status in (400, 408, 422, 500, 503):
        client, sent = gateway((status, {"retry-after": "1"}))
        assert prose.write(finding, trace_id="t", client=client, base=BASE).body_source == "stub", status
        assert len(sent) == 1 and slept == [], status


def test_the_wait_comes_from_the_first_header_that_names_one():
    assert prose.retry_after_s({"Retry-After": "12"}) == 12.0
    assert prose.retry_after_s({"llm_provider-retry-after-ms": "2500"}) == 2.5
    assert prose.retry_after_s({"retry-after": "Wed, 04 Nov 2026 07:28:00 GMT"}) is None and prose.retry_after_s({}) is None
