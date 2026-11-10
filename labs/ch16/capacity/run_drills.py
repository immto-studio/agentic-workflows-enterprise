"""Step 5's drills against fakes: contention under three limits, retries, the gateway's own latency, the outage
drill, the database stopped, and the repeated-write check.

Chapter 16, step 5 (companion #14, O-D8 and O-D10). Everything runs on 127.0.0.1 with no model and no cloud:
`fake_provider.py` stands in for the managed model, step 4's PostgreSQL and database-backed gateway carry the keys,
and chapter 5's callback runs unchanged in every gateway that routes the workflows' aliases. The drills:

- **contention**: W3's incidents and W2's questions through step 4's gateway against a provider quota of 100,000
  tokens a minute, with W2 bursting large requests for a minute, under chapter 5's requests-per-minute limit
  alone, then a tokens-per-minute limit on each workflow's key that divides the quota (LiteLLM's key-level
  `tpm_limit`), then the same with headroom for the limiter's reset, then limits on the deployment under
  `enforce_model_rate_limits` with `max_parallel_requests` written out;
- **the limiter's cache**: each per-key limit once more with `census_hooks.py` reading the in-memory cache the
  limiter counts in, on step 4's gateway and on the same gateway without its budget alerts;
- **retries**: a throttled minute against the provider directly, under no retry, retries that honour
  Retry-After with jitter and a cap, and naive retries; the same two policies through step 4's gateway; and
  LiteLLM's router retrying on its own, to show when it waits for Retry-After and when it doesn't;
- **latency**: the gateway's own time per call, the client's time less the provider's, beside the overhead
  LiteLLM reports;
- **outage**: the primary failing with 5xx errors, then timeouts, then connection errors, with `allowed_fails: 2`
  and `cooldown_time: 30`: how long the gateway keeps sending to it, what W2's and W3's runs in flight see, and
  where each workflow's calls were served;
- **database**: PostgreSQL stopped under a workflow's calls and started again;
- **repeat**: what stops a run repeated after a failover from repeating a write (`repeat_write.py`, W3's code).

Run, in step 4's environment (chapter 5's requirements plus Prisma, `prisma generate` done), from labs/ch16:
    python capacity/run_drills.py --out results/<date>/capacity            # about 65 minutes
    python capacity/run_drills.py --limiter-cache results/<date>/capacity  # that drill alone, about 12 minutes
    python capacity/run_drills.py --summarize results/<date>/capacity      # the summary again from the files
Raw records stay in `capacity/_lab/drills-<stamp>/`.
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
BUDGET = LAB / "budget"
CH05 = LAB.parent / "ch05"
CH01 = LAB.parent / "ch01"
COMPANION = LAB.parents[1]
W3DIR = COMPANION / "workflows" / "w3-incident"
for folder in (HERE, BUDGET, CH01, CH05 / "harness", CH05 / "manifest", CH05 / "mcp-server", W3DIR / "harness",
               W3DIR / "state"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import httpx  # noqa: E402

import load  # noqa: E402
import retry  # noqa: E402
import stack  # noqa: E402

W2, W3 = "w2-ops-assistant", "w3-incident"
QUOTA = 100_000
DURATION_S = 150.0
BURST = (15.0, 75.0)
BURST_SHAPE = load.Shape(6000, 2000, 1000)   # a question that pulls a long log or a large manifest into the prompt
MAX_TOKENS = 256                             # set by the drill; chapter 5's harness sets none
PROVIDER_ARGS = ["--tpm", str(QUOTA), "--base-ms", "50", "--per-output-token-ms", "1.0"]
STEP4_CONFIG = BUDGET / "litellm.config.yaml"
CONTENTION = [
    {"name": "requests per minute alone", "config": "step4", "tpm_limit": None,
     "what": "chapter 5's callback limits each workflow to its manifest's requests a minute (W2 120, W3 60)"},
    {"name": "tokens per minute per key", "config": "step4", "tpm_limit": {W2: 75_000, W3: 25_000},
     "what": "each workflow's key gets a tpm_limit, the two dividing the provider's quota exactly"},
    {"name": "tokens per minute per key, with headroom", "config": "step4", "tpm_limit": {W2: 37_500, W3: 25_000},
     "what": "W2's share halved, so that W2's share twice and W3's demand fit the quota"},
    {"name": "deployment limits", "config": "deployment", "tpm_limit": None,
     "what": "tpm, rpm and max_parallel_requests on the deployment, under enforce_model_rate_limits"},
]
ROUNDS = 3
LATENCY_TPM_LIMIT = 10_000_000   # the limiter at work on every call, refusing none
OUTAGE_MODES = ("5xx", "timeout", "connection")
OUTAGE_PHASES = {"healthy_s": 10.0, "failing_s": 60.0, "healed_s": 50.0}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def epoch(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


def manifests() -> dict[str, dict]:
    import manifest as ch05_manifest

    return {w: m for w, m in ch05_manifest.load_manifests(stack.MANIFESTS).items() if w in (W2, W3)}


def shapes() -> dict[str, load.Shape]:
    """W2's and W3's calls to the managed alias, sized by the ledger's tokens per call."""
    ledger = json.loads((LAB / "results" / "2026-11-03" / "ledger.json").read_text(encoding="utf-8"))
    out = {}
    for key, workflow in (("w2", W2), ("w3", W3)):
        p = ledger["month"]["profiles"][key]
        calls = p["calls"] - (p.get("restricted_calls") or 0)
        tokens_in = (p["input"] - (p.get("restricted_input") or 0)) / calls
        tokens_out = (p["output"] - (p.get("restricted_output") or 0)) / calls
        out[workflow] = load.Shape(round(tokens_in), MAX_TOKENS, round(tokens_out))
    return out


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def nearest(values: list[float], share: float) -> float | None:
    found = load.percentile(values, share)
    return round(found, 4) if found is not None else None


# --- contention -------------------------------------------------------------------------------------------

def compact(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One line per request, small enough to commit: enough to recompute every number in the summary."""
    return [{"stream": r["stream"], "workflow": r["workflow"], "t": r["t"], "served": r["served"], "wait_s": r["wait_s"],
             "served_at": r["served_at"],
             "attempts": [[a["t"], a["status"], a["limit"], a["retry_after"]] for a in r["attempts"]],
             "estimate": r["input_tokens"] + (r["max_tokens"] or 0), "charge": r["input_tokens"] + r["output_tokens"]}
            for r in requests]


def describe(requests: list[dict[str, Any]]) -> dict[str, Any]:
    served = [r for r in requests if r["served"]]
    waits = [r["wait_s"] for r in served]
    attempts = sum(len(r["attempts"]) for r in requests)
    refused = Counter(a[2] for r in requests for a in r["attempts"] if a[1] != 200)
    return {"requests": len(requests), "served": len(served),
            "served_share": round(len(served) / len(requests), 4) if requests else None,
            "first_attempt": sum(1 for r in requests if r["attempts"][0][1] == 200),
            "attempts": attempts, "attempts_per_request": round(attempts / len(requests), 3) if requests else None,
            "wait_median_s": median(waits), "wait_p95_s": nearest(waits, 0.95),
            "wait_max_s": round(max(waits), 4) if waits else None, "refused_by": dict(sorted(refused.items())),
            "tokens_served": sum(r["charge"] for r in served)}


def provider_view(records: list[dict[str, Any]], wall0: float, quota: int = QUOTA) -> dict[str, Any]:
    """What the provider admitted and refused, by workflow, and the most it reserved in any sliding minute.

    The reserved peak sums each admitted request's estimate. It can pass the quota, since the provider checks a new
    reservation against what earlier requests settled at, which is less than they reserved.
    """
    admitted = sorted((r["t"] - wall0, r["estimate"], r["workflow"]) for r in records if r["status"] == 200)
    peak = 0.0
    for i, (t, _, _) in enumerate(admitted):
        held = sum(e for s, e, _ in admitted[: i + 1] if s > t - 60.0)
        peak = max(peak, held)
    by_workflow: dict[str, dict[str, int]] = {}
    for r in records:
        row = by_workflow.setdefault(r["workflow"] or "unmarked", {"admitted": 0, "refused": 0, "tokens_charged": 0})
        if r["status"] == 200:
            row["admitted"] += 1
            row["tokens_charged"] += int(r.get("charged") or 0)
        elif r["status"] == 429:
            row["refused"] += 1
    return {"quota": quota, "peak_reserved_in_a_minute": int(peak), "peak_over_quota": round(peak / quota, 4),
            "by_workflow": dict(sorted(by_workflow.items()))}


def contention_metrics(requests: list[dict[str, Any]], provider: dict[str, Any]) -> dict[str, Any]:
    inside = [r for r in requests if BURST[0] <= r["t"] < BURST[1]]
    return {"w3_in_the_burst": describe([r for r in inside if r["stream"] == "incident"]),
            "w3_whole_run": describe([r for r in requests if r["stream"] == "incident"]),
            "w2_steady_in_the_burst": describe([r for r in inside if r["stream"] == "steady"]),
            "w2_burst": describe([r for r in inside if r["stream"] == "burst"]),
            "provider": provider}


def workloads(sizes: dict[str, load.Shape]) -> list[load.Workload]:
    return [load.Workload(W3, "confidential", sizes[W3], retry.HONOUR, 0, DURATION_S, every_s=6, stream="incident"),
            load.Workload(W2, "internal", sizes[W2], retry.HONOUR, 0, DURATION_S, every_s=3, stream="steady"),
            load.Workload(W2, "internal", BURST_SHAPE, retry.HONOUR, BURST[0], BURST[1], workers=8, stream="burst")]


def drill_contention(s: stack.Stack, admin: Any, made: dict, work: Path, rounds: int = ROUNDS
                     ) -> tuple[list[dict], list[dict]]:
    """Each limit `rounds` times, the rounds interleaved, a fresh proxy and a fresh quota for every one.

    Who wins a freed slot in the provider's window is a race, so one round of a limit can differ a good deal from
    the next; every round is kept.
    """
    sizes = shapes()
    rows, lines = [], []
    for round_ in range(1, rounds + 1):
        for spec in CONTENTION:
            config = STEP4_CONFIG if spec["config"] == "step4" else HERE / "litellm.deployment.yaml"
            row, requests, _ = contention_round(s, admin, made, spec, round_, config, sizes,
                                                work / f"contention-{len(rows) + 1}-provider.json")
            lines += [{"limit": spec["name"], "round": round_, **r} for r in requests]
            rows.append(row)
            print("contention", spec["name"], round_, json.dumps(row["w3_in_the_burst"]), flush=True)
    return rows, lines


def contention_round(s: stack.Stack, admin: Any, made: dict, spec: dict[str, Any], round_: int, config: Path,
                     sizes: dict[str, load.Shape], provider_file: Path) -> tuple[dict, list[dict], load.Clock]:
    """One round of one limit, on a fresh proxy and a fresh quota: its row, its requests and its clock."""
    back = s.restart_proxy(config)
    for workflow in (W2, W3):
        admin.update(made[workflow]["token"], tpm_limit=(spec["tpm_limit"] or {}).get(workflow))
    time.sleep(3)
    s.control("primary", reset_quota=True, clear_log=True)
    clock = load.Clock()
    results = asyncio.run(load.run(s.url, {w: made[w]["key"] for w in (W2, W3)}, workloads(sizes),
                                   clock=clock, seed=16 + round_))
    records = s.provider_log("primary")
    requests = compact(results)
    row = {"name": spec["name"], "round": round_, "what": spec["what"], "config": config.name,
           "tpm_limit": spec["tpm_limit"], "proxy_back_in_s": back,
           **contention_metrics(requests, provider_view(records, clock.wall0))}
    provider_file.write_text(json.dumps(records), encoding="utf-8")
    return row, requests, clock


# --- the limiter's cache ----------------------------------------------------------------------------------

CENSUS_FILE = "CAPACITY_CENSUS_FILE"
CENSUS = [
    {"gateway": "step 4's", "config": "litellm.census.yaml", "limit": "tokens per minute per key"},
    {"gateway": "step 4's", "config": "litellm.census.yaml", "limit": "tokens per minute per key, with headroom"},
    {"gateway": "step 4's without alerts", "config": "litellm.census-no-alerts.yaml",
     "limit": "tokens per minute per key"},
    {"gateway": "step 4's without alerts", "config": "litellm.census-no-alerts.yaml",
     "limit": "tokens per minute per key, with headroom"},
]


def census_metrics(lines: list[dict[str, Any]], tokens: dict[str, str], wall0: float,
                   requests: list[dict[str, Any]]) -> dict[str, Any]:
    """When the usage cache filled and with what, when each key's window went before its time, and what the key
    refused and let through.

    A window is evicted when a snapshot finds it gone while the last snapshot that held it gave it more than a
    second still to live; a window that runs out its sixty seconds isn't counted.
    """
    snaps = sorted((line for line in lines if "size" in line), key=lambda line: line["t"])
    full = next((line for line in snaps if line["size"] >= line["max"]), None)
    largest = max(snaps, key=lambda line: line["size"]) if snaps else None
    keys: dict[str, Any] = {}
    for workflow, token in tokens.items():
        window = f"{{api_key:{token}}}:window"
        evicted, last = [], None
        for line in snaps:
            held = line["limiter"].get(window)
            if held is not None:
                last = (line["t"], held[1])
            elif last is not None and last[1] is not None and line["t"] < last[0] + last[1] - 1.0:
                evicted.append(round(line["t"] - wall0, 3))
                last = None
        refusals = [a[0] for r in requests if r["workflow"] == workflow for a in r["attempts"]
                    if a[2] == "the key's tokens per minute"]
        keys[workflow] = {"window_evicted_s": evicted[0] if evicted else None, "evictions": len(evicted),
                          "key_refusals": len(refusals),
                          "last_key_refusal_s": round(max(refusals), 3) if refusals else None}
    kinds = sorted(largest["kinds"].items(), key=lambda kv: (-kv[1], kv[0])) if largest else []
    return {"entries_max": snaps[0]["max"] if snaps else None, "snapshots": len(snaps),
            "errors": sum(1 for line in lines if "error" in line),
            "full_at_s": round(full["t"] - wall0, 3) if full else None,
            "largest": largest["size"] if largest else None, "kinds_when_largest": dict(kinds[:3]),
            "keys": keys,
            "w2_burst_tokens_served_60_to_120_s": sum(r["charge"] for r in requests if r["stream"] == "burst"
                                                      and r["served"] and 60.0 <= r["served_at"] < 120.0)}


def drill_limiter_cache(s: stack.Stack, admin: Any, made: dict, work: Path) -> tuple[list[dict], list[dict]]:
    """Each per-key limit once on step 4's gateway with the census callback, and once more without step 4's
    budget alerts, which keep a status per request in the cache the limiter counts in."""
    sizes = shapes()
    folder = work / "census"
    folder.mkdir(parents=True, exist_ok=True)
    rows, lines = [], []
    for i, setup in enumerate(CENSUS, 1):
        census = folder / f"census-{i}.jsonl"
        s.extra_env[CENSUS_FILE] = str(census)
        spec = next(c for c in CONTENTION if c["name"] == setup["limit"])
        row, requests, clock = contention_round(s, admin, made, spec, 1, HERE / setup["config"], sizes,
                                                folder / f"census-{i}-provider.json")
        found = [json.loads(line) for line in census.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows.append({"gateway": setup["gateway"], **row,
                     "cache": census_metrics(found, {w: made[w]["token"] for w in (W2, W3)}, clock.wall0, requests)})
        lines += [{"gateway": setup["gateway"], "limit": spec["name"], **r} for r in requests]
        print("census", setup["gateway"], spec["name"], json.dumps(rows[-1]["cache"]), flush=True)
    s.extra_env.pop(CENSUS_FILE, None)
    return rows, lines


# --- retries ----------------------------------------------------------------------------------------------

THROTTLED = load.Shape(1000, 500, 300)


def throttled_minute(requests: list[dict[str, Any]], records: list[dict[str, Any]], wall0: float,
                     minute: tuple[float, float] = (0.0, 60.0)) -> dict[str, Any]:
    offered = [r for r in requests if minute[0] <= r["t"] < minute[1]]
    calls = [a for r in requests for a in r["attempts"]]
    in_minute = [a for a in calls if minute[0] <= a[0] < minute[1]]
    at_provider = [r for r in records if minute[0] <= r["t"] - wall0 < minute[1]]
    served = [r for r in requests if r["served"]]
    return {"requests": len(requests), "served": len(served), "calls": len(calls),
            "calls_per_success": round(len(calls) / len(served), 3) if served else None,
            "requests_in_the_minute": len(offered), "calls_in_the_minute": len(in_minute),
            "load_over_offered": round(len(in_minute) / len(offered), 3) if offered else None,
            "provider_calls_in_the_minute": len(at_provider),
            "provider_refusals_in_the_minute": sum(1 for r in at_provider if r["status"] == 429),
            "last_served_s": round(max(r["served_at"] for r in served), 3) if served else None,
            "wait_median_s": median([r["wait_s"] for r in served])}


def drill_client_retries(url: str, key: str, control: Any, provider_log: Any, *, through: str,
                         policies: tuple[retry.Policy, ...], seconds: float = 60.0) -> list[dict[str, Any]]:
    """A minute of W2's requests at twice what the quota admits, once for each policy.

    The quota is fresh when each policy starts, so it admits the first forty requests and the rest of the minute
    is throttled: one request every 0.75 seconds, 1,500 tokens reserved each, against 60,000 a minute.
    """
    rows = []
    for policy in policies:
        control(reset_quota=True, clear_log=True)
        time.sleep(1)
        clock = load.Clock()
        stream = [load.Workload(W2, "internal", THROTTLED, policy, 0, seconds, every_s=0.75, stream=policy.name)]
        results = asyncio.run(load.run(url, {W2: key}, stream, clock=clock, timeout_s=30))
        requests = compact(results)
        row = {"through": through, "policy": policy.name, "max_attempts": policy.max_attempts,
               **throttled_minute(requests, provider_log(), clock.wall0, minute=(0.0, seconds))}
        row["refused_by"] = dict(sorted(Counter(a[2] for r in requests for a in r["attempts"] if a[1] != 200).items()))
        rows.append(row)
        print("retries", through, policy.name, json.dumps(row), flush=True)
    return rows


def drill_router_retries(work: Path) -> list[dict[str, Any]]:
    """LiteLLM's router retrying a provider's 429 on its own, two retries, three cases."""
    s = stack.Stack(work / "router", HERE / "litellm.retry.yaml", {"t1": ["--base-ms", "50"], "t2": ["--base-ms", "50"]},
                    {"CAPACITY_T1_URL": "t1", "CAPACITY_T2_URL": "t2"})
    cases = [("larkspur-chat-single", 5, 2, "one deployment in the group, Retry-After 5 s"),
             ("larkspur-chat-single", 90, 2, "one deployment in the group, Retry-After 90 s"),
             ("larkspur-chat-pair", 5, 1, "two deployments in the group, the first throttled, Retry-After 5 s")]
    rows = []
    try:
        s.start()
        for alias, retry_after, throttled, what in cases:
            s.restart_proxy()  # no cooldown carried from one case to the next
            for name in ("t1", "t2"):
                s.control(name, clear_log=True)
            s.control("t1", throttle_next=throttled, retry_after_s=retry_after)
            request_id = uuid.uuid4().hex[:12]
            started = time.time()
            r = httpx.post(f"{s.url}/chat/completions", headers={"Authorization": f"Bearer {s.master_key}"}, timeout=120,
                           json={"model": alias, "messages": [{"role": "user", "content": f"[wf:{W2}] [req:{request_id}] hi"}]})
            ended = time.time()
            attempts = sorted([(rec["t"], name, rec["status"]) for name in ("t1", "t2") for rec in s.provider_log(name)
                               if rec.get("request") == request_id])
            gaps = [round(b[0] - a[0], 3) for a, b in zip(attempts, attempts[1:])]
            rows.append({"case": what, "alias": alias, "retry_after_s": retry_after,
                         "attempts": [{"t": round(t - started, 3), "deployment": name, "status": status}
                                      for t, name, status in attempts],
                         "gaps_s": gaps, "status": r.status_code, "served_by": r.headers.get("x-litellm-model-id"),
                         "took_s": round(ended - started, 3),
                         "client_retry_after": r.headers.get("retry-after"),
                         "client_provider_retry_after": r.headers.get("llm_provider-retry-after")})
            print("router", what, json.dumps(rows[-1]), flush=True)
    finally:
        s.stop()
    return rows


# --- latency -----------------------------------------------------------------------------------------------

def drill_latency(url: str, key: str, workflow: str, data_class: str, provider_log: Any, control: Any, *, label: str,
                  calls: int = 60, concurrency: int = 1) -> dict[str, Any]:
    """The gateway's own time per call: the client's time less the provider's, matched by request id."""
    control(clear_log=True, reset_quota=True)
    shape = load.Shape(964, MAX_TOKENS, 152)
    timings: list[dict[str, Any]] = []

    def worker(n: int) -> None:
        client = httpx.Client(timeout=30)
        for _ in range(n):
            request_id = uuid.uuid4().hex[:12]
            started = time.perf_counter()
            r = client.post(f"{url}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                            json=load.body(workflow, data_class, request_id, shape))
            reported = r.headers.get("x-litellm-overhead-duration-ms")
            timings.append({"request": request_id, "status": r.status_code,
                            "client_ms": (time.perf_counter() - started) * 1000,
                            "litellm_overhead_ms": float(reported) if reported not in (None, "None") else None})

    worker(3)  # warm the gateway's caches; not counted
    timings.clear()
    threads = [threading.Thread(target=worker, args=(calls // concurrency,)) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    handled = {rec["request"]: rec.get("handled_ms") for rec in provider_log() if rec.get("request")}
    own = [t["client_ms"] - handled[t["request"]] for t in timings if t["status"] == 200 and handled.get(t["request"])]
    reported = [t["litellm_overhead_ms"] for t in timings if t["status"] == 200 and t["litellm_overhead_ms"] is not None]
    provider = [handled[t["request"]] for t in timings if handled.get(t["request"])]
    return {"setup": label, "calls": len(timings), "concurrency": concurrency,
            "answered": sum(1 for t in timings if t["status"] == 200),
            "client_ms": {"median": median([t["client_ms"] for t in timings]),
                          "p95": nearest([t["client_ms"] for t in timings], 0.95)},
            "provider_ms": {"median": median(provider), "p95": nearest(provider, 0.95)},
            "gateway_ms": {"median": median(own), "p95": nearest(own, 0.95), "max": round(max(own), 3) if own else None},
            "litellm_reports_ms": {"median": median(reported), "p95": nearest(reported, 0.95)}}


# --- the outage drill ---------------------------------------------------------------------------------------

def _w2_run(s: stack.Stack, key: str, on_second_call: Any) -> dict[str, Any]:
    """Chapter 1's loop with chapter 5's GatewayModel as W2: the failure starts between its two model calls."""
    from agent_loop import run_agent
    from fake_platform import pod_status
    from gateway_model import GatewayModel, pinned_tool_specs

    specs = pinned_tool_specs(CH05 / "mcp-server" / "tools.lock.json", {"get_pod_status"})
    model = GatewayModel(gateway_url=s.url, alias="larkspur-chat", tools=specs, trace_id=uuid.uuid4().hex,
                         workflow=W2, data_class="internal", api_key=key, timeout_s=30)
    count = {"n": 0}

    def flipping(messages: list[dict]) -> dict:
        count["n"] += 1
        if count["n"] == 2:
            on_second_call()
        return model(messages)

    try:
        answer, error = run_agent("Is claims-api healthy?", model=flipping, tools={"get_pod_status": pod_status},
                                  allowed={"get_pod_status": {"service"}}), None
    except httpx.HTTPStatusError as exc:
        answer, error = None, f"{exc.response.status_code}"
    return {"trace_id": model.trace_id, "answered": answer is not None, "answer": (answer or "")[:80], "error": error,
            "calls": [round(c.latency_s, 3) for c in model.calls]}


def _w3_triage(s: stack.Stack, key: str, on_second_call: Any | None) -> dict[str, Any]:
    """W3's triage loop with W3's GatewayModel, unchanged; the failure starts between its two model calls."""
    import loop as w3loop
    from fake_platform import pod_status
    from gateway_model import pinned_tool_specs

    specs = pinned_tool_specs(CH05 / "mcp-server" / "tools.lock.json", {"get_pod_status"})
    model = w3loop.W3GatewayModel(gateway_url=s.url, alias="larkspur-chat", tools=specs, trace_id=uuid.uuid4().hex,
                                  workflow=W3, data_class="confidential", api_key=key, timeout_s=30)
    count = {"n": 0}

    def flipping(messages: list[dict]) -> dict:
        count["n"] += 1
        if count["n"] == 2 and on_second_call is not None:
            on_second_call()
        return model(messages)

    try:
        out = w3loop.run_steps("Is claims-api healthy?", flipping, {"get_pod_status": pod_status},
                               {"get_pod_status": {"service"}}, {"restart_deployment"})
        return {"trace_id": model.trace_id, "outcome": out.kind, "reason": out.reason, "text": out.text[:90],
                "raised": None, "model_calls": count["n"]}
    except httpx.HTTPStatusError as exc:
        return {"trace_id": model.trace_id, "outcome": None, "reason": None, "text": None,
                "raised": f"HTTPStatusError {exc.response.status_code}", "model_calls": count["n"]}


def outage_mode(s: stack.Stack, mode: str) -> dict[str, Any]:
    """One failure mode: the loops, the runs in flight, and every record the drill needs to time the cooldown."""
    s.restart_proxy()  # no cooldown or request-rate window carried over from the previous mode
    for name in ("primary", "fallback", "self-hosted"):
        if s.fakes[name].process is None:
            s.start_fake(name)
        s.control(name, mode="ok", clear_log=True)
    events: list[dict[str, Any]] = []
    stop = threading.Event()

    def loop_calls(workflow: str, data_class: str, every_s: float) -> None:
        client = httpx.Client(timeout=30)
        while not stop.is_set():
            started = time.time()
            request_id = uuid.uuid4().hex[:12]
            try:
                r = client.post(f"{s.url}/chat/completions", headers={"Authorization": f"Bearer {s.master_key}"},
                                json=load.body(workflow, data_class, request_id, load.Shape(200, 64, 20)))
                status, model_id = r.status_code, r.headers.get("x-litellm-model-id")
                retry_after, message = r.headers.get("retry-after"), ("" if status == 200 else load.message_of(r))
            except httpx.HTTPError as exc:
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
    time.sleep(OUTAGE_PHASES["healthy_s"])
    # Both runs make their first model call on a healthy primary; the failure starts once both are between
    # their first and second calls, so each meets it in flight. Its time is taken once the switch has taken effect
    # (the fake's mode set, or its process stopped), so that no call counted as sent during the failure could
    # have reached a primary that was still healthy.
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
    in_flight = [threading.Thread(target=lambda: runs.__setitem__("w2_in_flight", _w2_run(s, s.master_key, flip_once))),
                 threading.Thread(target=lambda: runs.__setitem__("w3_in_flight", _w3_triage(s, s.master_key, flip_once)))]
    for t in in_flight:
        t.start()
    for t in in_flight:
        t.join(timeout=90)
    t_fail = flipped.get("t") or time.time()
    time.sleep(max(0.0, t_fail + 20.0 - time.time()))
    runs["w3_during_cooldown"] = _w3_triage(s, s.master_key, None)
    time.sleep(max(0.0, t_fail + OUTAGE_PHASES["failing_s"] - time.time()))
    t_heal = time.time()
    if mode == "connection":
        s.start_fake("primary")
    else:
        s.control("primary", mode="ok")
    time.sleep(OUTAGE_PHASES["healed_s"])
    stop.set()
    for w in workers:
        w.join(timeout=60)
    primary = s.provider_log("primary")
    fallback = s.provider_log("fallback")
    return {"mode": mode, "t_fail": t_fail, "t_heal": t_heal, "events": events, "runs": runs,
            "primary": [{k: r.get(k) for k in ("t", "t_end", "workflow", "status")} for r in primary],
            "fallback": [{k: r.get(k) for k in ("t", "t_end", "workflow", "status")} for r in fallback]}


def outage_metrics(raw: dict[str, Any], lines: list[dict[str, Any]], allowed_fails: int, cooldown_s: float) -> dict:
    """The cooldown timed from the gateway's own lines, and what each workflow got, relative to the failure."""
    t_fail, t_heal = raw["t_fail"], raw["t_heal"]
    window = [line for line in lines if t_fail - 1 <= epoch(line["ts"]) <= t_heal + 60]
    primary_failures = sorted(epoch(line["ts"]) - t_fail for line in window
                              if line.get("event") == "failed" and line.get("deployment") == "primary"
                              and line.get("error") != "RouterRateLimitError")
    cooldown_answers = sorted(e["t"] - t_fail for e in raw["events"] if e["limit"] == "the router's cooldown")
    # Cycles: the failures that reach the primary, then the cooldown that follows them.
    cycles: list[dict[str, Any]] = []
    for t in primary_failures:
        if t < t_heal - t_fail:
            if not cycles or t - cycles[-1]["last_failure_s"] > 10:
                cycles.append({"first_failure_s": round(t, 3), "last_failure_s": round(t, 3), "failures": 0})
            cycles[-1]["failures"] += 1
            cycles[-1]["last_failure_s"] = round(t, 3)
    for cycle in cycles:
        later = [c for c in cooldown_answers if c >= cycle["last_failure_s"] - 0.5]
        cycle["cooldown_seen_s"] = round(later[0], 3) if later else None
    served_primary_after = sorted(e["t_end"] - t_heal for e in raw["events"]
                                  if e["t"] >= t_heal and e["status"] == 200 and e["served_by"] == "primary")
    # A call counts as made during the failure when it was sent after the failure took effect and answered before
    # the primary healed; one sent just before the heal can be held by the failure and answered by the healed primary.
    failing = [e for e in raw["events"] if t_fail <= e["t"] and e["t_end"] < t_heal]

    def tally(workflow: str) -> dict[str, Any]:
        mine = [e for e in failing if e["workflow"] == workflow]
        latencies = [e["t_end"] - e["t"] for e in mine if e["status"] == 200]
        return {"calls": len(mine), "statuses": dict(sorted(Counter(str(e["status"]) for e in mine).items())),
                "served_by": dict(sorted(Counter(e["served_by"] or "none" for e in mine if e["status"] == 200).items())),
                "kinds": dict(sorted(Counter(e["limit"] for e in mine if e["status"] != 200).items())),
                "latency_median_s": median(latencies), "latency_max_s": round(max(latencies), 3) if latencies else None}

    def regions(workflow: str) -> dict[str, int]:
        return dict(sorted(Counter(line.get("region") or "none" for line in window
                                   if line.get("event") == "call" and line.get("workflow") == workflow).items()))

    w3_failed = [line for line in window if line.get("event") == "failed" and line.get("workflow") == W3]
    w2_mislabelled = [line for line in window if line.get("event") == "failed" and line.get("workflow") == W2
                      and line.get("deployment") == "fallback" and line.get("error") == "RouterRateLimitError"]
    run_lines = {name: [{"deployment": line.get("deployment"), "region": line.get("region"), "event": line["event"],
                         "fallback": line.get("fallback")}
                        for line in lines if line.get("trace_id") == run.get("trace_id") and line["event"] in ("call", "failed")]
                 for name, run in raw["runs"].items()}
    return {"mode": raw["mode"], "allowed_fails": allowed_fails, "cooldown_time_s": cooldown_s,
            "failures_at_the_primary": [round(t, 3) for t in primary_failures], "cycles": cycles,
            "first_cooldown_answer_s": round(cooldown_answers[0], 3) if cooldown_answers else None,
            "sent_to_the_failing_primary_s": cycles[0]["last_failure_s"] if cycles else None,
            "failures_before_the_first_cooldown": cycles[0]["failures"] if cycles else 0,
            "healed_at_s": round(t_heal - t_fail, 3),
            "primary_served_again_after_heal_s": round(served_primary_after[0], 3) if served_primary_after else None,
            "w2": tally(W2), "w3": tally(W3), "w2_regions": regions(W2), "w3_regions": regions(W3),
            "w3_failed_lines_with_fallback_disabled": sum(1 for line in w3_failed if line.get("fallbacks_disabled")),
            "w3_failed_lines": len(w3_failed),
            "w2_cooldown_failures_logged_as_the_fallback": len(w2_mislabelled),
            "runs": raw["runs"], "run_lines": run_lines}


def drill_outage(work: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict]]:
    import yaml

    config = HERE / "litellm.outage.yaml"
    router = yaml.safe_load(config.read_text(encoding="utf-8"))["router_settings"]
    speed = ["--base-ms", "50", "--per-output-token-ms", "1.0"]  # as the contention drill's provider, with no quota
    s = stack.Stack(work / "outage", config, {"primary": speed, "fallback": speed, "self-hosted": speed},
                    {"CAPACITY_PRIMARY_URL": "primary", "CAPACITY_FALLBACK_URL": "fallback",
                     "CAPACITY_SELF_HOSTED_URL": "self-hosted"})
    rows, latency, events = [], [], []
    try:
        s.start()
        log, control = (lambda: s.provider_log("primary")), (lambda **b: s.control("primary", **b))
        # The same calls straight to the provider first: the client's and the provider's own overhead, which the
        # gateway's rows include and the baseline lets a reader take away.
        latency.append(drill_latency(f"{s.fakes['primary'].url}/v1", "unused", W2, "internal", log, control,
                                     label="the provider alone, no gateway"))
        latency.append(drill_latency(s.url, s.master_key, W2, "internal", log, control,
                                     label="chapter 5's gateway, no database"))
        # A provider four times as fast leaves the gateway's work after each answer less time to hide in.
        s.restart_proxy()
        s.control("primary", per_output_token_ms=0)
        latency.append(drill_latency(s.url, s.master_key, W2, "internal", log, control,
                                     label="chapter 5's gateway, the provider answering in 50 ms"))
        s.control("primary", per_output_token_ms=1.0)
        for mode in OUTAGE_MODES:
            raw = outage_mode(s, mode)
            rows.append(outage_metrics(raw, s.gateway_lines(), router["allowed_fails"], router["cooldown_time"]))
            events += [{"mode": mode, **{k: (round(v - raw["t_fail"], 3) if k in ("t", "t_end") else v)
                                         for k, v in e.items()}} for e in raw["events"]]
            (work / f"outage-{mode}.json").write_text(json.dumps(raw), encoding="utf-8")
            print("outage", mode, json.dumps({k: rows[-1][k] for k in ("cycles", "w2", "w3")}), flush=True)
    finally:
        s.stop()
    return rows, latency, events


# --- the database stopped -----------------------------------------------------------------------------------

def key_spend(s: stack.Stack, token: str) -> float:
    import psycopg

    with psycopg.connect(s.cluster.url("litellm"), autocommit=True, connect_timeout=5) as conn:
        return float(conn.execute('SELECT spend FROM "LiteLLM_VerificationToken" WHERE token = %s', (token,)).fetchone()[0])


def settled_spend(s: stack.Stack, token: str, quiet_s: float = 12.0, max_s: float = 60.0) -> float:
    """The key's spend once LiteLLM's batch writer has stopped changing it (step 4 found it writes every ~10 s)."""
    started, last = time.monotonic(), key_spend(s, token)
    since = time.monotonic()
    while time.monotonic() - started < max_s:
        time.sleep(0.5)
        spend = key_spend(s, token)
        if spend != last:
            last, since = spend, time.monotonic()
        elif time.monotonic() - since >= quiet_s:
            break
    return last


def drill_database(s: stack.Stack, made: dict, *, before_s: float = 10, down_s: float = 90, after_s: float = 60) -> dict:
    """W2 calls once a second, half its manifest's rate; PostgreSQL stops for a minute and a half and starts again.

    The calls are an open stream, each sent on the second whatever happened to the last, so a refusal that holds
    its caller doesn't hide when the database came back. The key's spend is read before and after, once LiteLLM's
    batch writer has gone quiet for twenty seconds, and set against the cost of the calls the gateway answered,
    from chapter 5's cost lines, to see whether the spend of calls answered while the database was gone reached it.
    """
    key, token = made[W2]["key"], made[W2]["token"]
    spend_before = settled_spend(s, token)
    clock = load.Clock()
    total = before_s + down_s + after_s
    stream = [load.Workload(W2, "internal", load.Shape(200, 64, 20), retry.NONE, 0, total, every_s=1.0, stream="db")]
    box: dict[str, Any] = {}
    worker = threading.Thread(target=lambda: box.setdefault(
        "results", asyncio.run(load.run(s.url, {W2: key}, stream, clock=clock, timeout_s=120))), daemon=True)
    worker.start()
    time.sleep(max(0.0, before_s - clock.now()))
    t_stop = clock.now()
    s.cluster.stop()
    time.sleep(down_s)
    t_start = clock.now()
    s.cluster.start()
    s.cluster.wait()
    worker.join(timeout=total + 300)
    spend_after = settled_spend(s, token, quiet_s=20.0, max_s=180.0)
    calls = [{"t": round(r["t"] - t_stop, 3), "t_end": round(r["attempts"][0]["t_end"] - t_stop, 3),
              "status": r["attempts"][0]["status"], "message": (r["attempts"][0].get("message") or "")[:200],
              "retry_after": r["attempts"][0]["retry_after"]} for r in box.get("results", [])]
    return database_metrics(calls, t_start - t_stop, s.gateway_lines(), clock.wall0, t_stop, clock.now(),
                            spend_after - spend_before) | {"events": calls}


def database_metrics(calls: list[dict[str, Any]], up: float, lines: list[dict[str, Any]], wall0: float, t_stop: float,
                     t_end: float, counted: float) -> dict[str, Any]:
    """The calls sent while PostgreSQL was down, split by what answered them, and the spend that reached it.

    `calls` are relative to the stop; `up` is when PostgreSQL started again. A call sent while it was down was
    answered from LiteLLM's key cache until the first refusal; after that, a call was refused unless it was still
    waiting for the database when the database came back.
    """
    down = [c for c in calls if 0 <= c["t"] < up]
    after = [c for c in calls if c["t"] >= up]
    refusals = [c for c in down if c["status"] != 200]
    first_refusal = refusals[0]["t"] if refusals else None
    cached = [c for c in down if c["status"] == 200 and (first_refusal is None or c["t"] < first_refusal)]
    waited = [c for c in down if c["status"] == 200 and first_refusal is not None and c["t"] >= first_refusal]
    back = next((c for c in after if c["status"] == 200), None)
    wall_stop, wall_start = wall0 + t_stop, wall0 + t_stop + up
    mine = [line for line in lines if line.get("event") == "call" and line.get("workflow") == W2
            and wall0 <= epoch(line["ts"]) <= wall0 + t_end]
    answered_cost = sum(line.get("cost_usd") or 0.0 for line in mine)
    while_down_cost = sum(line.get("cost_usd") or 0.0 for line in mine if wall_stop <= epoch(line["ts"]) < wall_start)
    return {"stopped_for_s": round(up, 3), "calls_before": sum(1 for c in calls if c["t"] < 0),
            "calls_while_down": len(down), "while_down": dict(sorted(Counter(str(c["status"]) for c in down).items())),
            "answered_from_the_key_cache": len(cached),
            "the_cache_answered_until_s": round(max(c["t_end"] for c in cached), 3) if cached else None,
            "first_refusal_sent_at_s": first_refusal,
            "refusals": len(refusals),
            "refusal_held_its_caller_s": {"median": median([c["t_end"] - c["t"] for c in refusals]),
                                          "max": round(max(c["t_end"] - c["t"] for c in refusals), 3) if refusals else None},
            "answered_after_waiting_for_the_database": len(waited),
            "messages_while_down": dict(Counter(c["message"][:120] for c in refusals).most_common(4)),
            "after_restart": dict(sorted(Counter(str(c["status"]) for c in after).items())),
            "first_call_answered_after_restart_sent_s": round(back["t"] - up, 3) if back else None,
            "cost_of_answered_calls_usd": round(answered_cost, 8), "of_which_while_down_usd": round(while_down_cost, 8),
            "spend_counted_usd": round(counted, 8),
            "spend_counted_over_answered": round(counted / answered_cost, 4) if answered_cost else None}


# --- the whole run ------------------------------------------------------------------------------------------

def versions() -> dict[str, Any]:
    import platform
    from importlib import metadata

    found = {}
    for name in ("litellm", "prisma", "psycopg", "httpx", "uvicorn", "starlette"):
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = None
    found["python"] = platform.python_version()
    return found


def database_stack(folder: Path) -> stack.Stack:
    """Step 4's PostgreSQL and database-backed gateway, with the fake provider as the primary."""
    return stack.Stack(folder, STEP4_CONFIG, {"primary": PROVIDER_ARGS, "self-hosted": []},
                       {"BUDGET_PRIMARY_URL": "primary", "BUDGET_SELF_HOSTED_URL": "self-hosted",
                        "CAPACITY_PRIMARY_URL": "primary", "CAPACITY_SELF_HOSTED_URL": "self-hosted"},
                       database=True, receiver=True)


def write_limiter_cache(out: Path, rows: list[dict], lines: list[dict], master_key: str) -> None:
    import postgres
    import record

    record.write_json(out / "limiter-cache.json", {"date": now_utc().date().isoformat(), "versions": versions(),
                                                    "postgres": postgres.VERSION, "rounds": rows},
                      secrets=(master_key,))
    (out / "limiter-cache-requests.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in lines),
                                                      encoding="utf-8", newline="\n")


def run_limiter_cache(out: Path) -> list[dict]:
    """The limiter-cache drill alone, on a database stack of its own."""
    import keys

    work = HERE / "_lab" / f"census-{now_utc().strftime('%Y%m%dT%H%M%SZ')}"
    work.mkdir(parents=True)
    s = database_stack(work / "db")
    try:
        s.start()
        admin = keys.Admin(s.url, s.master_key)
        made = keys.provision(admin, manifests())
        s.control("primary", tpm=QUOTA)
        rows, lines = drill_limiter_cache(s, admin, made, work)
    finally:
        s.stop()
    out.mkdir(parents=True, exist_ok=True)
    write_limiter_cache(out, rows, lines, s.master_key)
    return rows


def run_all(out: Path) -> dict[str, Any]:
    import keys
    import postgres
    import record
    import repeat_write

    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    work = HERE / "_lab" / f"drills-{stamp}"
    work.mkdir(parents=True)
    result: dict[str, Any] = {"date": now_utc().date().isoformat(), "versions": versions(), "postgres": postgres.VERSION,
                              "quota_tpm": QUOTA, "burst": list(BURST), "duration_s": DURATION_S,
                              "shapes": {w: vars(sh) | {"estimate": sh.estimate} for w, sh in shapes().items()},
                              "burst_shape": vars(BURST_SHAPE) | {"estimate": BURST_SHAPE.estimate},
                              "policies": {p.name: vars(p) for p in retry.POLICIES.values()}}
    result["repeat"] = repeat_write.check(work / "repeat")
    print("repeat", json.dumps(result["repeat"]["rows"])[:300], flush=True)
    result["router_retries"] = drill_router_retries(work)

    # The provider alone, no gateway: only its fake is started.
    direct = stack.Stack(work / "direct", HERE / "litellm.retry.yaml", {"throttled": ["--tpm", "60000", "--base-ms", "50"]}, {})
    try:
        direct.start_fake("throttled")
        result["client_retries"] = drill_client_retries(
            f"{direct.fakes['throttled'].url}/v1", "unused", lambda **b: direct.control("throttled", **b),
            lambda: direct.provider_log("throttled"), through="the provider directly",
            policies=(retry.NONE, retry.HONOUR, retry.NAIVE))
    finally:
        direct.stop()

    outage, latency, outage_events = drill_outage(work)
    result["outage"] = outage
    result["latency"] = latency

    s = database_stack(work / "db")
    contention_lines: list[dict] = []
    census: list[dict] = []
    census_lines: list[dict] = []
    database_events: list[dict] = []
    try:
        s.start()
        result["proxy_start_s"] = s.proxy_starts[0]
        admin = keys.Admin(s.url, s.master_key)
        made = keys.provision(admin, manifests())
        s.control("primary", tpm=None)
        # Each setup on a fresh proxy, so that no limiter window carries calls from the one before. The key's
        # tpm_limit is set far above what the calls use: the limiter reserves and settles every call and refuses none.
        result["latency"].append(drill_latency(s.url, made[W2]["key"], W2, "internal", lambda: s.provider_log("primary"),
                                               lambda **b: s.control("primary", **b),
                                               label="step 4's gateway, W2's virtual key"))
        admin.update(made[W2]["token"], tpm_limit=LATENCY_TPM_LIMIT)
        for label, calls, at_once in (("step 4's gateway, W2's key with a tpm_limit", 60, 1),
                                      ("step 4's gateway, W2's key with a tpm_limit, 8 at once", 96, 8)):
            s.restart_proxy(STEP4_CONFIG)
            result["latency"].append(drill_latency(s.url, made[W2]["key"], W2, "internal",
                                                   lambda: s.provider_log("primary"), lambda **b: s.control("primary", **b),
                                                   label=label, calls=calls, concurrency=at_once))
        admin.update(made[W2]["token"], tpm_limit=None)
        # Step 4's gateway has no fallback configured, so a provider's 429 reaches the harness.
        s.restart_proxy(STEP4_CONFIG)
        s.control("primary", tpm=60_000)
        result["client_retries"] += drill_client_retries(
            s.url, made[W2]["key"], lambda **b: s.control("primary", **b), lambda: s.provider_log("primary"),
            through="step 4's gateway", policies=(retry.HONOUR, retry.NAIVE))
        s.control("primary", tpm=QUOTA)
        result["contention"], contention_lines = drill_contention(s, admin, made, work)
        census, census_lines = drill_limiter_cache(s, admin, made, work)
        s.restart_proxy(STEP4_CONFIG)
        s.control("primary", tpm=None)
        time.sleep(3)
        database = drill_database(s, made)
        result["database"] = {k: v for k, v in database.items() if k != "events"}
        database_events = database["events"]
    finally:
        s.stop()
    record.write_json(out / "drills.json", result, secrets=(s.master_key,))
    write_limiter_cache(out, census, census_lines, s.master_key)
    for name, rows in (("contention-requests.jsonl", contention_lines), ("outage-events.jsonl", outage_events),
                       ("database-events.jsonl", database_events)):
        (out / name).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                                encoding="utf-8", newline="\n")
    print(f"raw records in {work}; results in {out}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=LAB / "results" / "drills" / "capacity")
    parser.add_argument("--summarize", type=Path, default=None, help="write summary.md again from the folder's files")
    parser.add_argument("--limiter-cache", type=Path, default=None,
                        help="run the limiter-cache drill alone into this folder, then write its summary again")
    args = parser.parse_args(argv)
    import summary

    if args.summarize:
        summary.write(args.summarize)
        return 0
    if args.limiter_cache:
        run_limiter_cache(args.limiter_cache)
        summary.write(args.limiter_cache)
        return 0
    run_all(args.out)
    import calculator
    import record

    record.write_json(args.out / "calculator.json", calculator.report())
    summary.write(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
