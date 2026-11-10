"""A callback that alerts, through step 4's webhook, when the limiter's store can't be reached.

Chapter 16, step 5b (companion #14, O-D8). With a shared store, LiteLLM 1.106.6 keeps each key's window and counters
there and a mirror in the proxy's memory. When the store can't be reached, its limiter carries on from that mirror,
each worker on its own, or, with `fail_closed_rate_limit_enforcement`, refuses every call it can't check, with 503
(`proxy/hooks/parallel_request_limiter_v3.py`); its Redis client stops calling the store for a minute after five
failures in a row (`RedisCircuitBreaker`, `caching/redis_cache.py`). LiteLLM writes a warning to its log and sends
nothing: its webhook carries budget alerts only (fact sheet 8.1). Chapter 5 pages the platform's on-call "when the
gateway itself fails" (ch05:498), so this callback watches the store from inside the gateway and tells step 4's
receiver, which forwards the alert to the platform's on-call.

From the proxy's first call on, it opens a connection to the store every `CAPACITY_STORE_WATCH_S` seconds (two by
default), sends AUTH and PING, and waits a second for the answer. After `CAPACITY_STORE_MISSES` failures in a row
(two) it POSTs `limiter_store_unreachable` to WEBHOOK_URL, once; at the first answer after that it POSTs
`limiter_store_reachable`, once. Each ping is a line in `CAPACITY_STORE_WATCH_FILE` when that names a file, for the
drills. The alert names the store by host and port and never carries its password. The callback changes no request
and never fails one.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

UNREACHABLE, REACHABLE = "limiter_store_unreachable", "limiter_store_reachable"
WATCH_FILE = "CAPACITY_STORE_WATCH_FILE"


def iso(moment: float) -> str:
    return datetime.fromtimestamp(moment, timezone.utc).isoformat(timespec="milliseconds")


async def ping(host: str, port: int, password: str, timeout: float = 1.0) -> str | None:
    """None when the store answers AUTH and PING; otherwise what went wrong, in a few words."""
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        writer.write(f"*2\r\n$4\r\nAUTH\r\n${len(password)}\r\n{password}\r\n*1\r\n$4\r\nPING\r\n".encode())
        await writer.drain()
        first = await asyncio.wait_for(reader.readline(), timeout)
        second = await asyncio.wait_for(reader.readline(), timeout)
        if (first, second) != (b"+OK\r\n", b"+PONG\r\n"):
            return f"unexpected answer {(first + second)[:40]!r}"
        return None
    except (OSError, asyncio.TimeoutError) as exc:
        return type(exc).__name__ + (f": {exc}" if str(exc) else "")
    finally:
        if writer is not None:
            writer.close()


class Watch:
    """The state machine, apart from the network, so the tests can drive it: pings in, alerts out."""

    def __init__(self, misses: int = 2) -> None:
        self.misses = misses
        self.failed = 0
        self.down_since: float | None = None
        self.alerted = False

    def observe(self, error: str | None, at: float) -> tuple[str | None, float | None, int]:
        """The alert to send after this ping, if any, with when the store stopped answering and how many pings
        failed: for a recovery, those of the outage that just ended."""
        if error is None:
            was, since, failed = self.alerted, self.down_since, self.failed
            self.failed, self.down_since, self.alerted = 0, None, False
            return (REACHABLE if was else None), since, failed
        self.failed += 1
        if self.down_since is None:
            self.down_since = at
        if self.failed >= self.misses and not self.alerted:
            self.alerted = True
            return UNREACHABLE, self.down_since, self.failed
        return None, self.down_since, self.failed


class StoreWatch(CustomLogger):
    def __init__(self) -> None:
        super().__init__()
        self.task: asyncio.Task | None = None

    def settings(self) -> dict[str, Any]:
        env = os.environ
        return {"host": env.get("CAPACITY_STORE_HOST", ""), "port": int(env.get("CAPACITY_STORE_PORT") or 0),
                "password": env.get("CAPACITY_STORE_PASSWORD", ""), "webhook": env.get("WEBHOOK_URL", ""),
                "every_s": float(env.get("CAPACITY_STORE_WATCH_S") or 2.0),
                "misses": int(env.get("CAPACITY_STORE_MISSES") or 2), "file": env.get(WATCH_FILE, "")}

    async def async_pre_call_hook(self, user_api_key_dict: Any, cache: Any, data: dict, call_type: Any) -> dict:
        if self.task is None:
            s = self.settings()
            if s["host"] and s["port"]:
                self.task = asyncio.get_running_loop().create_task(self.watch(s))
        return data

    async def watch(self, s: dict[str, Any]) -> None:
        state = Watch(s["misses"])
        while True:
            at = time.time()
            error = await ping(s["host"], s["port"], s["password"])
            alert, since, failed = state.observe(error, at)
            if s["file"]:
                with open(s["file"], "a", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps({"t": at, "ok": error is None, "error": error, "alert": alert}) + "\n")
            if alert and s["webhook"]:
                await self.send(s, self.event(s, alert, error, since, failed, at))
            await asyncio.sleep(max(0.0, s["every_s"] - (time.time() - at)))

    @staticmethod
    def event(s: dict[str, Any], alert: str, error: str | None, down_since: float | None, failed: int,
              at: float) -> dict[str, Any]:
        store = f"{s['host']}:{s['port']}"
        if alert == UNREACHABLE:
            message = (f"The limiter's store at {store} hasn't answered {failed} pings in a row since "
                       f"{iso(down_since or at)}; the gateway's rate limits are running on each worker's memory, or "
                       "refusing calls if they fail closed.")
        else:
            gone = f" after {round(at - down_since, 1)} s" if down_since else ""
            message = f"The limiter's store at {store} answers again{gone}."
        return {"event": alert, "event_group": "platform", "event_message": message, "store": store,
                "since": iso(down_since) if down_since else None, "failed_pings": failed, "error": error,
                "at": iso(at)}

    @staticmethod
    async def send(s: dict[str, Any], body: dict[str, Any]) -> None:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(s["webhook"], json=body)
        except httpx.HTTPError:
            pass  # the receiver down too: the next change of state tries again


hooks = StoreWatch()
