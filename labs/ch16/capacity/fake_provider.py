"""A fake model provider with a tokens-per-minute quota, the way the three clouds describe theirs.

Chapter 16, step 5 (companion #14, O-D8). Fact sheet section 4 says how a managed model's quota works on
each cloud. Bedrock takes "Total input tokens + max_tokens" from the quota when a request arrives and settles
it at the tokens actually used once the response is done; Azure estimates each request from the prompt and
`max_tokens` and answers a request over the limit with 429, `retry-after-ms` and `x-ratelimit-*` headers;
both say to honour Retry-After. This server does the same against a quota of its own, so the gateway and the
harness can be driven into throttling on the workstation:

- **reserve**: a request's estimate is its input tokens, counted from the prompt at four characters a token
  (LiteLLM's own estimate, fact sheet 8.1), plus `max_tokens`, or `default_max_tokens` when the request sets
  none. The estimate must fit in what the quota's sliding 60-second window has left, or the answer is 429 with
  `Retry-After` in whole seconds (the HTTP form, and the only one LiteLLM's router reads), `retry-after-ms`,
  `x-ratelimit-limit-tokens` and `x-ratelimit-remaining-tokens`;
- **settle**: once the answer is written, the reservation is replaced by the input tokens plus the output
  tokens times `burndown` (Bedrock's output burndown, 1 unless set);
- **latency**: `base_ms` plus `per_output_token_ms` for each output token, slept before the answer;
- **output**: a request asks for its output length with the marker `<<out:N>>` in its last user message, cut
  at `max_tokens`; a request with tools is answered by chapter 5's rule model, as chapter 5's fake backend
  answers, so a harness can run its loop through the gateway;
- **failures**, switched at run time with `POST /control`: `5xx` answers 503 at once; `timeout` holds the
  request for `hang_s` and then answers 504, long after any gateway's timeout. A connection error is the
  process stopped: the drills stop this server, and the port refuses connections until they start it again;
- **throttle**: `POST /control {"throttle_next": n, "retry_after_s": s}` answers the next n requests 429 with
  that Retry-After whatever the quota says, which is how the drills show what LiteLLM's router does with it.

Every request is logged in memory with its arrival, its end, the workflow named by a `[wf:<name>]` marker,
the request named by a `[req:<id>]` marker, the status, the estimate and the charge (`GET /log`). Binds
127.0.0.1 only.

Run:  python capacity/fake_provider.py --name primary --port 8811 --tpm 60000 --base-ms 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CH05_GATEWAY = HERE.parents[1] / "ch05" / "gateway"
HOST = "127.0.0.1"
CHARS_PER_TOKEN = 4  # LiteLLM's DEFAULT_CHARS_PER_TOKEN (fact sheet 8.1)
WINDOW_S = 60.0
OUT_MARKER = re.compile(r"<<out:(\d+)>>")
WORKFLOW_MARKER = re.compile(r"\[wf:([A-Za-z0-9_.-]+)\]")
REQUEST_MARKER = re.compile(r"\[req:([A-Za-z0-9]+)\]")
DEFAULT_OUTPUT_TOKENS = 64
MODES = ("ok", "5xx", "timeout")


# --- the quota -----------------------------------------------------------------------------------------

def count_tokens(text: str) -> int:
    """Input tokens as the fake counts them: four characters a token, at least one for any text."""
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN)) if text else 0


def prompt_text(messages: list[dict[str, Any]]) -> str:
    parts = []
    for message in messages or []:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):  # content parts
            parts.extend(str(p.get("text", "")) for p in content if isinstance(p, dict))
        for call in message.get("tool_calls") or []:
            parts.append(json.dumps(call.get("function", {})))
    return "".join(parts)


@dataclass
class Charge:
    at: float
    amount: float


@dataclass
class TokenQuota:
    """Tokens a minute over a sliding window: reserve up front, settle after, refuse with the wait it needs.

    `tpm` of None means no quota. The clock is injectable so the tests can move time.
    """

    tpm: int | None
    window_s: float = WINDOW_S
    clock: Callable[[], float] = time.monotonic
    charges: dict[str, Charge] = field(default_factory=dict)

    def _expire(self, now: float) -> None:
        for key in [k for k, c in self.charges.items() if c.at <= now - self.window_s]:
            del self.charges[key]

    def used(self, now: float | None = None) -> float:
        now = self.clock() if now is None else now
        self._expire(now)
        return sum(c.amount for c in self.charges.values())

    def remaining(self, now: float | None = None) -> float:
        return float("inf") if self.tpm is None else self.tpm - self.used(now)

    def wait_for(self, estimate: float, now: float | None = None) -> float:
        """Seconds until `estimate` fits, as the charges in the window expire one by one."""
        now = self.clock() if now is None else now
        if self.tpm is None:
            return 0.0
        if estimate > self.tpm:
            return self.window_s  # never fits; the caller is told a whole window
        used = self.used(now)
        if used + estimate <= self.tpm:
            return 0.0
        for charge in sorted(self.charges.values(), key=lambda c: c.at):
            used -= charge.amount
            if used + estimate <= self.tpm:
                return max(0.0, charge.at + self.window_s - now)
        return self.window_s

    def reserve(self, estimate: float) -> tuple[str | None, float]:
        """(the reservation's key, 0) when it fits; (None, seconds to wait) when it doesn't."""
        now = self.clock()
        wait = self.wait_for(estimate, now)
        if wait > 0:
            return None, wait
        key = uuid.uuid4().hex
        self.charges[key] = Charge(now, float(estimate))
        return key, 0.0

    def settle(self, key: str | None, actual: float) -> None:
        """Replace the reservation with what the request used; its place in the window stays."""
        if key is not None and key in self.charges:
            self.charges[key].amount = float(actual)

    def release(self, key: str | None) -> None:
        if key is not None:
            self.charges.pop(key, None)


def retry_after_header(wait_s: float) -> str:
    """Whole seconds, rounded up, never 0: the HTTP form of Retry-After."""
    return str(max(1, math.ceil(wait_s)))


# --- the provider ---------------------------------------------------------------------------------------

@dataclass
class Settings:
    name: str
    tpm: int | None = None
    default_max_tokens: int = 4096
    burndown: float = 1.0
    base_ms: float = 50.0
    per_output_token_ms: float = 0.0
    hang_s: float = 30.0
    mode: str = "ok"


class Provider:
    """The quota, the failure mode and the log; the HTTP layer below is thin."""

    def __init__(self, settings: Settings, clock: Callable[[], float] = time.monotonic) -> None:
        self.settings = settings
        self.quota = TokenQuota(settings.tpm, clock=clock)
        self.log: list[dict[str, Any]] = []
        self.throttle_next = 0
        self.throttle_retry_after_s = 1.0
        self.lock = threading.Lock()
        self.started = time.time()

    def control(self, body: dict[str, Any]) -> dict[str, Any]:
        s = self.settings
        if "mode" in body:
            if body["mode"] not in MODES:
                raise ValueError(f"mode must be one of {MODES}")
            s.mode = body["mode"]
        for key in ("base_ms", "per_output_token_ms", "hang_s", "burndown"):
            if key in body:
                setattr(s, key, float(body[key]))
        if "default_max_tokens" in body:
            s.default_max_tokens = int(body["default_max_tokens"])
        if "tpm" in body:
            s.tpm = None if body["tpm"] is None else int(body["tpm"])
            self.quota = TokenQuota(s.tpm, clock=self.quota.clock)
        if body.get("reset_quota"):
            self.quota.charges.clear()
        if body.get("clear_log"):
            self.log.clear()
        if "throttle_next" in body:
            self.throttle_next = int(body["throttle_next"])
            self.throttle_retry_after_s = float(body.get("retry_after_s", 1.0))
        return self.state()

    def state(self) -> dict[str, Any]:
        s = self.settings
        return {"name": s.name, "mode": s.mode, "tpm": s.tpm, "used": round(self.quota.used(), 1),
                "default_max_tokens": s.default_max_tokens, "burndown": s.burndown, "base_ms": s.base_ms,
                "per_output_token_ms": s.per_output_token_ms, "hang_s": s.hang_s, "requests": len(self.log),
                "throttle_next": self.throttle_next}

    @staticmethod
    def output_tokens(messages: list[dict[str, Any]], max_tokens: int | None) -> int:
        last_user = next((m.get("content") for m in reversed(messages or []) if m.get("role") == "user"), "")
        text = last_user if isinstance(last_user, str) else prompt_text([{"content": last_user}])
        found = OUT_MARKER.search(text or "")
        wanted = int(found.group(1)) if found else DEFAULT_OUTPUT_TOKENS
        return min(wanted, max_tokens) if max_tokens else wanted

    @staticmethod
    def workflow(messages: list[dict[str, Any]]) -> str | None:
        found = WORKFLOW_MARKER.search(prompt_text(messages))
        return found.group(1) if found else None

    @staticmethod
    def request_id(messages: list[dict[str, Any]]) -> str | None:
        found = REQUEST_MARKER.search(prompt_text(messages))
        return found.group(1) if found else None

    def admit(self, body: dict[str, Any]) -> dict[str, Any]:
        """Decide a request's fate before any latency: the record, with `status` 200 for an admitted one."""
        s = self.settings
        messages = body.get("messages") or []
        max_tokens = body.get("max_tokens") or body.get("max_completion_tokens")
        input_tokens = count_tokens(prompt_text(messages))
        estimate = input_tokens + (int(max_tokens) if max_tokens else s.default_max_tokens)
        record: dict[str, Any] = {"t": time.time(), "workflow": self.workflow(messages),
                                  "request": self.request_id(messages), "model": body.get("model"),
                                  "mode": s.mode, "input_tokens": input_tokens, "max_tokens": max_tokens,
                                  "estimate": estimate, "status": None, "retry_after": None, "charged": None,
                                  "tools": bool(body.get("tools"))}
        with self.lock:
            if s.mode == "5xx":
                record["status"] = 503
            elif s.mode == "timeout":
                record["status"] = 504
            elif self.throttle_next > 0:
                self.throttle_next -= 1
                record["status"], record["retry_after"] = 429, self.throttle_retry_after_s
                record["throttled"] = True
            else:
                key, wait = self.quota.reserve(estimate)
                if key is None:
                    record["status"], record["retry_after"] = 429, wait
                    record["remaining"] = max(0, int(self.quota.remaining()))
                else:
                    record["status"], record["key"] = 200, key
            self.log.append(record)
        return record

    def settle(self, record: dict[str, Any], output_tokens: int) -> None:
        charged = record["input_tokens"] + output_tokens * self.settings.burndown
        with self.lock:
            self.quota.settle(record.pop("key", None), charged)
        record["charged"], record["output_tokens"] = charged, output_tokens


# --- the HTTP layer -------------------------------------------------------------------------------------

def _rule_reply(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Chapter 5's rule model, as chapter 5's fake backend answers a request with tools."""
    if str(CH05_GATEWAY) not in sys.path:
        sys.path.insert(0, str(CH05_GATEWAY))
    from fake_backend import rule_reply  # chapter 5's function, unchanged

    return rule_reply(messages)


def build_app(provider: Provider):
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    s = provider.settings

    async def chat_completions(request: Request) -> JSONResponse:
        # The provider's own time, from the request reaching the handler to the answer leaving it, on the
        # performance counter: time.time() on Windows under Python 3.12 is GetSystemTimeAsFileTime, which moves
        # in steps of about a millisecond at best, too coarse to take a gateway's few milliseconds from.
        started = time.perf_counter()
        body = await request.json()
        record = provider.admit(body)
        status = record["status"]
        if status == 503:
            record["t_end"] = time.time()
            return JSONResponse({"error": {"message": f"{s.name} is failing on purpose", "type": "server_error"}},
                                status_code=503)
        if status == 504:
            await asyncio.sleep(s.hang_s)
            record["t_end"] = time.time()
            return JSONResponse({"error": {"message": f"{s.name} timed out on purpose", "type": "timeout"}},
                                status_code=504)
        if status == 429:
            record["t_end"] = time.time()
            wait = record["retry_after"]
            limit = s.tpm if s.tpm is not None else 0
            headers = {"retry-after": retry_after_header(wait), "retry-after-ms": str(int(math.ceil(wait * 1000))),
                       "x-ratelimit-limit-tokens": str(limit),
                       "x-ratelimit-remaining-tokens": str(record.get("remaining", 0))}
            words = (f"Too many requests; {s.name} is throttling on purpose." if record.get("throttled") else
                     f"Too many tokens; {s.name} is over its quota of {limit} a minute.")
            return JSONResponse({"error": {"message": f"{words} Try again in {headers['retry-after']} s.",
                                           "type": "rate_limit_exceeded", "code": "429"}},
                                status_code=429, headers=headers)
        messages = body.get("messages") or []
        max_tokens = body.get("max_tokens") or body.get("max_completion_tokens")
        if body.get("tools"):
            message = _rule_reply(messages)
            output_tokens = count_tokens(message.get("content") or json.dumps(message.get("tool_calls")))
        else:
            output_tokens = provider.output_tokens(messages, max_tokens)
            message = {"role": "assistant", "content": f"[{s.name}] " + "x" * max(0, output_tokens * CHARS_PER_TOKEN
                                                                                    - len(s.name) - 3)}
        await asyncio.sleep((s.base_ms + s.per_output_token_ms * output_tokens) / 1000.0)
        provider.settle(record, output_tokens)
        record["t_end"] = time.time()
        record["handled_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model", f"fake-{s.name}"),
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": record["input_tokens"], "completion_tokens": output_tokens,
                      "total_tokens": record["input_tokens"] + output_tokens},
        }, headers={"x-fake-handled-ms": str(record["handled_ms"])})

    async def control(request: Request) -> JSONResponse:
        try:
            return JSONResponse(provider.control(await request.json()))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    async def log(request: Request) -> JSONResponse:
        since = int(request.query_params.get("since", 0))
        return JSONResponse({"records": provider.log[since:], "next": len(provider.log)})

    async def health(request: Request) -> JSONResponse:
        return JSONResponse(provider.state())

    return Starlette(routes=[
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        Route("/control", control, methods=["POST"]),
        Route("/log", log, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--tpm", type=int, default=None, help="the quota in tokens a minute; none by default")
    parser.add_argument("--default-max-tokens", type=int, default=4096)
    parser.add_argument("--burndown", type=float, default=1.0)
    parser.add_argument("--base-ms", type=float, default=50.0)
    parser.add_argument("--per-output-token-ms", type=float, default=0.0)
    parser.add_argument("--hang-s", type=float, default=30.0)
    parser.add_argument("--mode", choices=MODES, default="ok")
    args = parser.parse_args(argv)
    import uvicorn

    provider = Provider(Settings(args.name, args.tpm, args.default_max_tokens, args.burndown, args.base_ms,
                                 args.per_output_token_ms, args.hang_s, args.mode))
    uvicorn.run(build_app(provider), host=HOST, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
