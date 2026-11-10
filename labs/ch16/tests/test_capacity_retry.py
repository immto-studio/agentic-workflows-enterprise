"""The two retry policies, the waits they read, the limits an answer names, and a short throttled run of each
against the fake provider on 127.0.0.1."""

from __future__ import annotations

import asyncio
import random
import threading
import time

import pytest

import fake_provider as fp
import load
import report
import retry
import stack


def test_the_honouring_policy_waits_what_it_is_asked_plus_jitter_and_stops_at_six():
    rng = random.Random(1)
    for attempt in range(1, 6):
        wait = retry.next_wait(retry.HONOUR, attempt, 429, {"retry-after": "7"}, 0.0, rng)
        assert 7.0 <= wait <= 8.0
    assert retry.next_wait(retry.HONOUR, 6, 429, {"retry-after": "7"}, 0.0, rng) is None, "six total attempts"


def test_it_prefers_milliseconds_and_reads_the_gateways_prefix():
    assert retry.retry_after_s({"retry-after-ms": "1500", "retry-after": "9"}) == 1.5
    assert retry.retry_after_s({"Retry-After": "9"}) == 9.0
    assert retry.retry_after_s({"llm_provider-retry-after": "44", "x-ratelimit-remaining-tokens": "0"}) == 44.0
    assert retry.retry_after_s({"retry-after": "30", "llm_provider-retry-after": "44"}) == 30.0, "the gateway's own first"
    assert retry.retry_after_s({"retry-after": "Wed, 04 Nov 2026 00:00:00 GMT"}) is None
    assert retry.retry_after_s({}) is None


def test_without_a_retry_after_it_backs_off_as_the_sdks_do():
    rng = random.Random(2)
    waits = [retry.next_wait(retry.HONOUR, attempt, 429, {}, 0.0, rng) for attempt in range(1, 6)]
    caps = [min(20.0, 2 ** (a - 1)) for a in range(1, 6)]
    assert all(0 <= w <= cap for w, cap in zip(waits, caps))


def test_it_retries_only_what_is_safe_and_never_past_the_deadline():
    rng = random.Random(3)
    for status in (400, 401, 403, 404, 422, 500):
        assert retry.next_wait(retry.HONOUR, 1, status, {}, 0.0, rng) is None, status
    assert retry.next_wait(retry.HONOUR, 1, 503, {}, 0.0, rng) is not None
    assert retry.next_wait(retry.HONOUR, 1, 429, {"retry-after": "60"}, 5.0, rng) is None, "60 s more passes 60"


def test_the_naive_policy_retries_anything_at_once_twenty_times():
    rng = random.Random(4)
    assert retry.next_wait(retry.NAIVE, 1, 429, {"retry-after": "60"}, 0.0, rng) == 0.0
    assert retry.next_wait(retry.NAIVE, 1, 400, {}, 0.0, rng) == 0.0
    assert retry.next_wait(retry.NAIVE, 20, 429, {}, 0.0, rng) is None
    assert retry.next_wait(retry.NONE, 1, 429, {}, 0.0, rng) is None


@pytest.mark.parametrize("status, message, expected", [
    (429, "request refused: 'w2-ops-assistant' is over 120 requests per minute", "chapter 5's requests per minute"),
    (429, "Rate limit exceeded for api_key: 88a1. Limit type: tokens. Current limit: 75000", "the key's tokens per minute"),
    (429, "Deployment has all max_parallel_requests slots in use.", "the deployment's parallel requests"),
    (429, "Model rate limit exceeded. TPM limit=100000, current usage=100231", "the deployment's tokens per minute"),
    (429, "No deployments available for selected model, Try again in 30 seconds.", "the router's cooldown"),
    (429, "litellm.RateLimitError: OpenAIException - Too many tokens; primary is over its quota", "the provider's quota"),
    (422, "Budget has been exceeded! Current cost: 200.0", "the monthly budget"),
    (401, "Authentication Error, Key is blocked.", "the kill switch"),
    (400, "request refused: missing trace_id in metadata", "chapter 5's rules"),
    (503, "ServiceUnavailableError: primary is failing on purpose", "status 503"),
    (200, "", "served"),
    (None, "ConnectError", "no answer"),
])
def test_each_answer_names_the_limit_that_gave_it(status, message, expected):
    assert load.limiter(status, message) == expected


def test_a_prompt_is_the_size_the_ledger_says_and_percentiles_are_the_ledgers():
    shape = load.Shape(1602, 256, 99)
    text = load.prompt("w3-incident", "abcdef123456", shape)
    assert fp.count_tokens(text) == 1602 and len(text) == 1602 * 4
    assert shape.estimate == 1858 and shape.charge == 1701
    values = [0.4, 0.1, 0.9, 0.3, 0.7, 0.2, 0.8]
    for q in (0.5, 0.95, 0.99):
        assert load.percentile(values, q) == report.nearest_rank(values, q)


@pytest.fixture
def provider_url():
    import uvicorn

    port = stack.free_port()
    provider = fp.Provider(fp.Settings("primary", tpm=3_000, base_ms=5))
    server = uvicorn.Server(uvicorn.Config(fp.build_app(provider), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/v1", provider
    server.should_exit = True
    thread.join(timeout=10)


def test_naive_retries_multiply_the_load_and_honouring_ones_do_not(provider_url):
    url, provider = provider_url
    shape = load.Shape(500, 500, 500)  # 1,000 reserved and charged, against 3,000 a minute: three fit
    calls = {}
    fast = retry.Policy("honour-fast", max_attempts=3, honours_retry_after=True, jitter_s=0.1, deadline_s=2.0)
    for policy in (retry.NAIVE, fast):
        provider.control({"reset_quota": True, "clear_log": True})
        stream = [load.Workload("w2-ops-assistant", "internal", shape, policy, 0, 2.0, every_s=0.25, stream="t")]
        results = asyncio.run(load.run(url, {"w2-ops-assistant": "unused"}, stream))
        calls[policy.name] = (sum(len(r["attempts"]) for r in results), sum(r["served"] for r in results), len(results))
        assert len(provider.log) == calls[policy.name][0], "every attempt reached the provider"
    naive_calls, naive_served, offered = calls["naive"]
    honour_calls, honour_served, _ = calls["honour-fast"]
    assert offered == 8 and naive_served == honour_served == 3
    assert naive_calls >= 3 * honour_calls, calls
    assert honour_calls <= offered * 3
