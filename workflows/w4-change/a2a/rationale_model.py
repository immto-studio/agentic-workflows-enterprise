"""The rationale seam: a model writes the prose, the rubric sets the class.

Chapter 13, W4-D9. `rubric.score` decides the class from the evidence's fields; the risk scorer asks a
model only to put the class and its reasons into a sentence for the change advisory board. When no model
is configured (`W4_MODEL_BASE_URL` unset) the deterministic stub (`rubric.rationale`) is used, so the lab
and its tests run without a model; when it is set, the scorer calls the gateway's OpenAI-compatible
endpoint (the larkspur-chat alias) and falls back to the stub on any error, so a model outage never
blocks a pack. The model never sets the class: it is given the class and told not to change it.

Chapter 16's lab (companion #14, step 3b) found a change's spans in two trees: the request carried the trace
id and no `traceparent`, so chapter 5's gateway made the call's `chat` span a root of its own beside the
scribe's. The risk scorer now hands over its span's `traceparent`, which goes in the metadata beside the
trace id, and the gateway's span lands under the risk scorer's, as W5's prose seam does since step 3b.

Chapter 16's step 5b (companion #14): a 429 whose answer says how long to wait is waited out before the stub stands
in (`post_waiting`): the same request again after that wait and up to a second of jitter, six attempts at most and
never past a minute after the first. A 429 that names no wait, and every other failure, go to the stub as before.
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Mapping
from typing import Any

import rubric

SYSTEM = ("You write one sentence of rationale for a change advisory board. You are given a risk CLASS "
          "that has already been decided and the REASONS behind it. Restate the class and the reasons "
          "plainly in one sentence. Do not change the class, and do not add a class of your own. Do not "
          "say the change is approved, authorized, pre-approved, or safe to merge; the board decides that.")


WORKFLOW = os.environ.get("W4_WORKFLOW", "w4-change")
DATA_CLASS = "internal"  # the rationale call's class: a change's evidence is Internal by default (W4-D14)


# A reasoning model spends tokens thinking before the sentence: with 200 the first gpt-oss-20b run came
# back empty on five of eight calls and the seam fell back to the stub without saying so.
MAX_TOKENS = int(os.environ.get("W4_MODEL_MAX_TOKENS", "1200"))

# Where a 429 says how long to wait: the gateway's own headers, then a provider's as LiteLLM's proxy passes them on.
RETRY_AFTER_HEADERS = (("retry-after-ms", 0.001), ("retry-after", 1.0),
                       ("llm_provider-retry-after-ms", 0.001), ("llm_provider-retry-after", 1.0))
WAIT_ATTEMPTS = 6  # Bedrock's "six total attempts" (chapter 16's fact sheet, section 4)
WAIT_CAP_S = 60.0  # never past a minute after the first attempt, the longest wait LiteLLM's router honours
WAIT_JITTER_S = 1.0
pause = time.sleep  # the waits, through one name, so that a test can record them instead


def retry_after_s(headers: Mapping[str, str] | None) -> float | None:
    """The wait an answer asks for, in seconds; None when it names none, or not as a number."""
    lower = {str(k).lower(): v for k, v in (headers or {}).items()}
    for name, scale in RETRY_AFTER_HEADERS:
        try:
            seconds = float(lower[name]) * scale
        except (KeyError, ValueError):
            continue
        if seconds >= 0:
            return seconds
    return None


def post_waiting(url: str, **kwargs: Any) -> Any:
    """`httpx.post`, with a 429 that says how long to wait sent again after that wait, within the cap; any other
    answer, and a 429 that names no wait, is returned as it came."""
    import httpx

    started = time.monotonic()
    attempt = 1
    while True:
        response = httpx.post(url, **kwargs)
        asked = retry_after_s(response.headers) if response.status_code == 429 else None
        if asked is None or attempt == WAIT_ATTEMPTS:
            return response
        wait = asked + random.random() * WAIT_JITTER_S
        if time.monotonic() - started + wait > WAIT_CAP_S:
            return response
        pause(wait)
        attempt += 1


def rationale(evidence: dict[str, Any], risk_class: str, reasons: list[str], *,
              trace_id: str | None = None, traceparent: str | None = None) -> str:
    """The rationale prose. A model writes it when one is configured; otherwise the deterministic stub."""
    return rationale_with_source(evidence, risk_class, reasons, trace_id=trace_id, traceparent=traceparent)[0]


def rationale_with_source(evidence: dict[str, Any], risk_class: str,
                          reasons: list[str], *,
                          trace_id: str | None = None,
                          traceparent: str | None = None) -> tuple[str, str]:
    """The rationale and where it came from: "model" when a configured
    model wrote it, "stub" when the deterministic sentence was used (no
    model configured, an empty answer, or an error). The pack records the
    source, so a run can say how many rationales the model actually
    wrote. `traceparent`, the risk scorer's span, goes in the metadata
    beside the trace id: the gateway puts its span under it."""
    base = os.environ.get("W4_MODEL_BASE_URL", "").strip()
    stub = rubric.rationale(evidence, risk_class, reasons)
    if not base:
        return stub, "stub"
    try:
        model = os.environ.get("W4_MODEL_NAME", "larkspur-chat")
        key = os.environ.get("W4_MODEL_API_KEY", "sk-lab")
        joined = "; ".join(reasons) if reasons else "none"
        user = (f"CLASS: {risk_class}\nREASONS: {joined}\n"
                f"CHANGE: {evidence.get('change_ref')} "
                f"on {evidence.get('service')}.")
        # Chapter 5's gateway hooks read the workflow and the class from
        # the tags and the trace id from the metadata, apply the manifest
        # and the data-class grid, and log the call.
        metadata = {"tags": [f"workflow:{WORKFLOW}",
                             f"data_class:{DATA_CLASS}"],
                    "trace_id": trace_id}
        if traceparent:
            metadata["traceparent"] = traceparent
        resp = post_waiting(
            base.rstrip("/") + "/chat/completions", timeout=180.0,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0,
                  "max_tokens": MAX_TOKENS, "metadata": metadata,
                  "messages": [{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": user}]})
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        text = (content or "").strip()
        return (text, "model") if text else (stub, "stub")
    except Exception:  # a model outage never blocks a pack: the stub
        return stub, "stub"
