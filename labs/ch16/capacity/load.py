"""Traffic for the drills: W2's and W3's model calls, shaped by the ledger's tokens, through a retry policy.

Chapter 16, step 5. A call here is one Chat Completions request with the tags and the trace id chapter 5's
gateway requires, sized in tokens: the prompt is `input_tokens` times four characters (the fake provider and
LiteLLM both count four characters a token), `max_tokens` is set, and `<<out:N>>` asks the fake provider for N
output tokens. `[wf:<workflow>]` lets the provider's log say whose call it was, and `[req:<id>]` matches the
provider's record of an attempt to the client's.

Each request runs under a policy from `retry.py`; every attempt is kept with its start, its end, its status, the
Retry-After it was given, which limit refused it and the gateway's own headers. A request is served when an
attempt answers 200. Times are seconds from the start of the scenario on the drill's clock.

`Workload` describes one stream: an open stream sends a request every `every_s` seconds whatever happened to the
last one, as alerts and questions arrive; a closed stream (`workers`) sends the next request as soon as the last
one ends, served or given up, as a burst of work queued behind a harness does.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

import retry

CHARS_PER_TOKEN = 4
GATEWAY_HEADERS = ("x-litellm-model-id", "x-litellm-overhead-duration-ms", "x-litellm-response-duration-ms",
                   "retry-after", "retry-after-ms", "llm_provider-retry-after", "llm_provider-retry-after-ms",
                   "x-ratelimit-remaining-tokens", "x-ratelimit-limit-tokens", "rate_limit_type")


@dataclass(frozen=True)
class Shape:
    """One call's size: the tokens in the prompt, the max_tokens it asks for, and the tokens it gets back."""

    input_tokens: int
    max_tokens: int | None
    output_tokens: int

    @property
    def estimate(self) -> int:
        """What a provider reserves up front: the prompt and max_tokens (fact sheet section 4)."""
        return self.input_tokens + (self.max_tokens or 0)

    @property
    def charge(self) -> int:
        return self.input_tokens + self.output_tokens


def prompt(workflow: str, request_id: str, shape: Shape) -> str:
    head = f"[wf:{workflow}] [req:{request_id}] <<out:{shape.output_tokens}>> "
    filler = max(0, shape.input_tokens * CHARS_PER_TOKEN - len(head))
    return head + ("lorem " * (filler // 6 + 1))[:filler]


def body(workflow: str, data_class: str, request_id: str, shape: Shape, alias: str = "larkspur-chat",
         trace_id: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"model": alias, "messages": [{"role": "user", "content": prompt(workflow, request_id, shape)}],
                           "metadata": {"tags": [f"workflow:{workflow}", f"data_class:{data_class}"],
                                        "trace_id": trace_id or uuid.uuid4().hex}}
    if shape.max_tokens:
        out["max_tokens"] = shape.max_tokens
    return out


def limiter(status: int | None, message: str) -> str:
    """Which limit, or which failure, an answer reports, from its status and its words."""
    text = message.lower()
    if status == 200:
        return "served"
    if status is None:
        return "no answer"
    if status == 429:
        if "requests per minute" in text and "request refused" in text:
            return "chapter 5's requests per minute"
        if "rate limit exceeded for api_key" in text or ("limit type" in text and "api_key" in text):
            return "the key's tokens per minute"
        if "max_parallel_requests" in text:
            return "the deployment's parallel requests"
        if "model rate limit exceeded" in text:
            return "the deployment's tokens per minute"
        if "no deployments available" in text:
            return "the router's cooldown"
        if "over its quota" in text or "too many tokens" in text:
            return "the provider's quota"
        return "a 429"
    if status == 422 and "budget" in text:
        return "the monthly budget"
    if status == 401 and "blocked" in text:
        return "the kill switch"
    if status == 400 and "request refused" in text:
        return "chapter 5's rules"
    return f"status {status}"


def message_of(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or "")[:300]
    return ""


@dataclass
class Clock:
    """The drill's clock: seconds since it started, and the wall time it started at, to place a provider's log."""

    t0: float = field(default_factory=time.perf_counter)
    wall0: float = field(default_factory=time.time)

    def now(self) -> float:
        return time.perf_counter() - self.t0


async def request(client: httpx.AsyncClient, url: str, key: str, workflow: str, data_class: str, shape: Shape,
                  policy: retry.Policy, clock: Clock, rng: random.Random, *, stream: str = "",
                  alias: str = "larkspur-chat") -> dict[str, Any]:
    """One request under `policy`: every attempt, and whether and when it was served."""
    request_id = uuid.uuid4().hex[:12]
    trace_id = uuid.uuid4().hex
    started = clock.now()
    attempts: list[dict[str, Any]] = []
    served_at = None
    while True:
        t = clock.now()
        try:
            response = await client.post(f"{url}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                                         json=body(workflow, data_class, request_id, shape, alias, trace_id))
            status, message = response.status_code, ("" if response.status_code == 200 else message_of(response))
            headers = {k: v for k, v in response.headers.items() if k.lower() in GATEWAY_HEADERS}
        except httpx.HTTPError as exc:
            status, message, headers = None, type(exc).__name__, {}
        attempt = {"t": round(t, 4), "t_end": round(clock.now(), 4), "status": status, "limit": limiter(status, message),
                   "retry_after": retry.retry_after_s(headers), "headers": headers}
        if status != 200:
            attempt["message"] = message[:200]
        attempts.append(attempt)
        if status == 200:
            served_at = attempt["t_end"]
            break
        wait = retry.next_wait(policy, len(attempts), status, headers, clock.now() - started, rng)
        if wait is None:
            break
        await asyncio.sleep(wait)
    return {"id": request_id, "trace_id": trace_id, "workflow": workflow, "stream": stream, "policy": policy.name,
            "t": round(started, 4), "served": served_at is not None, "served_at": served_at,
            "wait_s": round(served_at - started, 4) if served_at is not None else None,
            "attempts": attempts, "input_tokens": shape.input_tokens, "max_tokens": shape.max_tokens,
            "output_tokens": shape.output_tokens}


@dataclass(frozen=True)
class Workload:
    """One stream of one workflow's calls."""

    workflow: str
    data_class: str
    shape: Shape
    policy: retry.Policy
    start_s: float
    end_s: float
    every_s: float | None = None   # an open stream: one request every so many seconds
    workers: int = 0               # a closed stream: so many requests in flight, each sent when the last ends
    stream: str = ""


async def run(url: str, keys: Mapping[str, str], workloads: list[Workload], *, seed: int = 16,
              timeout_s: float = 60.0, limits: int = 200, clock: Clock | None = None) -> list[dict[str, Any]]:
    """Every request every workload made, on one clock, each workload's key taken from `keys`."""
    rng = random.Random(seed)
    clock = clock or Clock()
    results: list[dict[str, Any]] = []
    transport = httpx.AsyncHTTPTransport(limits=httpx.Limits(max_connections=limits, max_keepalive_connections=limits))
    async with httpx.AsyncClient(timeout=timeout_s, transport=transport) as client:

        async def one(w: Workload) -> None:
            results.append(await request(client, url, keys[w.workflow], w.workflow, w.data_class, w.shape, w.policy,
                                         clock, rng, stream=w.stream))

        async def open_stream(w: Workload) -> None:
            pending = []
            n = 0
            while True:
                at = w.start_s + n * (w.every_s or 0)
                if at >= w.end_s:
                    break
                await asyncio.sleep(max(0.0, at - clock.now()))
                pending.append(asyncio.create_task(one(w)))
                n += 1
            await asyncio.gather(*pending)

        async def worker(w: Workload) -> None:
            await asyncio.sleep(max(0.0, w.start_s - clock.now()))
            while clock.now() < w.end_s:
                await one(w)

        tasks = []
        for w in workloads:
            if w.every_s:
                tasks.append(asyncio.create_task(open_stream(w)))
            tasks.extend(asyncio.create_task(worker(w)) for _ in range(w.workers))
        await asyncio.gather(*tasks)
    return sorted(results, key=lambda r: r["t"])


def percentile(values: list[float], share: float) -> float | None:
    """Nearest rank, as the ledger's tables use it (`report.nearest_rank`)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(share * len(ordered)) - 1, 0)]
