"""Step 5b's summary: every table the README's step 5b section prints, written from the committed files, with step 5's
numbers beside the store's where the two drills compare.

Chapter 16, step 5b. `run_5b.py` writes `store-probe.json`, `store.json`, `outage.json` and the requests and events
behind them to `results/<date>/capacity/`; this writes `summary-5b.md` beside them from those files and from step 5's
committed results (`results/2026-11-03/capacity/`), the same bytes each time.

Run (from labs/ch16):  python capacity/run_5b.py --summarize results/<date>/capacity
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from summary import counts, num, table

HERE = Path(__file__).resolve().parent
STEP5 = HERE.parent / "results" / "2026-11-03" / "capacity"
W2, W3 = "w2-ops-assistant", "w3-incident"
BURST_END = 75.0
PER_KEY = ("tokens per minute per key", "tokens per minute per key, with headroom")


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def span(values: list[float]) -> str:
    """'a' when every round gave the same, else 'a to b'."""
    if not values:
        return ""
    low, high = min(values), max(values)
    return num(low) if low == high else f"{num(low)} to {num(high)}"


# --- what each round's requests say, the same way for step 5's and for the store's --------------------------------

def round_facts(requests: list[dict[str, Any]], row: dict[str, Any]) -> dict[str, Any]:
    """For one round: W3's requests in the burst, the provider's refusals of W3 after the burst, the key's refusals
    of W2 in its second minute, and the burst's tokens served between 60 and 120 s."""
    w3 = row["w3_in_the_burst"]
    key_refusals = [a[0] for r in requests if r["workflow"] == W2 for a in r["attempts"]
                    if a[2] == "the key's tokens per minute"]
    return {"w3_served": w3["served"], "w3_requests": w3["requests"], "w3_first": w3["first_attempt"],
            "w3_longest": w3["wait_max_s"] or 0.0,
            "w3_provider_after": sum(1 for r in requests if r["workflow"] == W3 for a in r["attempts"]
                                     if a[2] == "the provider's quota" and a[0] >= BURST_END),
            "w2_key_second_minute": sum(1 for t in key_refusals if 60.0 <= t < 120.0),
            "w2_key_last": max(key_refusals) if key_refusals else None,
            "w2_burst_60_120": sum(r["charge"] for r in requests if r["stream"] == "burst" and r["served"]
                                   and 60.0 <= r["served_at"] < 120.0)}


def by_round(rows: list[dict[str, Any]], requests: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    out = {}
    for row in rows:
        mine = [r for r in requests if r["limit"] == row["name"] and r["round"] == row.get("round", 1)]
        out[(row["name"], row.get("round", 1))] = round_facts(mine, row)
    return out


def beside(limit: str, facts: list[dict[str, Any]]) -> list[Any]:
    served = sum(f["w3_served"] for f in facts)
    asked = sum(f["w3_requests"] for f in facts)
    return [f"{served} of {asked}", sum(f["w3_first"] for f in facts), max(f["w3_longest"] for f in facts),
            span([f["w3_provider_after"] for f in facts]), span([f["w2_key_second_minute"] for f in facts]),
            span([f["w2_burst_60_120"] for f in facts])]


# --- the sections ---------------------------------------------------------------------------------------------------

def probe(p: dict[str, Any]) -> list[str]:
    race = p["race"]
    out = ["## The store's probe", "",
           f"LiteLLM {p['versions']['litellm']}'s rate-limiter scripts, each run once against Garnet "
           f"{p['versions']['garnet']} with known inputs and set against what Redis answers, then {race['calls']:,} "
           f"check-and-increments at once over {race['connections']} connections against a limit of {race['limit']}, "
           f"{race['trials']} times in each mode. Redis admits exactly {race['limit']}.", ""]
    rows = []
    for m in p["modes"]:
        trials = m["trials"]
        rows.append(["on" if m["transaction_mode"] else "off",
                     f"{sum(m['as_redis_answers'].values())} of {len(m['as_redis_answers'])}",
                     ", ".join(str(t["admitted"]) for t in trials), ", ".join(str(t["counter_after"]) for t in trials),
                     sum(t["errors"] for t in trials)])
    out += table(["Lua transaction mode", "Script steps answered as Redis answers", "Admitted, each trial",
                  "Counter after, each trial", "Errors"], rows)
    return out


def contention(store: dict[str, Any], requests: list[dict[str, Any]], step5: dict[str, Any],
               step5_requests: list[dict[str, Any]]) -> list[str]:
    rows = store["contention"]
    out = ["", "## Contention on the store", "",
           f"Step 5's drill as it ran: a quota of {store['quota_tpm']:,} tokens a minute, W3 every 6 s and W2 every 3 s "
           f"for {num(store['duration_s'])} s, W2's burst from {num(store['burst'][0])} to {num(store['burst'][1])} s, "
           "each limit three times, the store emptied before each round. W3's requests made during the burst:", ""]
    out += table(["Limit", "Round", "Requests", "Served", "On the first attempt", "Attempts a request",
                  "Median wait (s)", "Longest wait (s)", "What refused W3's attempts"],
                 [[c["name"], c["round"], c["w3_in_the_burst"]["requests"], c["w3_in_the_burst"]["served"],
                   c["w3_in_the_burst"]["first_attempt"], c["w3_in_the_burst"]["attempts_per_request"],
                   c["w3_in_the_burst"]["wait_median_s"], c["w3_in_the_burst"]["wait_max_s"],
                   counts(c["w3_in_the_burst"]["refused_by"])] for c in rows])
    out += ["", "W2 during the burst, and the provider over the whole run:", ""]

    def provider(c: dict[str, Any], workflow: str) -> int:
        return c["provider"]["by_workflow"].get(workflow, {}).get("refused", 0)

    out += table(["Limit", "Round", "W2's burst requests", "Served", "W2's questions served", "W3 served, whole run",
                  "Provider refusals, W2", "Provider refusals, W3", "What refused W2's burst"],
                 [[c["name"], c["round"], c["w2_burst"]["requests"], c["w2_burst"]["served"],
                   f"{c['w2_steady_in_the_burst']['served']} of {c['w2_steady_in_the_burst']['requests']}",
                   f"{c['w3_whole_run']['served']} of {c['w3_whole_run']['requests']}", provider(c, W2), provider(c, W3),
                   counts(c["w2_burst"]["refused_by"])] for c in rows])
    mine, theirs = by_round(rows, requests), by_round(step5["contention"], step5_requests)
    out += ["", "Beside step 5's three rounds of each limit, which had no store: W3 in the burst, the provider's refusals of "
                "W3 after the burst (from 75 s), the key's refusals of W2 in its second minute (60 to 120 s), and the "
                "burst's tokens served from 60 to 120 s, in each round:", ""]
    lines = []
    for limit in dict.fromkeys(c["name"] for c in rows):
        for label, found in (("step 5, no store", theirs), ("step 5b, the store", mine)):
            facts = [f for (name, _), f in found.items() if name == limit]
            lines.append([limit, label, *beside(limit, facts)])
    out += table(["Limit", "Drill", "W3 served in the burst", "On the first attempt", "Longest wait (s)",
                  "Provider refusals of W3 after the burst", "The key's refusals of W2, 60 to 120 s",
                  "W2's burst tokens served, 60 to 120 s"], lines)
    return out


def cache(store: dict[str, Any], step5_cache: dict[str, Any]) -> list[str]:
    out = ["", "## The limiter's cache on the store", "",
           "Each per-key limit once more with the census, which reads the proxy's in-memory cache at every call and the "
           "store every half second; step 5's rounds, with no store, beside them. Times in seconds from the start of the "
           "round.", ""]
    rows = []
    for c in step5_cache["rounds"]:
        k2 = c["cache"]["keys"][W2]
        rows.append([c["gateway"], c["name"], f"{c['cache']['largest']} of {c['cache']['entries_max']}",
                     c["cache"]["full_at_s"], k2["window_evicted_s"], "no store",
                     f"{k2['key_refusals']}, {num(k2['last_key_refusal_s'])}" if k2["key_refusals"] else "0",
                     c["cache"]["w2_burst_tokens_served_60_to_120_s"],
                     f"{c['w3_in_the_burst']['served']} of {c['w3_in_the_burst']['requests']}, "
                     f"{c['w3_in_the_burst']['first_attempt']}",
                     c["provider"]["by_workflow"].get(W3, {}).get("refused", 0)])
    for c in store["cache"]:
        k2, s2 = c["cache"]["keys"][W2], c["store"]["keys"][W2]
        rows.append([c["gateway"], c["name"], f"{c['cache']['largest']} of {c['cache']['entries_max']}",
                     c["cache"]["full_at_s"], k2["window_evicted_s"],
                     f"{s2['store_evictions']} of {s2['store_windows_seen']} windows" if s2["store_windows_seen"] else "",
                     f"{k2['key_refusals']}, {num(k2['last_key_refusal_s'])}" if k2["key_refusals"] else "0",
                     c["cache"]["w2_burst_tokens_served_60_to_120_s"],
                     f"{c['w3_in_the_burst']['served']} of {c['w3_in_the_burst']['requests']}, "
                     f"{c['w3_in_the_burst']['first_attempt']}",
                     c["provider"]["by_workflow"].get(W3, {}).get("refused", 0)])
    out += table(["Gateway", "Limit", "Most entries in memory", "Memory full at (s)", "W2's window gone from memory at (s)",
                  "W2's windows evicted from the store", "The key's refusals of W2, the last at (s)",
                  "W2's burst tokens served from 60 to 120 s", "W3 in the burst, served and on the first attempt",
                  "Provider refusals, W3"], rows)
    return out


def latency(store: dict[str, Any], step5: dict[str, Any]) -> list[str]:
    if "latency" not in store:
        return []
    theirs = next(r for r in step5["latency"] if r["setup"] == "step 4's gateway, W2's key with a tpm_limit")
    out = ["", "## The gateway's own latency on the store", "",
           "Step 5's setup, sixty single calls with W2's key under a tpm_limit that refuses nothing, beside step 5's row:",
           ""]
    out += table(["Setup", "Calls", "At once", "Client, median (ms)", "Provider, median (ms)",
                  "Client less provider, median (ms)", "Client less provider, 95th percentile (ms)",
                  "LiteLLM's own figure, median (ms)"],
                 [[r["setup"], r["calls"], r["concurrency"], r["client_ms"]["median"], r["provider_ms"]["median"],
                   r["gateway_ms"]["median"], r["gateway_ms"]["p95"], r["litellm_reports_ms"]["median"]]
                  for r in (theirs, store["latency"])])
    return out


def stopped(store: dict[str, Any]) -> list[str]:
    if "stopped" not in store:
        return []
    out = ["", "## The store stopped", "",
           f"One round of the exact division (W2's key 75,000 tokens a minute, W3's 25,000) on step 4's gateway with the "
           f"store, its budget alerts on and the census reading both caches. The store was stopped "
           f"{num(store['stop_at_s'] - store['burst'][0])} s into W2's burst, at {num(store['stop_at_s'])} s, and started "
           f"again, empty, at {num(store['start_at_s'])} s. What each workflow's attempts got, by when they were sent:", ""]
    rows = []
    for r in store["stopped"]:
        for name, phase in r["phases"].items():
            w2, w3 = phase[W2], phase[W3]
            rows.append([r["name"], name, counts(w2["statuses"]), counts(w2["refused_by"]), phase["w2_burst_tokens_served"],
                         f"{w3['incidents_served']} of {w3['incidents']}, {w3['incidents_first_attempt']}",
                         counts(w3["statuses"]),
                         f"{num(w2['attempt_s']['median'])} / {num(w2['attempt_s']['max'])}"])
    out += table(["Limiter", "Sent", "W2's answers", "What refused W2", "W2's burst tokens served",
                  "W3's incidents served, and on the first attempt", "W3's answers", "W2's attempt, median / longest (s)"],
                 rows)
    out += ["", "What the gateway did about it, in seconds from the stop and from the start:", ""]
    out += table(["Limiter", "First 503 after the stop", "503 answers", "Last 503 after the start", "First failed ping",
                  "Unreachable alert received", "First good ping after the start", "Answering-again alert received",
                  "Forwarded to"],
                 [[r["name"], r["first_503_after_the_stop_s"], r["answers_503"],
                   round(r["last_503_s"] - r["started_at_s"], 3) if r["last_503_s"] is not None else None,
                   r["first_failed_ping_after_the_stop_s"],
                   next((num(round(a["received_s"] - r["stopped_at_s"], 3)) for a in r["alerts"]
                         if a["event"] == "limiter_store_unreachable"), "none"),
                   r["first_good_ping_after_the_start_s"],
                   next((num(round(a["received_s"] - r["started_at_s"], 3)) for a in r["alerts"]
                         if a["event"] == "limiter_store_reachable"), "none"),
                   ", ".join(sorted({to for a in r["alerts"] for to in a["forwarded_to"]}))] for r in store["stopped"]])
    out += ["", "The proxy's log over the round, and its in-memory cache while the store was down:", ""]
    labels = list(store["stopped"][0]["log"])
    out += table(["Limiter", "Log lines", *[label[0].upper() + label[1:] for label in labels],
                  "Memory readings while down", "Most entries in memory", "Readings that held W2's window"],
                 [[r["name"], r["log_lines"], *[r["log"][label] for label in labels], r["memory_readings_while_down"],
                   r["memory_largest_while_down"], r["w2_window_in_memory_while_down"]] for r in store["stopped"]])
    words = Counter()
    for r in store["stopped"]:
        words.update(r["words_503"])
    if words:
        out += ["", "What the 503s said: " + "; ".join(f"\"{w}\" ({n})" for w, n in words.most_common(3)) + "."]
    unanswered = [f"{r['name']}, at {num(t)} s: {why}" for r in store["stopped"] for t, why in r["unanswered"]]
    if unanswered:
        out += ["", "Attempts that got no answer at all: " + "; ".join(unanswered) + "."]
    return out


def outage(o: dict[str, Any]) -> list[str]:
    out = ["", "## The outage drill again", "",
           "Step 5's three failure modes on two configs: step 5's own, with W3's model client of step 5b, and "
           "`litellm.outage-canada.yaml`, which gives W3 the self-hosted alias as its fallback. Times in seconds from "
           "the moment the primary began to fail.", ""]
    for cfg in o["configs"]:
        rows = cfg["modes"]
        out += [f"### {cfg['name']} (`{cfg['config']}`)", ""]
        out += table(["Mode", "W2's calls", "W2's answers", "Served by", "W3's calls", "W3's answers", "Served by",
                      "W3's refusals"],
                     [[r["mode"], r["w2"]["calls"], counts(r["w2"]["statuses"]), counts(r["w2"]["served_by"]),
                       r["w3"]["calls"], counts(r["w3"]["statuses"]), counts(r["w3"]["served_by"]),
                       counts(r["w3"]["kinds"])] for r in rows])
        out += [""]
        out += table(["Mode", "W2's calls by Region", "W3's calls by Region", "W3's calls by deployment",
                      "W3's requests the primary saw", "W3's requests us-east-2 saw", "W3's requests the self-hosted saw",
                      "W2's requests the self-hosted saw"],
                     [[r["mode"], counts(r["w2_regions"]), counts(r["w3_regions"]), counts(r["w3_calls_by_deployment"]),
                       r["w3_requests_seen_by"]["primary, ca-central-1"], r["w3_requests_seen_by"]["fallback, us-east-2"],
                       r["w3_requests_seen_by"]["self-hosted, ca-central-1"],
                       r["w2_requests_seen_by"]["self-hosted, ca-central-1"]] for r in rows])
        out += [""]

        def w3_run(run: dict[str, Any]) -> str:
            if run.get("raised"):
                return f"raised {run['raised']} after {run['model_calls']} model calls"
            waits = run.get("waits") or []
            waited = (f", having waited {' and '.join(num(w['waited_s']) for w in waits)} s for "
                      f"{', '.join(str(w['status']) for w in waits)}") if waits else ""
            why = f": {run['unavailable']}" if run.get("unavailable") else ""
            return (f"{run['outcome']} after {run['model_calls']} model calls and {num(run['seconds'])} s"
                    f"{waited}{why}")

        out += table(["Mode", "W2's run", "W3's run in flight", "W3's run started 20 s in"],
                     [[r["mode"], "answered" if r["runs"]["w2_in_flight"]["answered"] else "no answer",
                       w3_run(r["runs"]["w3_in_flight"]), w3_run(r["runs"]["w3_during_cooldown"])] for r in rows])
        out += [""]
    return out[:-1]


def fallback_load(calc: dict[str, Any]) -> list[str]:
    """W3's busy hour of Confidential calls on the self-hosted path, had an outage lasted the hour, at chapter 9's
    measured single-stream speeds, beside the Restricted calls step 5's calculator already put there."""
    profile = calc["profiles"]["w3"]
    restricted = next(s for s in calc["self_hosted"] if s["workflow"] == W3)
    speeds = restricted["measured"]
    seconds = (profile["busy_input_tpm"] * 60 / speeds["prompt_tokens_per_second"]
               + profile["busy_output_tpm"] * 60 / speeds["output_tokens_per_second"])
    both = seconds + restricted["replica_seconds"]
    return ["", "## W3's fallback on the self-hosted path", "",
            f"Had a provider outage lasted W3's whole busy hour ({num(profile['busy_hour_runs'])} incidents), its "
            f"Confidential calls, {num(profile['busy_input_tpm'] * 60)} input and {num(profile['busy_output_tpm'] * 60)} "
            f"output tokens, would take {num(seconds)} replica-seconds at chapter 9's single-stream speeds, and with the "
            f"Restricted calls' {num(restricted['replica_seconds'])} that is {num(both)} seconds, "
            f"{num(both / 36)}% of one replica's hour."]


def continuity(rows: list[dict[str, Any]]) -> list[str]:
    """The continuity table's rows as step 5b found them (`after_step5b`); step 5's summary keeps step 5's."""
    if not rows:
        return []
    out = ["", "## Continuity after step 5b", "",
           "The rows of step 5's continuity table that step 5b's drills change (`capacity/continuity.yaml`, "
           "`after_step5b`); step 5's summary keeps them as step 5 found them.", ""]
    out += table(["Component", "Failure mode", "Recovery objective", "Evidence", "Gap"],
                 [[r["component"], r["failure_mode"], r["recovery_objective"], r["evidence"], r.get("gap") or ""]
                  for r in rows])
    return out


def render(p: dict[str, Any], store: dict[str, Any], requests: list[dict[str, Any]], o: dict[str, Any],
           step5: dict[str, Any], step5_requests: list[dict[str, Any]], step5_cache: dict[str, Any],
           calc: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    out = [f"# Step 5b: the limiter on a shared store, and the outage drill again, {store['date']}", ""]
    out += probe(p) + contention(store, requests, step5, step5_requests) + cache(store, step5_cache)
    out += latency(store, step5) + stopped(store) + outage(o) + fallback_load(calc) + continuity(rows)
    v = store["versions"]
    out += ["", f"LiteLLM {v['litellm']}, redis-py {v['redis']}, Garnet {v['garnet']}, Python {v['python']}, prisma "
                f"{v['prisma']}.", ""]
    return "\n".join(out)


def load(folder: Path) -> tuple:
    return (json.loads((folder / "store-probe.json").read_text(encoding="utf-8")),
            json.loads((folder / "store.json").read_text(encoding="utf-8")),
            jsonl(folder / "store-contention-requests.jsonl"),
            json.loads((folder / "outage.json").read_text(encoding="utf-8")),
            json.loads((STEP5 / "drills.json").read_text(encoding="utf-8")),
            jsonl(STEP5 / "contention-requests.jsonl"),
            json.loads((STEP5 / "limiter-cache.json").read_text(encoding="utf-8")),
            json.loads((STEP5 / "calculator.json").read_text(encoding="utf-8")),
            load_continuity())


def load_continuity(path: Path = HERE / "continuity.yaml") -> list[dict[str, Any]]:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")).get("after_step5b") or []


def write(folder: Path) -> Path:
    path = folder / "summary-5b.md"
    path.write_text(render(*load(folder)), encoding="utf-8", newline="\n")
    return path
