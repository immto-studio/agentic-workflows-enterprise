"""Step 5's committed results, as `capacity/run_drills.py` wrote them on 3 November 2026: the summary and the README's
tables, the contention numbers recomputed from every request, and what each drill found.

These tests read files; they start nothing. The drills need PostgreSQL and step 4's environment with Prisma, so they
run by hand (README, step 5), and what they found is held here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import run_drills
import summary

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-03" / "capacity"
DRILLS = json.loads((RESULTS / "drills.json").read_text(encoding="utf-8"))
CALC = json.loads((RESULTS / "calculator.json").read_text(encoding="utf-8"))
CACHE = json.loads((RESULTS / "limiter-cache.json").read_text(encoding="utf-8"))
STEP5 = "## Capacity and continuity (step 5)"
W2, W3 = "w2-ops-assistant", "w3-incident"


def jsonl(name: str) -> list[dict]:
    return [json.loads(line) for line in (RESULTS / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_summary_is_what_the_summary_writer_makes_from_the_committed_files():
    written = (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert written == summary.render(DRILLS, CALC, summary.load_continuity(), summary.load_cache(RESULTS))


def test_the_readmes_step_5_tables_are_the_summarys():
    readme = (LAB / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = (RESULTS / "summary.md").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    section, rows = "", []
    for line in readme.splitlines():
        if line.startswith("## "):
            section = line
        if section == STEP5 and line.startswith("|") and not line.startswith("|---"):
            rows.append(line)
    assert len(rows) >= 40
    for row in rows:
        assert row in lines, row


def test_the_contention_numbers_come_from_the_requests():
    requests = jsonl("contention-requests.jsonl")
    assert len(DRILLS["contention"]) == len(run_drills.CONTENTION) * run_drills.ROUNDS
    for row in DRILLS["contention"]:
        mine = [r for r in requests if r["limit"] == row["name"] and r["round"] == row["round"]]
        inside = [r for r in mine if run_drills.BURST[0] <= r["t"] < run_drills.BURST[1]]
        assert run_drills.describe([r for r in inside if r["stream"] == "incident"]) == row["w3_in_the_burst"]
        assert run_drills.describe([r for r in mine if r["stream"] == "incident"]) == row["w3_whole_run"]
        assert run_drills.describe([r for r in inside if r["stream"] == "burst"]) == row["w2_burst"]


def rounds(name: str) -> list[dict]:
    found = [c for c in DRILLS["contention"] if c["name"] == name]
    assert len(found) == run_drills.ROUNDS, name
    return found


def test_a_tokens_per_minute_limit_on_each_key_keeps_w3s_share_and_the_others_dont():
    for row in rounds("tokens per minute per key"):
        w3 = row["w3_in_the_burst"]
        assert w3["served"] == w3["requests"] and w3["first_attempt"] >= w3["requests"] - 1, row["round"]
        assert w3["wait_max_s"] < 2.0, row["round"]
    for row in rounds("tokens per minute per key, with headroom"):
        w3 = row["w3_in_the_burst"]
        assert w3["served"] == w3["requests"] == w3["first_attempt"], row["round"]
        assert w3["wait_max_s"] < 1.0, row["round"]
    for name in ("requests per minute alone", "deployment limits"):
        rows = rounds(name)
        first = sum(r["w3_in_the_burst"]["first_attempt"] for r in rows)
        assert first <= sum(r["w3_in_the_burst"]["requests"] for r in rows) / 2, name
        assert all(r["w3_in_the_burst"]["refused_by"].get("the provider's quota", 0) > 5 for r in rows), name
    assert all(r["w2_burst"]["refused_by"].get("the key's tokens per minute", 0) > 0
               for r in rounds("tokens per minute per key"))


def test_under_the_key_limits_the_burst_spent_w2s_request_rate_and_the_key_stopped_counting():
    """The key refused the burst at its start, every refusal counted against chapter 5's requests a minute, and
    chapter 5's limit refused W2 until those requests left its window; by then the key refused nothing, and the
    burst's last requests went through together, more than a minute's share in the headroom rounds. The provider
    refused W3 only after the burst."""
    requests = jsonl("contention-requests.jsonl")
    for name in ("tokens per minute per key", "tokens per minute per key, with headroom"):
        for row in rounds(name):
            mine = [r for r in requests if r["limit"] == name and r["round"] == row["round"]]
            w2 = [a for r in mine if r["workflow"] == W2 for a in r["attempts"]]
            by_key = [a[0] for a in w2 if a[2] == "the key's tokens per minute"]
            assert by_key and max(by_key) < run_drills.BURST[0] + 15, (name, row["round"])
            assert sum(1 for a in w2 if a[2] == "chapter 5's requests per minute") > 100, (name, row["round"])
            assert row["w2_steady_in_the_burst"]["served"] <= row["w2_steady_in_the_burst"]["requests"] / 2
            w3_refused = [a[0] for r in mine if r["workflow"] == W3 for a in r["attempts"]
                          if a[2] == "the provider's quota"]
            assert all(t >= run_drills.BURST[1] for t in w3_refused), (name, row["round"])
            if name.endswith("headroom"):
                late = sum(r["charge"] for r in mine if r["stream"] == "burst" and r["served"]
                           and 60.0 <= r["served_at"] < 120.0)
                assert late > row["tpm_limit"][W2], (row["round"], late)


def cache_round(gateway: str, limit: str) -> dict:
    return next(r for r in CACHE["rounds"] if r["gateway"] == gateway and r["name"] == limit)


PER_KEY = ("tokens per minute per key", "tokens per minute per key, with headroom")


def test_the_limiter_cache_numbers_come_from_the_requests():
    requests = jsonl("limiter-cache-requests.jsonl")
    assert [(r["gateway"], r["name"]) for r in CACHE["rounds"]] == [(c["gateway"], c["limit"]) for c in run_drills.CENSUS]
    for row in CACHE["rounds"]:
        mine = [r for r in requests if r["gateway"] == row["gateway"] and r["limit"] == row["name"]]
        inside = [r for r in mine if run_drills.BURST[0] <= r["t"] < run_drills.BURST[1]]
        assert run_drills.describe([r for r in inside if r["stream"] == "incident"]) == row["w3_in_the_burst"]
        assert run_drills.describe([r for r in mine if r["stream"] == "incident"]) == row["w3_whole_run"]
        assert run_drills.describe([r for r in inside if r["stream"] == "burst"]) == row["w2_burst"]
        again = run_drills.census_metrics([], {}, 0.0, mine)
        assert again["w2_burst_tokens_served_60_to_120_s"] == row["cache"]["w2_burst_tokens_served_60_to_120_s"]
        for workflow in (W2, W3):
            refused = [a[0] for r in mine if r["workflow"] == workflow for a in r["attempts"]
                       if a[2] == "the key's tokens per minute"]
            assert len(refused) == row["cache"]["keys"][workflow]["key_refusals"], (row["gateway"], workflow)


def test_on_step_4s_gateway_the_request_statuses_fill_the_cache_and_evict_the_keys_windows():
    for limit in PER_KEY:
        cache = cache_round("step 4's", limit)["cache"]
        assert cache["errors"] == 0 and cache["largest"] == cache["entries_max"] == 200
        assert cache["full_at_s"] < run_drills.BURST[1]
        kinds = cache["kinds_when_largest"]
        assert max(kinds, key=kinds.get) == "request_status" and kinds["request_status"] > 150
        w2 = cache["keys"][W2]
        assert cache["full_at_s"] <= w2["window_evicted_s"] < cache["full_at_s"] + 5, limit
        assert w2["last_key_refusal_s"] < w2["window_evicted_s"], "the key refused nothing after its window went"
    headroom = cache_round("step 4's", PER_KEY[1])
    assert headroom["cache"]["w2_burst_tokens_served_60_to_120_s"] > headroom["tpm_limit"][W2]


def test_without_the_alerts_the_cache_holds_the_windows_and_the_key_keeps_counting():
    for limit in PER_KEY:
        row = cache_round("step 4's without alerts", limit)
        cache = row["cache"]
        assert cache["errors"] == 0 and cache["full_at_s"] is None and cache["largest"] <= 10
        assert "request_status" not in cache["kinds_when_largest"]
        assert all(k["evictions"] == 0 for k in cache["keys"].values())
        assert cache["keys"][W2]["last_key_refusal_s"] > 60, "W2's key refused in its second minute too"
        assert cache["w2_burst_tokens_served_60_to_120_s"] <= row["tpm_limit"][W2]
        assert row["w3_in_the_burst"]["first_attempt"] == row["w3_in_the_burst"]["requests"]
        assert row["provider"]["by_workflow"][W3]["refused"] == 0


def test_the_deployment_limits_count_too_late_to_stop_the_providers_429s():
    for row in rounds("deployment limits"):
        assert row["provider"]["by_workflow"][W2]["refused"] > 20, row["round"]
        refused = row["w3_in_the_burst"]["refused_by"]
        assert refused.get("the deployment's tokens per minute", 0) == 0, row["round"]
        assert refused.get("the provider's quota", 0) > refused.get("the deployment's parallel requests", 0)


def test_naive_retries_multiply_the_load_and_serve_no_more():
    direct = {r["policy"]: r for r in DRILLS["client_retries"] if r["through"] == "the provider directly"}
    assert direct["naive"]["served"] <= direct["none"]["served"] < direct["honour"]["served"]
    assert direct["naive"]["load_over_offered"] > 5 and direct["honour"]["load_over_offered"] == 1.0
    assert direct["naive"]["calls_per_success"] > 3 * direct["honour"]["calls_per_success"]
    gateway = {r["policy"]: r for r in DRILLS["client_retries"] if r["through"] == "step 4's gateway"}
    assert gateway["naive"]["refused_by"].get("chapter 5's requests per minute", 0) > 0
    assert gateway["naive"]["calls"] > 3 * gateway["honour"]["calls"]


def test_the_router_waits_for_retry_after_only_alone_and_only_up_to_a_minute():
    cases = {r["case"]: r for r in DRILLS["router_retries"]}
    alone = cases["one deployment in the group, Retry-After 5 s"]
    assert all(5.0 <= g <= 6.0 for g in alone["gaps_s"]) and alone["status"] == 200
    past = cases["one deployment in the group, Retry-After 90 s"]
    assert all(g < 3.0 for g in past["gaps_s"]) and past["status"] == 200
    pair = cases["two deployments in the group, the first throttled, Retry-After 5 s"]
    assert pair["gaps_s"][0] < 0.5 and pair["served_by"] == "t2-pair"
    assert [a["deployment"] for a in pair["attempts"]] == ["t1", "t2"]


def test_the_gateways_own_time_is_milliseconds_against_the_providers():
    rows = {r["setup"]: r for r in DRILLS["latency"]}
    baseline = rows.pop("the provider alone, no gateway")
    assert baseline["litellm_reports_ms"]["median"] is None, "no gateway, no LiteLLM header"
    for setup, row in rows.items():
        assert row["answered"] == row["calls"], setup
        assert row["gateway_ms"]["median"] > baseline["gateway_ms"]["median"], setup
        assert row["gateway_ms"]["median"] < row["provider_ms"]["median"] / 2, setup
        if row["concurrency"] == 1:
            assert row["gateway_ms"]["median"] < 25, setup


def mode(name: str) -> dict:
    return next(m for m in DRILLS["outage"] if m["mode"] == name)


def test_each_failure_mode_is_cooled_down_after_allowed_fails_and_probed_again_a_cooldown_later():
    for row in DRILLS["outage"]:
        first = row["cycles"][0]
        assert row["allowed_fails"] + 1 <= first["failures"] <= row["allowed_fails"] + 3, row["mode"]
        assert len(row["cycles"]) >= 2, row["mode"]
        gap = row["cycles"][1]["first_failure_s"] - first["last_failure_s"]
        assert row["cooldown_time_s"] - 2 <= gap <= row["cooldown_time_s"] + 8, (row["mode"], gap)
        assert 0 < row["primary_served_again_after_heal_s"] <= row["cooldown_time_s"] + 5, row["mode"]
    assert mode("timeout")["sent_to_the_failing_primary_s"] > 5, "each timed-out call held its caller 5 s"


def test_w2_got_its_fallback_and_w3_its_error_inside_each_manifests_regions():
    errors = {"5xx": "503", "timeout": "408", "connection": "500"}
    for row in DRILLS["outage"]:
        assert set(row["w2"]["statuses"]) == {"200"} and set(row["w2"]["served_by"]) == {"fallback"}, row["mode"]
        assert set(row["w2_regions"]) <= {"ca-central-1", "us-east-2"}, row["mode"]
        assert set(row["w3_regions"]) == {"ca-central-1"}, row["mode"]
        assert "200" not in row["w3"]["statuses"], row["mode"]
        assert set(row["w3"]["statuses"]) <= {errors[row["mode"]], "429"}, row["mode"]
        assert row["w3"]["kinds"].get("the router's cooldown", 0) > 10, row["mode"]
        assert row["w3_failed_lines_with_fallback_disabled"] == row["w3_failed_lines"] > 0, row["mode"]


def test_what_a_run_in_flight_saw():
    for row in DRILLS["outage"]:
        w2 = row["runs"]["w2_in_flight"]
        served = [line for line in row["run_lines"]["w2_in_flight"] if line["event"] == "call"]
        assert w2["answered"] and served[-1]["deployment"] == "fallback" and served[-1]["region"] == "us-east-2"
        assert row["runs"]["w3_during_cooldown"]["raised"] == "HTTPStatusError 429", row["mode"]
    assert mode("5xx")["runs"]["w3_in_flight"]["outcome"] == "unavailable"
    assert mode("connection")["runs"]["w3_in_flight"]["outcome"] == "unavailable"
    assert mode("timeout")["runs"]["w3_in_flight"]["raised"] == "HTTPStatusError 408"


def test_with_its_database_stopped_the_gateway_serves_cached_keys_and_then_refuses():
    db = DRILLS["database"]
    assert db["answered_from_the_key_cache"] > 30 and 40 <= db["the_cache_answered_until_s"] <= 75
    assert db["first_refusal_sent_at_s"] >= 40 and db["refusals"] > 10
    unreachable = "Service Unavailable, the authentication database is temporarily unreachable. Please retry shortly."
    assert db["messages_while_down"][unreachable] >= db["refusals"] - 2
    assert db["refusal_held_its_caller_s"]["median"] > 5
    assert set(db["after_restart"]) == {"200"} and db["first_call_answered_after_restart_sent_s"] < 10
    outside = db["cost_of_answered_calls_usd"] - db["of_which_while_down_usd"]
    assert db["spend_counted_usd"] <= outside * 1.01, "the spend of the calls answered while it was down never arrived"


def test_the_database_numbers_come_from_its_calls():
    calls = jsonl("database-events.jsonl")
    db = DRILLS["database"]
    mine = run_drills.database_metrics(calls, db["stopped_for_s"], [], 0.0, 0.0, 0.0, 0.0)
    for key in ("calls_before", "calls_while_down", "while_down", "answered_from_the_key_cache",
                "the_cache_answered_until_s", "first_refusal_sent_at_s", "refusals", "refusal_held_its_caller_s",
                "answered_after_waiting_for_the_database", "messages_while_down", "after_restart",
                "first_call_answered_after_restart_sent_s"):
        assert mine[key] == db[key], key


def test_no_path_key_or_password_of_this_machine_in_the_results():
    pattern = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?![\\/])|Users[\\/]|sk-[A-Za-z0-9]{8}|postgresql://[^<]")
    for path in RESULTS.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), (path.name, pattern.search(text).group(0))
