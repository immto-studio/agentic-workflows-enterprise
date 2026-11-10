"""A callback for the limiter-cache drill: what LiteLLM's proxy holds in the cache its rate limiter counts in.

Without Redis, LiteLLM 1.106.6 keeps a key's tokens-per-minute window and counters in the proxy's internal usage
cache, in memory, which holds at most 200 entries (`DEFAULT_MAX_SIZE_IN_MEMORY`, litellm/caching/in_memory_cache.py)
and, when it is full, evicts the entries nearest their expiry. At each call's pre-call hook, at each failure and at
each success, this callback appends one line to the file `CAPACITY_CENSUS_FILE` names: how many entries the cache
holds, how many of each kind, and the rate limiter's entries for every key with their values and the seconds each
has left. It reads LiteLLM's internals, which may move in another version, and changes nothing.

Step 5b put the limiter's windows in a shared store (`litellm.store-census.yaml`), where the in-memory cache keeps
only a mirror. When `CAPACITY_STORE_HOST` names the store, the census also reads the store every half second, on a
timer of its own, so that a store that stops answering never slows a call: a line with the store's size and the
limiter's keys, each with its value and the seconds it has left, or what went wrong.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

CENSUS_FILE = "CAPACITY_CENSUS_FILE"
LIMITER_PREFIX = "{api_key:"
STORE_EVERY_S = 0.5


def kind(key: str) -> str:
    """A cache key with its ids taken out: `{api_key:<hash>}:tokens` is `{api_key}:tokens`, and
    `request_status:<call id>` is `request_status`."""
    if key.startswith("{") and "}" in key:
        inner, rest = key[1:].split("}", 1)
        return "{" + inner.split(":", 1)[0] + "}" + rest
    return key.split(":", 1)[0]


def snapshot(cache: Any, event: str) -> dict[str, Any]:
    """One line of the census from an `InMemoryCache`: its size, its kinds of entry, and the limiter's entries."""
    now = cache._clock()
    kinds: dict[str, int] = {}
    limiter: dict[str, list[Any]] = {}
    for key in list(cache.cache_dict):
        name = str(key)
        kinds[kind(name)] = kinds.get(kind(name), 0) + 1
        if name.startswith(LIMITER_PREFIX):
            expires = cache.ttl_dict.get(key)
            limiter[name] = [cache.cache_dict.get(key), round(expires - now, 3) if expires is not None else None]
    return {"t": time.time(), "event": event, "size": len(cache.cache_dict), "max": cache.max_size_in_memory,
            "kinds": dict(sorted(kinds.items())), "limiter": dict(sorted(limiter.items()))}


def usage_cache() -> Any:
    """The proxy's internal usage cache, the in-memory half its rate limiter counts in without Redis."""
    from litellm.proxy.proxy_server import proxy_logging_obj

    return proxy_logging_obj.internal_usage_cache.dual_cache.in_memory_cache


async def store_snapshot(client: Any, timeout: float = 0.4) -> dict[str, Any]:
    """The store's side: how many keys it holds, and the limiter's keys with their values and seconds left."""
    async def read() -> dict[str, Any]:
        size = await client.dbsize()
        names = sorted([name async for name in client.scan_iter(match=LIMITER_PREFIX + "*", count=200)])
        values = await client.mget(names) if names else []
        lefts = [await client.pttl(name) for name in names]
        return {"store_size": size,
                "store_limiter": {name: [value, round(left / 1000, 3) if left is not None and left >= 0 else None]
                                  for name, value, left in zip(names, values, lefts)}}
    try:
        return await asyncio.wait_for(read(), timeout)
    except Exception as exc:  # noqa: BLE001 - a store that doesn't answer is what the census is for
        return {"store_error": f"{type(exc).__name__}: {exc}"[:160]}


class Census(CustomLogger):
    def __init__(self, path: str | None = None) -> None:
        super().__init__()
        self.path = path
        self.store_task: asyncio.Task | None = None

    def target(self) -> str | None:
        return self.path or os.environ.get(CENSUS_FILE)

    def append(self, line: dict[str, Any]) -> None:
        path = self.target()
        if path:
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(line, default=str) + "\n")

    def write(self, event: str) -> None:
        if not self.target():
            return
        try:
            line = snapshot(usage_cache(), event)
        except Exception as exc:  # noqa: BLE001 - the census must never fail a call
            line = {"t": time.time(), "event": event, "error": repr(exc)}
        self.append(line)

    def start_store_census(self) -> None:
        """Read the store every half second from now on, when the gateway has one and a census file is named."""
        host = os.environ.get("CAPACITY_STORE_HOST")
        if self.store_task is not None or not host or not self.target():
            return
        import redis.asyncio as aioredis

        client = aioredis.Redis(host=host, port=int(os.environ["CAPACITY_STORE_PORT"]),
                                password=os.environ.get("CAPACITY_STORE_PASSWORD"), decode_responses=True,
                                socket_timeout=0.4, socket_connect_timeout=0.4)

        async def loop() -> None:
            while True:
                started = time.time()
                self.append({"t": started, "event": "store", **await store_snapshot(client)})
                await asyncio.sleep(max(0.0, STORE_EVERY_S - (time.time() - started)))

        self.store_task = asyncio.get_running_loop().create_task(loop())

    async def async_pre_call_hook(self, user_api_key_dict: Any, cache: Any, data: dict, call_type: Any) -> dict:
        self.start_store_census()
        self.write("pre_call")
        return data

    async def async_post_call_failure_hook(self, request_data: dict, original_exception: Exception,
                                           user_api_key_dict: Any, traceback_str: str | None = None) -> None:
        self.write("failure")

    async def async_log_success_event(self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any) -> None:
        self.write("success")


hooks = Census()
