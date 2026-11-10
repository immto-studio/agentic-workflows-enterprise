"""The fake provider's quota: reserved up front from the prompt and max_tokens, settled after, refused with the
wait it needs; and its HTTP layer, driven in-process with no socket: the 429's headers, the failure modes, the
forced throttle, the markers, the burndown."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import fake_provider as fp
import load


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_reservation_fits_until_the_window_is_full_and_says_how_long_to_wait():
    clock = Clock()
    quota = fp.TokenQuota(10_000, clock=clock)
    first, wait = quota.reserve(6_000)
    assert first and wait == 0
    clock.now += 10
    second, wait = quota.reserve(3_000)
    assert second and wait == 0 and quota.used() == 9_000
    clock.now += 5
    refused, wait = quota.reserve(2_000)
    assert refused is None
    assert wait == pytest.approx(45.0), "the first charge, 15 s old, expires 60 s after it was made"
    clock.now += 45
    again, wait = quota.reserve(2_000)
    assert again and wait == 0 and quota.used() == 5_000


def test_settling_replaces_the_reservation_and_keeps_its_place_in_the_window():
    clock = Clock()
    quota = fp.TokenQuota(10_000, clock=clock)
    key, _ = quota.reserve(8_000)  # 6,000 prompt tokens and max_tokens 2,000
    quota.settle(key, 7_000)       # 1,000 output tokens came back
    assert quota.used() == 7_000
    assert quota.wait_for(3_001) == pytest.approx(60.0) and quota.wait_for(3_000) == 0
    clock.now += 60
    assert quota.used() == 0, "a settled charge leaves the window when its reservation would have"


def test_a_request_larger_than_the_quota_is_told_a_whole_window():
    quota = fp.TokenQuota(1_000, clock=Clock())
    assert quota.reserve(1_001) == (None, 60.0)
    assert fp.TokenQuota(None).reserve(10**9)[1] == 0, "no quota, no refusal"


def test_retry_after_is_whole_seconds_and_never_zero():
    assert fp.retry_after_header(0.2) == "1" and fp.retry_after_header(44.01) == "45" and fp.retry_after_header(5) == "5"


def test_the_estimate_is_the_prompt_at_four_characters_a_token_and_max_tokens_or_the_default():
    provider = fp.Provider(fp.Settings("p", tpm=None, default_max_tokens=4096))
    body = load.body("w3-incident", "confidential", "abc123", load.Shape(1640, 256, 114))
    record = provider.admit(body)
    assert record["input_tokens"] == 1640 and record["estimate"] == 1640 + 256
    assert record["workflow"] == "w3-incident" and record["request"] == "abc123"
    unset = provider.admit({"messages": [{"role": "user", "content": "x" * 400}]})
    assert unset["estimate"] == 100 + 4096, "a request without max_tokens reserves the provider's default"


@pytest.fixture
def client():
    provider = fp.Provider(fp.Settings("primary", tpm=10_000, base_ms=0, hang_s=0.05))
    with TestClient(fp.build_app(provider)) as c:
        c.provider = provider
        yield c


def post(c, shape: load.Shape, request_id: str = "r1", workflow: str = "w2-ops-assistant"):
    return c.post("/v1/chat/completions", json=load.body(workflow, "internal", request_id, shape))


def test_an_answer_reports_the_tokens_it_charges(client):
    r = post(client, load.Shape(4000, 2000, 1000))
    assert r.status_code == 200
    assert r.json()["usage"] == {"prompt_tokens": 4000, "completion_tokens": 1000, "total_tokens": 5000}
    assert client.provider.quota.used() == 5000, "settled at what was used, not at the 6,000 reserved"


def test_the_429_carries_the_clouds_headers(client):
    assert post(client, load.Shape(4000, 2000, 1000), "a").status_code == 200
    r = post(client, load.Shape(4000, 2000, 1000), "b")
    assert r.status_code == 429
    assert r.headers["retry-after"] == "60" and int(r.headers["retry-after-ms"]) <= 60_000
    assert r.headers["x-ratelimit-limit-tokens"] == "10000" and r.headers["x-ratelimit-remaining-tokens"] == "5000"
    assert "over its quota of 10000" in r.json()["error"]["message"]
    log = client.get("/log").json()["records"]
    assert [x["status"] for x in log] == [200, 429] and log[1]["request"] == "b"


def test_the_failure_modes_and_the_forced_throttle(client):
    assert client.post("/control", json={"mode": "5xx"}).json()["mode"] == "5xx"
    assert post(client, load.Shape(10, 10, 5)).status_code == 503
    client.post("/control", json={"mode": "timeout"})
    assert post(client, load.Shape(10, 10, 5)).status_code == 504
    client.post("/control", json={"mode": "ok", "throttle_next": 2, "retry_after_s": 7})
    first, second, third = (post(client, load.Shape(10, 10, 5), f"t{i}") for i in range(3))
    assert (first.status_code, second.status_code, third.status_code) == (429, 429, 200)
    assert first.headers["retry-after"] == "7" and "throttling on purpose" in first.json()["error"]["message"]
    assert client.post("/control", json={"mode": "down"}).status_code == 400


def test_burndown_charges_output_at_its_rate(client):
    client.post("/control", json={"burndown": 5, "reset_quota": True})
    post(client, load.Shape(1000, 500, 200))
    assert client.provider.quota.used() == 1000 + 5 * 200


def test_a_request_with_tools_gets_chapter_5s_rule_model(client):
    body = {"model": "larkspur-chat", "max_tokens": 64, "tools": [{"type": "function", "function": {
        "name": "get_pod_status", "parameters": {"type": "object"}}}],
            "messages": [{"role": "user", "content": "Is claims-api healthy?"}]}
    message = client.post("/v1/chat/completions", json=body).json()["choices"][0]["message"]
    assert message["tool_calls"][0]["function"]["name"] == "get_pod_status"
