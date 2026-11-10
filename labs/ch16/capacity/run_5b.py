"""Step 5b's drills: the limiter on a shared store, the store stopped mid-burst, and the outage drill again.

Chapter 16, step 5b (companion #14), from step 5's findings. Everything runs on 127.0.0.1 with no model and no cloud,
on step 5's fakes, quota, loads and rounds, and step 5's code where it fits (`run_drills.py`, unchanged):

- **the store's probe**: LiteLLM 1.106.6's rate-limiter scripts, each run once against Garnet with known inputs and
  set against what Redis answers, and 1,000 check-and-increments at once over 100 connections against a limit of
  250, three times with Garnet's Lua transaction mode and three times without;
- **contention**: step 5's four limits, three rounds each, interleaved, on step 4's gateway with its limiter on the
  store (`litellm.store.yaml`, `litellm.store-deployment.yaml`), the store emptied before every round;
- **the limiter's cache**: each per-key limit once more with the census, which now reads the store as well as the
  proxy's memory, with and without step 4's budget alerts (`litellm.store-census*.yaml`);
- **latency**: step 5's single-call setup with a tpm_limit, on the store;
- **the store stopped**: one round of the exact division with the store stopped thirty seconds into W2's burst and
  started again, empty, a minute later, once as LiteLLM leaves its limiter by default and once failing closed, with
  `store_hooks.py`'s alert arriving at step 4's receiver;
- **the outage**: step 5's three failure modes twice, on step 5's config with W3's model client of step 5b, and on
  `litellm.outage-canada.yaml`, which gives W3 the self-hosted alias as its fallback.

Run, in step 4's environment (chapter 5's requirements plus Prisma, `prisma generate` done), from labs/ch16, after
`python budget/postgres.py` and `python capacity/garnet.py`:
    python capacity/run_5b.py --out results/<date>/capacity                # about 65 minutes
    python capacity/run_5b.py --only stopped --out results/<date>/capacity   # one part, repeatable: probe,
                                                                             # contention, cache, latency, stopped, outage
    python capacity/run_5b.py --summarize results/<date>/capacity          # the summary again from the files
Raw records stay in `capacity/_lab/step5b-<stamp>/`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (HERE, LAB / "budget"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import garnet  # noqa: E402
import load  # noqa: E402
import run_drills as step5  # noqa: E402
import stack  # noqa: E402

W2, W3 = step5.W2, step5.W3
URLS = {"BUDGET_PRIMARY_URL": "primary", "BUDGET_SELF_HOSTED_URL": "self-hosted",
        "CAPACITY_PRIMARY_URL": "primary", "CAPACITY_SELF_HOSTED_URL": "self-hosted"}
STORE_CONTENTION = [(spec, "litellm.store-deployment.yaml" if spec["config"] == "deployment" else "litellm.store.yaml")
                    for spec in step5.CONTENTION]
STORE_CENSUS = [
    {"gateway": "step 4's with the store", "config": "litellm.store-census.yaml", "limit": "tokens per minute per key"},
    {"gateway": "step 4's with the store", "config": "litellm.store-census.yaml",
     "limit": "tokens per minute per key, with headroom"},
    {"gateway": "step 4's with the store, without alerts", "config": "litellm.store-census-no-alerts.yaml",
     "limit": "tokens per minute per key"},
    {"gateway": "step 4's with the store, without alerts", "config": "litellm.store-census-no-alerts.yaml",
     "limit": "tokens per minute per key, with headroom"},
]
STOPPED = [{"name": "LiteLLM's default", "config": "litellm.store-census.yaml"},
           {"name": "failing closed", "config": "litellm.store-census-fail-closed.yaml"}]
STOP_AT, START_AT = 45.0, 105.0  # thirty seconds into W2's burst (15 to 75 s), and a minute later
OUTAGES = [{"name": "step 5's config", "config": "litellm.outage.yaml"},
           {"name": "W3's fallback in Canada", "config": "litellm.outage-canada.yaml"}]
RACE = {"calls": 1000, "connections": 100, "limit": 250, "trials": 3}
# What LiteLLM 1.106.6 writes to the proxy's log when its store goes away, as the trial runs found it: warnings for
# the first failed batches, one for the circuit breaker, and then, while the breaker is open, a traceback ending in
# RedisCircuitBreakerOpenError for every skipped write of the spend counters.
LOG_SIGNS = {"a batch of store operations failed": "ops failed: ",
             "the circuit breaker opened": "Redis circuit breaker OPENED",
             "a store call skipped while the breaker was open, with its traceback":
                 "RedisCircuitBreakerOpenError: Redis circuit breaker is open",
             "the key cache's subscriber lost the store": "auth cache invalidation subscriber redis error",
             "a Lua script failed, the local mirror used": "Redis Lua script failed",
             "a call refused, failing closed": "fail_closed_rate_limit_enforcement: rejecting request"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def versions() -> dict[str, Any]:
    found = step5.versions()
    from importlib import metadata

    try:
        found["redis"] = metadata.version("redis")
    except metadata.PackageNotFoundError:
        found["redis"] = None
    found["garnet"] = garnet.VERSION
    return found


# --- the store's probe ------------------------------------------------------------------------------------------

def redis_answers() -> dict[str, list]:
    """What Redis answers each step of the probe, read from the scripts themselves; "now" is the window's start."""
    return {"batch_1st": ["now", 1], "batch_2nd": ["now", 2], "read": ["now", "2", None],
            "check_1st": [0, 60, "now"], "check_2nd": [0, 90, "now"], "check_over": [1, 1, 90, 100],
            "guarded_match": [1, 70], "guarded_stale": [0, 70],
            "acquire_1": [0, 1], "acquire_2": [0, 2], "acquire_3_over": [1, 1, 2, 2], "release_a": [1], "count": [1],
            "float_1": ["0.25"], "float_2": ["0.75"], "ttl_window": 60, "ttl_tokens": 60, "ttl_spend": 60}


async def probe_scripts(port: int, password: str) -> dict[str, Any]:
    """Each of the limiter's scripts once, with known inputs, as LiteLLM registers them."""
    import redis.asyncio as aioredis
    from litellm.proxy.hooks import parallel_request_limiter_v3 as v3

    r = aioredis.Redis(host="127.0.0.1", port=port, password=password, decode_responses=True)
    info = await r.info("server")
    names = ("BATCH_RATE_LIMITER_SCRIPT", "BATCH_COUNTER_READ_SCRIPT", "CHECK_AND_INCREMENT_BY_N_SCRIPT",
             "WINDOW_GUARDED_TOKEN_INCREMENT_SCRIPT", "PARALLEL_ACQUIRE_SCRIPT", "PARALLEL_RELEASE_SCRIPT",
             "PARALLEL_COUNT_SCRIPT", "TOKEN_INCREMENT_SCRIPT")
    scripts = {n: r.register_script(getattr(v3, n)) for n in names}
    w, c, t = "{api_key:probe}:window", "{api_key:probe}:requests", "{api_key:probe}:tokens"
    started = int(time.time())
    got: dict[str, Any] = {}

    async def run(label: str, name: str, keys: list[str], args: list[Any]) -> None:
        try:
            got[label] = await scripts[name](keys=keys, args=args)
        except Exception as exc:  # noqa: BLE001 - a script the store can't run is the finding
            got[label] = f"error {type(exc).__name__}: {exc}"

    await run("batch_1st", "BATCH_RATE_LIMITER_SCRIPT", [w, c], [started, 60])
    await run("batch_2nd", "BATCH_RATE_LIMITER_SCRIPT", [w, c], [started, 60])
    await run("read", "BATCH_COUNTER_READ_SCRIPT", [w, c, t], [])
    await r.delete(w, c, t)
    await run("check_1st", "CHECK_AND_INCREMENT_BY_N_SCRIPT", [w, t], [100, 60, 60, 60])
    await run("check_2nd", "CHECK_AND_INCREMENT_BY_N_SCRIPT", [w, t], [100, 30, 60, 60])
    await run("check_over", "CHECK_AND_INCREMENT_BY_N_SCRIPT", [w, t], [100, 30, 60, 60])
    await run("guarded_match", "WINDOW_GUARDED_TOKEN_INCREMENT_SCRIPT", [w, t], [await r.get(w) or "", -20, 60])
    await run("guarded_stale", "WINDOW_GUARDED_TOKEN_INCREMENT_SCRIPT", [w, t], ["1", 5, 60])
    g = "{api_key:probe}:parallel"
    await run("acquire_1", "PARALLEL_ACQUIRE_SCRIPT", [g], [2, 60, "slot-a"])
    await run("acquire_2", "PARALLEL_ACQUIRE_SCRIPT", [g], [2, 60, "slot-b"])
    await run("acquire_3_over", "PARALLEL_ACQUIRE_SCRIPT", [g], [2, 60, "slot-c"])
    await run("release_a", "PARALLEL_RELEASE_SCRIPT", [g], ["slot-a"])
    await run("count", "PARALLEL_COUNT_SCRIPT", [g], [60])
    f = "{api_key:probe}:spend"
    await run("float_1", "TOKEN_INCREMENT_SCRIPT", [f], [0.25, 60])
    await run("float_2", "TOKEN_INCREMENT_SCRIPT", [f], [0.5, 60])
    got["ttl_window"], got["ttl_tokens"], got["ttl_spend"] = await r.ttl(w), await r.ttl(t), await r.ttl(f)
    await r.aclose()

    def shown(value: Any) -> Any:
        """A window start, the server's clock in seconds, as "now"; numbers as Redis returns them."""
        if isinstance(value, list):
            return [shown(v) for v in value]
        if isinstance(value, (int, str)) and str(value).isdigit() and abs(int(value) - started) <= 5:
            return "now"
        return value

    answers = {label: shown(value) for label, value in got.items()}
    expected = redis_answers()
    return {"server": {k: info.get(k) for k in ("redis_version", "garnet_version")},
            "answers": answers, "as_redis_answers": {label: answers.get(label) == want for label, want in expected.items()}}


async def race(port: int, password: str, calls: int, connections: int, limit: int) -> dict[str, Any]:
    """`calls` check-and-increments by one at once, spread over `connections`, against `limit` on one key pair."""
    import redis.asyncio as aioredis
    from litellm.proxy.hooks import parallel_request_limiter_v3 as v3

    keys = ["{api_key:race}:window", "{api_key:race}:tokens"]
    admin = aioredis.Redis(host="127.0.0.1", port=port, password=password, socket_timeout=10)
    await admin.delete(*keys, "{api_key:race}:requests")
    clients = [aioredis.Redis(host="127.0.0.1", port=port, password=password, socket_timeout=10)
               for _ in range(connections)]
    scripts = [client.register_script(v3.CHECK_AND_INCREMENT_BY_N_SCRIPT) for client in clients]

    async def one(i: int) -> int:
        return int((await scripts[i % connections](keys=keys, args=[limit, 1, 60, 60]))[0])

    answers = await asyncio.wait_for(asyncio.gather(*(one(i) for i in range(calls)), return_exceptions=True), 120)
    counter = await admin.get(keys[1])
    for client in clients:
        await client.aclose()
    await admin.aclose()
    return {"admitted": sum(1 for a in answers if a == 0), "refused": sum(1 for a in answers if a == 1),
            "errors": sum(1 for a in answers if isinstance(a, BaseException)),
            "counter_after": int(counter) if counter is not None else None}


def run_probe(work: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"race": dict(RACE), "modes": [], "stopped_pids": []}
    for transaction_mode in (True, False):
        server = garnet.Server(work / f"probe-{'transaction' if transaction_mode else 'plain'}",
                               transaction_mode=transaction_mode)
        try:
            server.start()
            found = asyncio.run(probe_scripts(server.port, server.password))
            trials = [asyncio.run(race(server.port, server.password, RACE["calls"], RACE["connections"], RACE["limit"]))
                      for _ in range(RACE["trials"])]
        finally:
            out["stopped_pids"].append(server.pid)
            server.stop()
        out["modes"].append({"transaction_mode": transaction_mode, **found, "trials": trials})
        print("probe", transaction_mode, json.dumps(trials), flush=True)
    return out


# --- contention and the limiter's cache on the store ---------------------------------------------------------

def store_stack(folder: Path) -> stack.Stack:
    """Step 4's PostgreSQL and database-backed gateway, the receiver, the fake provider, and the store."""
    return stack.Stack(folder, HERE / "litellm.store.yaml", {"primary": step5.PROVIDER_ARGS, "self-hosted": []},
                       dict(URLS), database=True, receiver=True, store=True)


def fresh(s: stack.Stack) -> None:
    """No proxy, and an empty store: a round starts with no window, counter or cooldown from the round before."""
    s.stop_proxy()
    if not garnet.flushall(s.store.port, s.store.password):
        raise RuntimeError("the store didn't empty")


def watch_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if path.exists() else []


def store_metrics(lines: list[dict[str, Any]], tokens: dict[str, str], wall0: float) -> dict[str, Any]:
    """The store's side of the census: its size, its errors, and whether each key's window lived out its minute.

    As for the in-memory cache, a window is evicted when a reading finds it gone while the last reading that held it
    gave it more than a second still to live; a window that runs out its sixty seconds isn't counted."""
    snaps = sorted((line for line in lines if line.get("event") == "store"), key=lambda line: line["t"])
    ok = [line for line in snaps if "store_error" not in line]
    keys: dict[str, Any] = {}
    for workflow, token in tokens.items():
        window = f"{{api_key:{token}}}:window"
        evicted, last, windows = [], None, set()
        for line in ok:
            held = line["store_limiter"].get(window)
            if held is not None:
                windows.add(held[0])
                last = (line["t"], held[1])
            elif last is not None and last[1] is not None and line["t"] < last[0] + last[1] - 1.0:
                evicted.append(round(line["t"] - wall0, 3))
                last = None
            else:
                last = None
        keys[workflow] = {"store_window_evicted_s": evicted[0] if evicted else None, "store_evictions": len(evicted),
                          "store_windows_seen": len(windows)}
    errors = [line for line in snaps if "store_error" in line]
    return {"store_readings": len(snaps), "store_errors": len(errors),
            "store_error_kinds": dict(Counter(line["store_error"].split(":")[0] for line in errors).most_common(3)),
            "store_largest": max((line["store_size"] for line in ok), default=None), "keys": keys}


def drill_contention(s: stack.Stack, admin: Any, made: dict, work: Path, rounds: int = step5.ROUNDS
                     ) -> tuple[list[dict], list[dict]]:
    sizes = step5.shapes()
    rows: list[dict] = []
    lines: list[dict] = []
    for round_ in range(1, rounds + 1):
        for spec, config in STORE_CONTENTION:
            index = len(rows) + 1
            fresh(s)
            s.extra_env["CAPACITY_STORE_WATCH_FILE"] = str(work / f"contention-{index}-watch.jsonl")
            row, requests, _ = step5.contention_round(s, admin, made, spec, round_, HERE / config, sizes,
                                                      work / f"contention-{index}-provider.json")
            row["config"] = config
            row["store_alerts"] = [w["alert"] for w in watch_lines(work / f"contention-{index}-watch.jsonl") if w["alert"]]
            rows.append(row)
            lines += [{"limit": spec["name"], "round": round_, **r} for r in requests]
            print("store contention", spec["name"], round_, json.dumps(row["w3_in_the_burst"]), flush=True)
    s.extra_env.pop("CAPACITY_STORE_WATCH_FILE", None)
    return rows, lines


def drill_limiter_cache(s: stack.Stack, admin: Any, made: dict, work: Path) -> tuple[list[dict], list[dict]]:
    sizes = step5.shapes()
    rows: list[dict] = []
    lines: list[dict] = []
    tokens = {w: made[w]["token"] for w in (W2, W3)}
    for i, setup in enumerate(STORE_CENSUS, 1):
        census = work / f"census-{i}.jsonl"
        fresh(s)
        s.extra_env.update(CAPACITY_CENSUS_FILE=str(census), CAPACITY_STORE_WATCH_FILE=str(work / f"census-{i}-watch.jsonl"))
        spec = next(c for c in step5.CONTENTION if c["name"] == setup["limit"])
        row, requests, clock = step5.contention_round(s, admin, made, spec, 1, HERE / setup["config"], sizes,
                                                      work / f"census-{i}-provider.json")
        found = [json.loads(line) for line in census.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows.append({"gateway": setup["gateway"], **row, "config": setup["config"],
                     "cache": step5.census_metrics(found, tokens, clock.wall0, requests),
                     "store": store_metrics(found, tokens, clock.wall0),
                     "store_alerts": [w["alert"] for w in watch_lines(work / f"census-{i}-watch.jsonl") if w["alert"]]})
        lines += [{"gateway": setup["gateway"], "limit": spec["name"], **r} for r in requests]
        print("store census", setup["gateway"], spec["name"], json.dumps(rows[-1]["store"]), flush=True)
    for name in ("CAPACITY_CENSUS_FILE", "CAPACITY_STORE_WATCH_FILE"):
        s.extra_env.pop(name, None)
    return rows, lines


# --- the store stopped mid-burst -----------------------------------------------------------------------------

def compact_timed(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """step 5's compact lines, with each attempt's end and a refusal's words as well:
    [t, t_end, status, limit, retry_after, message]."""
    return [{"stream": r["stream"], "workflow": r["workflow"], "t": r["t"], "served": r["served"], "wait_s": r["wait_s"],
             "served_at": r["served_at"],
             "attempts": [[a["t"], a["t_end"], a["status"], a["limit"], a["retry_after"], (a.get("message") or "")[:160]]
                          for a in r["attempts"]],
             "estimate": r["input_tokens"] + (r["max_tokens"] or 0), "charge": r["input_tokens"] + r["output_tokens"]}
            for r in requests]


def phase(t: float, stopped: float, started: float) -> str:
    return "before" if t < stopped else ("while down" if t < started else "after")


def stopped_metrics(requests: list[dict[str, Any]], stopped: float, started: float, census: list[dict[str, Any]],
                    watch: list[dict[str, Any]], alerts: list[dict[str, Any]], log: str, tokens: dict[str, str],
                    wall0: float) -> dict[str, Any]:
    """What the gateway did before, while and after the store was down; times in seconds on the round's clock."""
    phases: dict[str, Any] = {}
    for name in ("before", "while down", "after"):
        mine = {}
        for workflow in (W2, W3):
            attempts = [a for r in requests if r["workflow"] == workflow for a in r["attempts"]
                        if phase(a[0], stopped, started) == name]
            sent = [r for r in requests if r["workflow"] == workflow and phase(r["t"], stopped, started) == name]
            incidents = [r for r in sent if r["stream"] == "incident"]
            mine[workflow] = {
                "attempts": len(attempts),
                "statuses": dict(sorted(Counter(str(a[2]) for a in attempts).items())),
                "refused_by": dict(sorted(Counter(a[3] for a in attempts if a[2] != 200).items())),
                "attempt_s": {"median": median([a[1] - a[0] for a in attempts]),
                              "max": round(max((a[1] - a[0] for a in attempts), default=0.0), 3) or None},
                "incidents": len(incidents), "incidents_served": sum(1 for r in incidents if r["served"]),
                "incidents_first_attempt": sum(1 for r in incidents if r["attempts"][0][2] == 200)}
        mine["w2_burst_tokens_served"] = sum(r["charge"] for r in requests if r["stream"] == "burst" and r["served"]
                                             and phase(r["served_at"], stopped, started) == name)
        phases[name] = mine
    unavailable = sorted(a[0] for r in requests for a in r["attempts"] if a[2] == 503)
    words_503 = Counter(a[5][:120] for r in requests for a in r["attempts"] if a[2] == 503)
    unanswered = sorted([round(a[0], 3), a[5]] for r in requests for a in r["attempts"] if a[2] is None)
    failed_pings = [w["t"] - wall0 for w in watch if not w["ok"]]
    good_after = [w["t"] - wall0 for w in watch if w["ok"] and w["t"] - wall0 >= started]
    window = f"{{api_key:{tokens[W2]}}}:window"
    memory = [line for line in census if "size" in line and stopped <= line["t"] - wall0 < started]
    return {"stopped_at_s": round(stopped, 3), "started_at_s": round(started, 3), "phases": phases,
            "first_503_after_the_stop_s": round(unavailable[0] - stopped, 3) if unavailable else None,
            "last_503_s": round(unavailable[-1], 3) if unavailable else None, "answers_503": len(unavailable),
            "words_503": dict(words_503.most_common(3)), "unanswered": unanswered,
            "log_lines": log.count("\n"),
            "first_failed_ping_after_the_stop_s": round(min((t for t in failed_pings if t >= stopped), default=0)
                                                        - stopped, 3) if failed_pings else None,
            "first_good_ping_after_the_start_s": round(good_after[0] - started, 3) if good_after else None,
            "alerts": [{"event": a["event"], "kind": a["kind"], "forwarded_to": a["forwarded_to"],
                        "received_s": round(datetime.fromisoformat(a["received_at"]).timestamp() - wall0, 3),
                        "message": a["event_message"]} for a in alerts],
            "log": {label: log.count(sign) for label, sign in LOG_SIGNS.items()},
            "w2_window_in_memory_while_down": sum(1 for line in memory if window in line["limiter"]),
            "memory_readings_while_down": len(memory),
            "memory_largest_while_down": max((line["size"] for line in memory), default=None),
            "store": store_metrics(census, tokens, wall0)}


def stopped_round(s: stack.Stack, admin: Any, made: dict, setup: dict[str, Any], work: Path, index: int
                  ) -> tuple[dict, list[dict]]:
    spec = next(c for c in step5.CONTENTION if c["name"] == "tokens per minute per key")
    census, watch = work / f"stopped-{index}-census.jsonl", work / f"stopped-{index}-watch.jsonl"
    fresh(s)
    s.extra_env.update(CAPACITY_CENSUS_FILE=str(census), CAPACITY_STORE_WATCH_FILE=str(watch))
    log_path, outbox = s.work / "proxy.log", s.work / "alerts.jsonl"
    log_from = log_path.stat().st_size if log_path.exists() else 0
    alerts_from = len(outbox.read_text(encoding="utf-8").splitlines()) if outbox.exists() else 0
    back = s.restart_proxy(HERE / setup["config"])
    for workflow in (W2, W3):
        admin.update(made[workflow]["token"], tpm_limit=spec["tpm_limit"][workflow])
    time.sleep(3)
    s.control("primary", reset_quota=True, clear_log=True)
    clock = load.Clock()
    switched: dict[str, Any] = {}

    def switch() -> None:
        time.sleep(max(0.0, STOP_AT - clock.now()))
        s.stop_store()
        switched["stopped"] = clock.now()
        time.sleep(max(0.0, START_AT - clock.now()))
        switched["start_took_s"] = s.start_store()
        switched["started"] = clock.now()

    thread = threading.Thread(target=switch, daemon=True)
    thread.start()
    results = asyncio.run(load.run(s.url, {w: made[w]["key"] for w in (W2, W3)}, step5.workloads(step5.shapes()),
                                   clock=clock, seed=17))
    thread.join(timeout=120)
    time.sleep(5)  # the watch's next ping and the alert after it
    requests = compact_timed(results)
    found = [json.loads(line) for line in census.read_text(encoding="utf-8").splitlines() if line.strip()]
    with log_path.open("rb") as stream:
        stream.seek(log_from)
        log = stream.read().decode("utf-8", errors="replace")
    alerts = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()[alerts_from:] if line.strip()] \
        if outbox.exists() else []
    alerts = [a for a in alerts if a.get("event") in ("limiter_store_unreachable", "limiter_store_reachable")]
    row = {"name": setup["name"], "config": setup["config"], "limit": spec["name"], "tpm_limit": spec["tpm_limit"],
           "proxy_back_in_s": back, "store_start_took_s": switched.get("start_took_s"),
           **stopped_metrics(requests, switched["stopped"], switched["started"], found, watch_lines(watch), alerts, log,
                             {w: made[w]["token"] for w in (W2, W3)}, clock.wall0)}
    for name in ("CAPACITY_CENSUS_FILE", "CAPACITY_STORE_WATCH_FILE"):
        s.extra_env.pop(name, None)
    return row, [{"name": setup["name"], **r} for r in requests]


STORE_PARTS = ("contention", "cache", "latency", "stopped")


def write_lines(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")


def run_store(out: Path, work: Path, parts: tuple[str, ...] = STORE_PARTS) -> None:
    """The store's drills on one database stack: contention, the limiter's cache, latency, the store stopped.
    A part run alone replaces its own entries in `store.json` and leaves the others as they were."""
    import keys
    import record

    s = store_stack(work / "db")
    existing = out / "store.json"
    result: dict[str, Any] = json.loads(existing.read_text(encoding="utf-8")) if existing.exists() else {}
    result.update({"date": now_utc().date().isoformat(), "versions": versions(), "quota_tpm": step5.QUOTA,
                   "burst": list(step5.BURST), "duration_s": step5.DURATION_S, "stop_at_s": STOP_AT,
                   "start_at_s": START_AT})
    lines: dict[str, list[dict]] = {}
    pids: dict[str, Any] = {}
    try:
        s.start()
        result["store_start_s"] = s.store.starts[0]
        admin = keys.Admin(s.url, s.master_key)
        made = keys.provision(admin, step5.manifests())
        s.control("primary", tpm=step5.QUOTA)
        if "contention" in parts:
            result["contention"], lines["store-contention-requests.jsonl"] = drill_contention(s, admin, made, work)
        if "cache" in parts:
            result["cache"], lines["store-cache-requests.jsonl"] = drill_limiter_cache(s, admin, made, work)
        if "latency" in parts:
            fresh(s)
            s.restart_proxy(HERE / "litellm.store.yaml")
            admin.update(made[W2]["token"], tpm_limit=step5.LATENCY_TPM_LIMIT)
            s.control("primary", tpm=None)
            result["latency"] = step5.drill_latency(
                s.url, made[W2]["key"], W2, "internal", lambda: s.provider_log("primary"),
                lambda **b: s.control("primary", **b), label="step 4's gateway with the store, W2's key with a tpm_limit")
            admin.update(made[W2]["token"], tpm_limit=None)
            s.control("primary", tpm=step5.QUOTA)
        if "stopped" in parts:
            result["stopped"], stopped_lines = [], []
            for i, setup in enumerate(STOPPED, 1):
                row, found = stopped_round(s, admin, made, setup, work, i)
                result["stopped"].append(row)
                stopped_lines += found
                print("stopped", setup["name"], json.dumps({k: row[k] for k in ("first_503_after_the_stop_s", "alerts",
                                                                                 "log")}), flush=True)
            lines["store-stopped-requests.jsonl"] = stopped_lines
    finally:
        pids["stopped"] = s.pids()
        s.stop()
        pids["left_running"] = s.pids()
    result.setdefault("processes", {})["+".join(parts)] = pids
    record.write_json(existing, result, secrets=(s.master_key, s.store.password))
    for name, rows in lines.items():
        write_lines(out / name, rows)


# --- the outage drill again ----------------------------------------------------------------------------------

def w3_triage(s: stack.Stack, key: str, on_second_call: Any | None) -> dict[str, Any]:
    """step 5's W3 triage, W3's run_steps and W3GatewayModel, with what step 5b's model client keeps: its waits, why
    it gave up, and how long the triage took."""
    import loop as w3loop
    from fake_platform import pod_status
    from gateway_model import pinned_tool_specs

    specs = pinned_tool_specs(step5.CH05 / "mcp-server" / "tools.lock.json", {"get_pod_status"})
    model = w3loop.W3GatewayModel(gateway_url=s.url, alias="larkspur-chat", tools=specs, trace_id=uuid.uuid4().hex,
                                  workflow=W3, data_class="confidential", api_key=key, timeout_s=30)
    count = {"n": 0}

    def flipping(messages: list[dict]) -> dict:
        count["n"] += 1
        if count["n"] == 2 and on_second_call is not None:
            on_second_call()
        return model(messages)

    started = time.time()
    try:
        out = w3loop.run_steps("Is claims-api healthy?", flipping, {"get_pod_status": pod_status},
                               {"get_pod_status": {"service"}}, {"restart_deployment"})
        found = {"outcome": out.kind, "reason": out.reason, "text": out.text[:90], "raised": None}
    except Exception as exc:  # noqa: BLE001 - step 5 found W3 raising here; anything raised is the finding
        status = getattr(getattr(exc, "response", None), "status_code", "")
        found = {"outcome": None, "reason": None, "text": None, "raised": f"{type(exc).__name__} {status}".strip()}
    return {"trace_id": model.trace_id, **found, "model_calls": count["n"], "started": started,
            "seconds": round(time.time() - started, 3), "waits": model.waits, "unavailable": model.unavailable,
            "time_budget_s": model.time_budget_s}


def outage_mode(s: stack.Stack, mode: str) -> dict[str, Any]:
    """step 5's outage_mode, with W3's run during the cooldown in a thread of its own, so that a run that waits
    can't hold the heal back, and the self-hosted fake's log kept as well."""
    s.restart_proxy()
    for name in ("primary", "fallback", "self-hosted"):
        if s.fakes[name].process is None:
            s.start_fake(name)
        s.control(name, mode="ok", clear_log=True)
    events: list[dict[str, Any]] = []
    stop = threading.Event()

    def loop_calls(workflow: str, data_class: str, every_s: float) -> None:
        import httpx

        client = httpx.Client(timeout=30)
        while not stop.is_set():
            started = time.time()
            request_id = uuid.uuid4().hex[:12]
            try:
                r = client.post(f"{s.url}/chat/completions", headers={"Authorization": f"Bearer {s.master_key}"},
                                json=load.body(workflow, data_class, request_id, load.Shape(200, 64, 20)))
                status, model_id = r.status_code, r.headers.get("x-litellm-model-id")
                retry_after, message = r.headers.get("retry-after"), ("" if status == 200 else load.message_of(r))
            except Exception as exc:  # noqa: BLE001
                status, model_id, retry_after, message = None, None, None, type(exc).__name__
            events.append({"workflow": workflow, "t": started, "t_end": time.time(), "status": status,
                           "served_by": model_id, "retry_after": retry_after, "limit": load.limiter(status, message),
                           "message": message[:160]})
            stop.wait(max(0.0, every_s - (time.time() - started)))

    def fail() -> None:
        if mode == "connection":
            s.stop_fake("primary")
        else:
            s.control("primary", mode=mode)

    workers = [threading.Thread(target=loop_calls, args=(W2, "internal", 1.0), daemon=True),
               threading.Thread(target=loop_calls, args=(W3, "confidential", 2.0), daemon=True)]
    for w in workers:
        w.start()
    time.sleep(step5.OUTAGE_PHASES["healthy_s"])
    flipped: dict[str, float] = {}
    lock = threading.Lock()
    both = threading.Barrier(2, timeout=60)

    def flip_once() -> None:
        both.wait()
        with lock:
            if "t" not in flipped:
                fail()
                flipped["t"] = time.time()

    runs: dict[str, Any] = {}
    in_flight = [threading.Thread(target=lambda: runs.__setitem__("w2_in_flight", step5._w2_run(s, s.master_key, flip_once))),
                 threading.Thread(target=lambda: runs.__setitem__("w3_in_flight", w3_triage(s, s.master_key, flip_once)))]
    for t in in_flight:
        t.start()
    for t in in_flight[:1]:
        t.join(timeout=90)
    deadline = time.time() + 90
    while "t" not in flipped and time.time() < deadline:
        time.sleep(0.05)
    t_fail = flipped.get("t") or time.time()
    time.sleep(max(0.0, t_fail + 20.0 - time.time()))
    cooldown_run = threading.Thread(target=lambda: runs.__setitem__("w3_during_cooldown", w3_triage(s, s.master_key, None)))
    cooldown_run.start()
    time.sleep(max(0.0, t_fail + step5.OUTAGE_PHASES["failing_s"] - time.time()))
    t_heal = time.time()
    if mode == "connection":
        s.start_fake("primary")
    else:
        s.control("primary", mode="ok")
    time.sleep(step5.OUTAGE_PHASES["healed_s"])
    for t in in_flight[1:] + [cooldown_run]:
        t.join(timeout=180)
    stop.set()
    for w in workers:
        w.join(timeout=60)
    logs = {name: s.provider_log(name) for name in ("primary", "fallback", "self-hosted")}
    for run in runs.values():
        if "started" in run:
            run["started_s"] = round(run.pop("started") - t_fail, 3)
    return {"mode": mode, "t_fail": t_fail, "t_heal": t_heal, "events": events, "runs": runs,
            **{name.replace("-", "_"): [{k: r.get(k) for k in ("t", "t_end", "workflow", "status")} for r in log]
               for name, log in logs.items()}}


def outage_extras(raw: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Where W3's calls went: by deployment from the gateway's lines, and as each fake provider saw them."""
    t_fail, t_heal = raw["t_fail"], raw["t_heal"]
    window = [line for line in lines if t_fail - 1 <= step5.epoch(line["ts"]) <= t_heal + 60]
    w3_calls = [line for line in window if line.get("event") == "call" and line.get("workflow") == W3]
    return {"w3_calls_by_deployment": dict(sorted(Counter(line.get("deployment") or "none" for line in w3_calls).items())),
            "w3_calls_as_fallback": sum(1 for line in w3_calls if line.get("fallback")),
            "w3_fallback_in_jurisdiction_lines": sum(1 for line in window if line.get("event") == "fallback_in_jurisdiction"
                                                     and (line.get("tags") or {}).get("workflow") == W3),
            "w3_requests_seen_by": {name: sum(1 for r in raw[key] if r["workflow"] == W3)
                                    for name, key in (("primary, ca-central-1", "primary"),
                                                      ("fallback, us-east-2", "fallback"),
                                                      ("self-hosted, ca-central-1", "self_hosted"))},
            "w2_requests_seen_by": {name: sum(1 for r in raw[key] if r["workflow"] == W2)
                                    for name, key in (("primary, ca-central-1", "primary"),
                                                      ("fallback, us-east-2", "fallback"),
                                                      ("self-hosted, ca-central-1", "self_hosted"))}}


def run_outage(out: Path, work: Path) -> None:
    import record
    import yaml

    speed = ["--base-ms", "50", "--per-output-token-ms", "1.0"]
    result: dict[str, Any] = {"date": now_utc().date().isoformat(), "versions": versions(), "configs": []}
    events: list[dict[str, Any]] = []
    secrets: list[str] = []
    for setup in OUTAGES:
        config = HERE / setup["config"]
        router = yaml.safe_load(config.read_text(encoding="utf-8"))["router_settings"]
        s = stack.Stack(work / f"outage-{setup['config'].removeprefix('litellm.').removesuffix('.yaml')}", config,
                        {"primary": speed, "fallback": speed, "self-hosted": speed},
                        {"CAPACITY_PRIMARY_URL": "primary", "CAPACITY_FALLBACK_URL": "fallback",
                         "CAPACITY_SELF_HOSTED_URL": "self-hosted"})
        secrets.append(s.master_key)
        rows = []
        try:
            s.start()
            for mode in step5.OUTAGE_MODES:
                raw = outage_mode(s, mode)
                lines = s.gateway_lines()
                rows.append({**step5.outage_metrics(raw, lines, router["allowed_fails"], router["cooldown_time"]),
                             **outage_extras(raw, lines)})
                events += [{"config": setup["config"], "mode": mode,
                            **{k: (round(v - raw["t_fail"], 3) if k in ("t", "t_end") else v) for k, v in e.items()}}
                           for e in raw["events"]]
                (s.work / f"outage-{mode}.json").write_text(json.dumps(raw), encoding="utf-8")
                print("outage", setup["name"], mode, json.dumps({k: rows[-1][k] for k in ("w3", "w3_requests_seen_by")}),
                      flush=True)
        finally:
            stopped = s.pids()
            s.stop()
        result["configs"].append({**setup, "modes": rows, "stopped_pids": stopped, "left_running": s.pids()})
    record.write_json(out / "outage.json", result, secrets=tuple(secrets))
    write_lines(out / "outage-events.jsonl", events)


# --- the whole run ------------------------------------------------------------------------------------------------

PARTS = ("probe", *STORE_PARTS, "outage")


def run(out: Path, parts: tuple[str, ...] = PARTS) -> None:
    import record

    garnet.verified()
    work = HERE / "_lab" / f"step5b-{now_utc().strftime('%Y%m%dT%H%M%SZ')}"
    work.mkdir(parents=True)
    out.mkdir(parents=True, exist_ok=True)
    if "probe" in parts:
        probe = run_probe(work)
        record.write_json(out / "store-probe.json", {"date": now_utc().date().isoformat(), "versions": versions(),
                                                     **probe})
    store_parts = tuple(p for p in STORE_PARTS if p in parts)
    if store_parts:
        run_store(out, work, store_parts)
    if "outage" in parts:
        run_outage(out, work)
    print(f"raw records in {work}; results in {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=LAB / "results" / "drills" / "capacity")
    parser.add_argument("--only", choices=PARTS, action="append", help="run this part alone (repeatable)")
    parser.add_argument("--summarize", type=Path, default=None, help="write summary-5b.md again from the folder's files")
    args = parser.parse_args(argv)
    if args.summarize:
        import summary_5b

        summary_5b.write(args.summarize)
        return 0
    run(args.out, tuple(args.only) if args.only else PARTS)
    try:
        import summary_5b

        summary_5b.write(args.out)
    except (ImportError, KeyError, FileNotFoundError) as exc:
        print(f"no summary yet ({type(exc).__name__}: {exc}); write it with --summarize", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
