"""The harness's side of the gateway's refusals: which stop a refusal is, and a run that ends on one.

Chapter 16, step 4 (companion #14, O-D7). Chapter 5's `GatewayModel` raises on any answer that isn't a 200,
so a run the gateway stops ends in an exception, and a harness that retries on errors would retry a budget
stop. LiteLLM answers a spent budget with 422, not 429 (`budget_exceeded_status_code`, fact sheet 8.1), and
this step's callback answers the same, so the harness counts a 422 as a budget stop and never retries it.
The kinds, from the status and the error's message or type:

- `monthly_budget`: 422 that names a budget (LiteLLM's "Budget has been exceeded!", type `budget_exceeded`,
  or this step's callback). A 422 that names no budget is FastAPI's validation error and stays an error.
- `run_budget`: chapter 5's per-run budget, a 429 whose message says the run "has spent".
- `rate_limited`: any other 429, the one kind worth a retry after a wait.
- `kill_switch`: LiteLLM's blocked key (401, "Key is blocked") or this step's switch (403, "kill switch").
- `refused`: chapter 5's pre-call rules (400, "request refused").
- `error`: everything else.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

RETRYABLE = {"rate_limited"}


def message_of(response: httpx.Response) -> tuple[str, str | None]:
    """The error's message and type from a gateway answer, whatever its shape."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:500], None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or ""), (str(error["type"]) if error.get("type") else None)
    detail = body.get("detail") if isinstance(body, dict) else None
    if detail is not None:
        return (detail if isinstance(detail, str) else json.dumps(detail)), None
    return json.dumps(body)[:500], None


def classify(status: int, message: str, error_type: str | None = None) -> str:
    text = message.lower()
    if status == 422 and ("budget" in text or error_type == "budget_exceeded"):
        return "monthly_budget"
    if status == 429:
        return "run_budget" if "has spent" in text else "rate_limited"
    if status == 401 and "blocked" in text:
        return "kill_switch"
    if status == 403 and "kill switch" in text:
        return "kill_switch"
    if status == 400 and "request refused" in text:
        return "refused"
    return "error"


class GatewayStop(Exception):
    """The gateway refused the run's call; `kind` says which stop."""

    def __init__(self, kind: str, status: int, message: str) -> None:
        super().__init__(f"{kind} ({status}): {message}")
        self.kind, self.status, self.message = kind, status, message

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE


@dataclass
class Guarded:
    """A model callable for chapter 1's loop that turns the gateway's refusals into GatewayStop."""

    model: Callable[[list[dict[str, str]]], dict[str, Any]]
    __name__: str = "guarded_gateway_model"

    def __call__(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        try:
            return self.model(messages)
        except httpx.HTTPStatusError as exc:
            message, error_type = message_of(exc.response)
            raise GatewayStop(classify(exc.response.status_code, message, error_type),
                              exc.response.status_code, message) from exc


@dataclass(frozen=True)
class Outcome:
    answer: str | None
    stop: str | None = None      # the kind, when the gateway stopped the run
    status: int | None = None
    message: str | None = None


def run(loop: Callable[..., str], question: str, model: Callable, **kwargs: Any) -> Outcome:
    """One run of the loop with a guarded model; a stop ends the run and is never retried here."""
    try:
        return Outcome(answer=loop(question, model=Guarded(model), **kwargs))
    except GatewayStop as stop:
        return Outcome(answer=None, stop=stop.kind, status=stop.status, message=stop.message)


@dataclass
class Tally:
    """Runs counted by how they ended: answered, or stopped by which kind."""

    counts: Counter = field(default_factory=Counter)

    def add(self, outcome: Outcome) -> None:
        self.counts["answered" if outcome.stop is None else outcome.stop] += 1

    def as_dict(self) -> dict[str, int]:
        return dict(sorted(self.counts.items()))
