"""Two ways a harness can retry a throttled call, and the arithmetic of each.

Chapter 16, step 5 (companion #14, O-D8). Fact sheet section 4 gives the clouds' advice: Bedrock says to
"Retry only errors that are safe to retry", honour `Retry-After`, start at one second with jitter and stop at
"six total attempts"; the AWS SDKs back off as `random(0, 1) × min(20,000 ms, base_delay × 2^retry)`; Azure says
"Use the retry-after-ms header value if present; otherwise, use exponential backoff with random jitter" and
"Set a maximum number of retries". The two policies here are that advice and its opposite:

- `honour`: retry a 429 (and a 503 or a 529, which Bedrock calls transient), never anything else. Wait what the
  answer asks, `retry-after-ms` first and then `Retry-After`, plus up to a second of jitter; with neither, back
  off as the SDKs do, with full jitter from a one-second base to a 20-second cap. Six attempts at most, and never
  past the run's deadline: a wait that would end after it ends the request instead.
- `naive`: retry any failure at once, up to twenty attempts, the loop that turned chapter 1's weekend into a bill.

`none` sends once. The policies are plain data; `next_wait` is the whole decision, so the tests drive it
without a network, and `load.py` calls it between attempts.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass

RETRYABLE_STATUS = frozenset({429, 503, 529})


@dataclass(frozen=True)
class Policy:
    name: str
    max_attempts: int
    honours_retry_after: bool
    jitter_s: float = 1.0       # added to a Retry-After, as the AWS guidance's "with jitter"
    base_s: float = 1.0         # the SDKs' throttling base delay
    cap_s: float = 20.0         # the SDKs' cap
    deadline_s: float | None = None  # give up rather than wait past this many seconds after the first attempt
    retry_any_failure: bool = False

    def retryable(self, status: int | None) -> bool:
        if self.max_attempts <= 1:
            return False
        if self.retry_any_failure:
            return status is None or status >= 400
        return status in RETRYABLE_STATUS


NONE = Policy("none", max_attempts=1, honours_retry_after=False)
HONOUR = Policy("honour", max_attempts=6, honours_retry_after=True, deadline_s=60.0)
NAIVE = Policy("naive", max_attempts=20, honours_retry_after=False, jitter_s=0.0, base_s=0.0, cap_s=0.0,
               retry_any_failure=True)
POLICIES = {p.name: p for p in (NONE, HONOUR, NAIVE)}


# Where a wait can be: the answerer's own headers first, then the provider's as LiteLLM's proxy passes them on.
# The proxy writes Retry-After itself only for its router's cooldown, and forwards every header of a provider's
# answer under the prefix `llm_provider-` (litellm_core_utils/llm_response_utils/get_headers.py), so a provider's
# 429 reaches the harness with `llm_provider-retry-after` and no `retry-after` (the drills record it).
WAIT_HEADERS = (("retry-after-ms", 0.001), ("retry-after", 1.0),
                ("llm_provider-retry-after-ms", 0.001), ("llm_provider-retry-after", 1.0))


def retry_after_s(headers: Mapping[str, str] | None, names: tuple[tuple[str, float], ...] = WAIT_HEADERS) -> float | None:
    """The wait an answer asks for, in seconds, from the first of `names` it carries.

    An HTTP date in Retry-After isn't used by any of the clouds' 429s as the fact sheet quotes them, so a value
    that isn't a number counts as absent.
    """
    if not headers:
        return None
    lower = {k.lower(): v for k, v in headers.items()}
    for name, scale in names:
        value = lower.get(name)
        if value is None:
            continue
        try:
            seconds = float(value) * scale
        except ValueError:
            continue
        if seconds >= 0:
            return seconds
    return None


def next_wait(policy: Policy, attempt: int, status: int | None, headers: Mapping[str, str] | None,
              elapsed_s: float, rng: random.Random) -> float | None:
    """Seconds to wait before attempt `attempt + 1`, or None to stop. `attempt` counts from 1."""
    if attempt >= policy.max_attempts or not policy.retryable(status):
        return None
    if not policy.honours_retry_after:
        return 0.0
    asked = retry_after_s(headers)
    if asked is not None:
        wait = asked + rng.uniform(0.0, policy.jitter_s)
    else:
        wait = rng.uniform(0.0, min(policy.cap_s, policy.base_s * 2 ** (attempt - 1)))
    if policy.deadline_s is not None and elapsed_s + wait > policy.deadline_s:
        return None
    return wait
