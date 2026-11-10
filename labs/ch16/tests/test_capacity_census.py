"""The limiter-cache drill's callback: the census it writes, read from LiteLLM's own in-memory cache, and the
eviction the drill found, shown on that cache with no proxy."""

from __future__ import annotations

import json

import census_hooks
from litellm.caching.in_memory_cache import InMemoryCache


def test_a_kind_is_a_cache_key_with_its_ids_taken_out():
    assert census_hooks.kind("{api_key:4f1c9e}:tokens") == "{api_key}:tokens"
    assert census_hooks.kind("{model_per_key:4f1c9e:larkspur-chat}:tokens") == "{model_per_key}:tokens"
    assert census_hooks.kind("request_status:0f3a-77b2") == "request_status"
    assert census_hooks.kind("plain") == "plain"


def test_a_snapshot_counts_the_cache_and_reads_the_limiters_entries_with_their_time_left():
    cache = InMemoryCache(max_size_in_memory=5)
    cache.set_cache("{api_key:h}:window", "1793765330", ttl=60)
    cache.set_cache("{api_key:h}:tokens", 8000, ttl=60)
    cache.set_cache("request_status:1", "fail", ttl=400)
    line = census_hooks.snapshot(cache, "pre_call")
    assert line["event"] == "pre_call" and line["size"] == 3 and line["max"] == 5
    assert line["kinds"] == {"request_status": 1, "{api_key}:tokens": 1, "{api_key}:window": 1}
    value, left = line["limiter"]["{api_key:h}:tokens"]
    assert value == 8000 and 59.0 < left <= 60.0
    assert set(line["limiter"]) == {"{api_key:h}:tokens", "{api_key:h}:window"}


def test_a_full_cache_evicts_the_limiters_window_and_counter_before_the_request_statuses():
    """What the drill found on step 4's gateway, on LiteLLM's own cache: when it is full, the entries nearest their
    expiry go first, and a key's sixty-second window is nearer than a status kept for the alerting threshold plus
    100 seconds."""
    cache = InMemoryCache(max_size_in_memory=4)
    cache.set_cache("{api_key:h}:window", "1793765330", ttl=60)
    cache.set_cache("{api_key:h}:tokens", 8000, ttl=60)
    for i in range(4):
        cache.set_cache(f"request_status:{i}", "fail", ttl=400)
    line = census_hooks.snapshot(cache, "failure")
    assert line["limiter"] == {}
    assert line["kinds"] == {"request_status": 4}


def test_the_census_appends_a_line_a_call_and_never_fails_the_call(tmp_path, monkeypatch):
    path = tmp_path / "census.jsonl"
    hooks = census_hooks.Census(str(path))
    cache = InMemoryCache(max_size_in_memory=200)
    cache.set_cache("{api_key:h}:window", "1793765330", ttl=60)
    monkeypatch.setattr(census_hooks, "usage_cache", lambda: cache)
    hooks.write("pre_call")

    def moved():
        raise AttributeError("no internal_usage_cache")

    monkeypatch.setattr(census_hooks, "usage_cache", moved)
    hooks.write("success")
    first, second = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert first["size"] == 1 and first["limiter"]["{api_key:h}:window"][0] == "1793765330"
    assert second["event"] == "success" and "AttributeError" in second["error"]


def test_with_no_file_named_the_census_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(census_hooks.CENSUS_FILE, raising=False)
    monkeypatch.chdir(tmp_path)
    census_hooks.Census().write("pre_call")
    assert list(tmp_path.iterdir()) == []
