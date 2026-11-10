"""Step 5b's committed results, as `capacity/run_5b.py` wrote them on 4 November 2026: the summary and the README's
tables, the store's probe, the contention numbers recomputed from every request, the limiter's cache, the store
stopped and the alert, the outage drill on both configs, the processes stopped, and the continuity rows step 5b
changes.

These tests read files; they start nothing. The drills need PostgreSQL, Prisma and Garnet, so they run by hand
(README, step 5b), and what they found is held here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import garnet
import run_5b
import run_drills
import summary
import summary_5b

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-04" / "capacity"
PROBE = json.loads((RESULTS / "store-probe.json").read_text(encoding="utf-8"))
STORE = json.loads((RESULTS / "store.json").read_text(encoding="utf-8"))
OUTAGE = json.loads((RESULTS / "outage.json").read_text(encoding="utf-8"))
STEP5B = "## The store, the retries and W3's fallback (step 5b)"
W2, W3 = "w2-ops-assistant", "w3-incident"
PER_KEY = ("tokens per minute per key", "tokens per minute per key, with headroom")


def jsonl(name: str) -> list[dict]:
    return [json.loads(line) for line in (RESULTS / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_summary_is_what_the_summary_writer_makes_from_the_committed_files():
    written = (RESULTS / "summary-5b.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert written == summary_5b.render(*summary_5b.load(RESULTS))


def test_the_readmes_step_5b_tables_are_the_summarys():
    readme = (LAB / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = (RESULTS / "summary-5b.md").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    section, rows = "", []
    for line in readme.splitlines():
        if line.startswith("## "):
            section = line
        if section == STEP5B and line.startswith("|") and not line.startswith("|---"):
            rows.append(line)
    assert len(rows) >= 20
    for row in rows:
        assert row in lines, row


def test_the_fetch_record_is_the_pin():
    fetched = json.loads((RESULTS / "garnet-fetch.json").read_text(encoding="utf-8"))
    assert (fetched["version"], fetched["asset"], fetched["sha256"], fetched["bytes"]) == \
        (garnet.VERSION, garnet.ASSET, garnet.SHA256, garnet.SIZE)
    assert fetched["published_sha256_matches"] is True and fetched["license"].startswith("MIT")
    signed = fetched["authenticode_garnet_server_exe"]
    assert signed["status"] == "Valid" and "Microsoft Corporation" in signed["signer"] and signed["timestamped"]
    assert fetched["authenticode_lua54_dll"]["status"] == "NotSigned"


def test_garnet_runs_litellms_scripts_as_redis_does_and_runs_them_whole_only_in_transaction_mode():
    modes = {m["transaction_mode"]: m for m in PROBE["modes"]}
    limit = PROBE["race"]["limit"]
    for mode in modes.values():
        assert mode["answers"] == run_5b.redis_answers() and all(mode["as_redis_answers"].values())
        assert mode["server"] == {"redis_version": "7.4.3", "garnet_version": garnet.VERSION}
        assert all(t["errors"] == 0 and t["counter_after"] == limit for t in mode["trials"])
    assert [t["admitted"] for t in modes[True]["trials"]] == [limit] * PROBE["race"]["trials"]
    assert any(t["admitted"] > limit for t in modes[False]["trials"]), "without the transaction mode, past the limit"


def test_the_contention_numbers_come_from_the_requests():
    requests = jsonl("store-contention-requests.jsonl")
    assert len(STORE["contention"]) == len(run_drills.CONTENTION) * run_drills.ROUNDS
    for row in STORE["contention"]:
        mine = [r for r in requests if r["limit"] == row["name"] and r["round"] == row["round"]]
        inside = [r for r in mine if run_drills.BURST[0] <= r["t"] < run_drills.BURST[1]]
        assert run_drills.describe([r for r in inside if r["stream"] == "incident"]) == row["w3_in_the_burst"]
        assert run_drills.describe([r for r in mine if r["stream"] == "incident"]) == row["w3_whole_run"]
        assert run_drills.describe([r for r in inside if r["stream"] == "burst"]) == row["w2_burst"]
        assert row["store_alerts"] == [], "the store answered all round, and the alert stayed quiet"


def store_rounds(name: str) -> list[dict]:
    found = [c for c in STORE["contention"] if c["name"] == name]
    assert len(found) == run_drills.ROUNDS, name
    return found


def test_on_the_store_the_keys_limits_hold_through_step_4s_alerts():
    """With the windows in the store, W3 is served at once in the burst, the provider refuses W3 nothing after it,
    and W2's key goes on refusing in its second minute, which step 5 found only without the alerts."""
    requests = jsonl("store-contention-requests.jsonl")
    for name in PER_KEY:
        for row in store_rounds(name):
            w3 = row["w3_in_the_burst"]
            assert w3["served"] == w3["requests"] == w3["first_attempt"], (name, row["round"])
            mine = [r for r in requests if r["limit"] == name and r["round"] == row["round"]]
            after = [a for r in mine if r["workflow"] == W3 for a in r["attempts"]
                     if a[2] == "the provider's quota" and a[0] >= run_drills.BURST[1]]
            assert after == [], (name, row["round"])
            second = [a for r in mine if r["workflow"] == W2 for a in r["attempts"]
                      if a[2] == "the key's tokens per minute" and 60.0 <= a[0] < 120.0]
            assert second, (name, row["round"])
    for row in store_rounds(PER_KEY[1]):
        late = sum(r["charge"] for r in requests if r["limit"] == PER_KEY[1] and r["round"] == row["round"]
                   and r["stream"] == "burst" and r["served"] and 60.0 <= r["served_at"] < 120.0)
        assert late <= row["tpm_limit"][W2], ("the burst held to W2's share in its second minute", row["round"])


def test_the_limiter_cache_rounds_on_the_store():
    requests = jsonl("store-cache-requests.jsonl")
    assert [(r["gateway"], r["name"]) for r in STORE["cache"]] == [(c["gateway"], c["limit"]) for c in run_5b.STORE_CENSUS]
    for row in STORE["cache"]:
        mine = [r for r in requests if r["gateway"] == row["gateway"] and r["limit"] == row["name"]]
        inside = [r for r in mine if run_drills.BURST[0] <= r["t"] < run_drills.BURST[1]]
        assert run_drills.describe([r for r in inside if r["stream"] == "incident"]) == row["w3_in_the_burst"]
        store = row["store"]
        assert store["store_errors"] <= 2 and set(store["store_error_kinds"]) <= {"TimeoutError"}, \
            "at most a census reading past its own 0.4 s limit"
        assert row["store_alerts"] == [], "the watch's pings all answered"
        assert store["keys"][W2]["store_evictions"] == 0 and store["keys"][W2]["store_windows_seen"] >= 2
        assert row["cache"]["keys"][W2]["last_key_refusal_s"] > 60, "W2's key refused in its second minute"
        assert row["provider"]["by_workflow"][W3]["refused"] == 0
        if row["gateway"] == "step 4's with the store":
            kinds = row["cache"]["kinds_when_largest"]
            assert row["cache"]["largest"] == row["cache"]["entries_max"] == 200, "the alerts still fill the memory"
            assert max(kinds, key=kinds.get) == "request_status"
        if row["name"] == PER_KEY[1]:
            assert row["cache"]["w2_burst_tokens_served_60_to_120_s"] <= row["tpm_limit"][W2]


def stopped(name: str) -> dict:
    return next(r for r in STORE["stopped"] if r["name"] == name)


def test_with_the_store_stopped_by_default_the_limiter_carries_on_from_a_memory_with_no_window():
    r = stopped("LiteLLM's default")
    before, down, after = (r["phases"][p] for p in ("before", "while down", "after"))
    assert r["answers_503"] == 0
    assert before[W2]["refused_by"]["the key's tokens per minute"] > 50
    assert "the key's tokens per minute" not in down[W2]["refused_by"], "W2's key refused nothing while it was down"
    assert before[W3]["refused_by"] == {} and down[W3]["refused_by"].get("the provider's quota", 0) > 0
    assert after[W3]["refused_by"].get("the provider's quota", 0) > 0
    assert r["w2_window_in_memory_while_down"] == 0 and r["memory_largest_while_down"] == 200


def test_failing_closed_the_gateway_refuses_every_keyed_call_until_the_store_is_back():
    r = stopped("failing closed")
    down = r["phases"]["while down"]
    assert r["first_503_after_the_stop_s"] < 10 and r["answers_503"] > 50
    assert set(down[W3]["statuses"]) == {"503"} and down[W3]["incidents_first_attempt"] == 0
    assert down["w2_burst_tokens_served"] == 0
    assert r["last_503_s"] - r["started_at_s"] < 15, "within seconds of the store's return"
    assert all("could not be verified against Redis" in words for words in r["words_503"])


def test_the_alert_reached_the_platforms_on_call_both_ways_in_each_round():
    for r in STORE["stopped"]:
        assert [a["event"] for a in r["alerts"]] == ["limiter_store_unreachable", "limiter_store_reachable"], r["name"]
        down, up = r["alerts"]
        assert down["forwarded_to"] == up["forwarded_to"] == ["platform.oncall@larkspur.example"]
        assert 0 < down["received_s"] - r["stopped_at_s"] < 10 and 0 < up["received_s"] - r["started_at_s"] < 10
        assert r["log"]["the circuit breaker opened"] >= 1 and r["unanswered"] == []


def test_every_process_the_drills_started_was_stopped():
    for part, pids in STORE["processes"].items():
        assert pids["stopped"] and pids["left_running"] == {}, part
        assert set(pids["stopped"]) == {"receiver", "proxy", "fake primary", "fake self-hosted", "store"}, part
    for cfg in OUTAGE["configs"]:
        assert cfg["stopped_pids"] and cfg["left_running"] == {}, cfg["name"]
    assert len(PROBE["stopped_pids"]) == 2 and all(PROBE["stopped_pids"])


def config(name: str) -> dict:
    return next(c for c in OUTAGE["configs"] if c["config"] == name)


def test_with_its_fallback_w3_is_served_in_canada_through_every_failure_mode_and_w2_as_before():
    for row in config("litellm.outage-canada.yaml")["modes"]:
        assert set(row["w3"]["statuses"]) == {"200"} and set(row["w3"]["served_by"]) == {"self-hosted"}, row["mode"]
        assert set(row["w3_regions"]) == {"ca-central-1"}, row["mode"]
        assert row["w3_requests_seen_by"]["fallback, us-east-2"] == 0, "no W3 call left Canada"
        assert row["w3_fallback_in_jurisdiction_lines"] > 0
        assert set(row["w2"]["statuses"]) == {"200"} and set(row["w2"]["served_by"]) == {"fallback"}, row["mode"]
        assert row["w2_requests_seen_by"]["self-hosted, ca-central-1"] == 0, "W2's chain is chapter 5's"
        for run in ("w3_in_flight", "w3_during_cooldown"):
            assert row["runs"][run]["outcome"] == "answer" and not row["runs"][run]["waits"], (row["mode"], run)
        assert row["runs"]["w2_in_flight"]["answered"]


def test_on_step_5s_config_w3_waits_out_the_cooldown_and_ends_a_run_it_cannot_wait_for():
    errors = {"5xx": "the gateway answered 503", "timeout": "408 with no wait to wait out",
              "connection": "the gateway answered 500"}
    for row in config("litellm.outage.yaml")["modes"]:
        flight, cooldown = row["runs"]["w3_in_flight"], row["runs"]["w3_during_cooldown"]
        assert flight["raised"] is None and flight["outcome"] == "unavailable", row["mode"]
        assert flight["unavailable"] == errors[row["mode"]], row["mode"]
        assert cooldown["raised"] is None and cooldown["outcome"] == "answer", row["mode"]
        assert [w["status"] for w in cooldown["waits"]] == [429, 429] and all(w["asked_s"] == 30 for w in cooldown["waits"])
        assert cooldown["seconds"] < cooldown["time_budget_s"]
        assert set(row["w3_regions"]) == {"ca-central-1"} and row["w3_requests_seen_by"]["fallback, us-east-2"] == 0
        assert set(row["w2"]["served_by"]) == {"fallback"}


def resolve(data, path: str):
    value = data
    for part in path.replace("]", "").replace("[", ".").split("."):
        value = value[int(part)] if part.isdigit() else value[part]
    return value


def test_the_continuity_rows_step_5b_changes_cite_only_what_its_drills_found():
    files = {"store": STORE, "probe": PROBE, "outage 5b": OUTAGE}
    printed = (RESULTS / "summary-5b.md").read_text(encoding="utf-8")
    rows = summary_5b.load_continuity()
    assert [r["component"] for r in rows] == ["the gateway", "Redis"]
    for row in rows:
        text = row["evidence"] + " " + row["gap"]
        for source in row["sources"]:
            if "summary" in source:
                assert source["summary"] in printed and source["summary"] in text, (row["component"], source)
            else:
                value = resolve(files[source["drill"]], source["path"])
                assert (source.get("shown") or summary.num(value)) in row["evidence"], (row["component"], source)


def test_no_path_key_or_password_of_this_machine_in_the_results():
    pattern = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?![\\/])|Users[\\/]|sk-[A-Za-z0-9]{8}|postgresql://[^<]")
    for path in RESULTS.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), (path.name, pattern.search(text).group(0))
        assert "<secret>" not in text, path.name
