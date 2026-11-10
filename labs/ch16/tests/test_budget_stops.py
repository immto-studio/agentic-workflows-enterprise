"""The harness's side of a refusal: a 422 is a budget stop, counted and never retried.

The messages are the ones LiteLLM 1.106.6 and chapter 5's callback send (budget/drills.py records them from the
real proxy); the run goes through chapter 5's `GatewayModel` against an httpx mock transport, so no process and
no socket is involved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import stops

LAB = Path(__file__).resolve().parents[1]
for folder in (LAB.parent / "ch01", LAB.parent / "ch05" / "harness"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from agent_loop import run_agent  # noqa: E402
from gateway_model import GatewayModel  # noqa: E402

LITELLM_422 = {"error": {"message": "Budget has been exceeded! Key=w2-ops-assistant Current cost: 200.0003, "
                                    "Max budget: 200.0", "type": "budget_exceeded", "param": None, "code": "422"}}
LITELLM_401 = {"error": {"message": "Authentication Error, Key is blocked. Update via `/key/unblock` if you're an "
                                    "admin.", "type": "auth_error", "param": "None", "code": "401"}}


@pytest.mark.parametrize("status, message, error_type, kind", [
    (422, LITELLM_422["error"]["message"], "budget_exceeded", "monthly_budget"),
    (422, "Budget has been exceeded! Current cost: 3, Max budget: 2", None, "monthly_budget"),
    (422, '[{"loc": ["body", "model"], "msg": "field required", "type": "missing"}]', None, "error"),
    (429, "request refused: run 0af7651916cd43dd8448eb211c80319c has spent $0.5100 of its $0.50 budget", None,
     "run_budget"),
    (429, "request refused: 'w2-ops-assistant' is over 120 requests per minute", None, "rate_limited"),
    (401, LITELLM_401["error"]["message"], "auth_error", "kill_switch"),
    (401, "Authentication Error, Invalid proxy server token passed.", "auth_error", "error"),
    (403, "request refused: the kill switch of 'w2-ops-assistant' is pulled", None, "kill_switch"),
    (400, "request refused: missing workflow, data_class, trace_id in metadata", None, "refused"),
    (400, "request refused: the key is 'w2-ops-assistant''s, and the request says it is 'w3-incident'", None,
     "refused"),
    (500, "Internal Server Error", None, "error"),
])
def test_each_refusal_is_the_stop_it_says(status, message, error_type, kind):
    assert stops.classify(status, message, error_type) == kind


def test_the_message_is_read_from_litellms_and_fastapis_shapes():
    assert stops.message_of(httpx.Response(422, json=LITELLM_422)) == (LITELLM_422["error"]["message"],
                                                                       "budget_exceeded")
    assert stops.message_of(httpx.Response(400, json={"detail": "request refused: x"})) == ("request refused: x", None)
    assert stops.message_of(httpx.Response(500, text="boom")) == ("boom", None)


def gateway(status: int, body: dict, seen: list) -> GatewayModel:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return GatewayModel(gateway_url="http://gateway.test", alias="larkspur-chat", tools=[], trace_id="0" * 32,
                        api_key="sk-test", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_a_422_ends_the_run_as_a_budget_stop_after_one_call():
    seen: list = []
    outcome = stops.run(run_agent, "Is claims-api healthy?", gateway(422, LITELLM_422, seen))
    assert (outcome.answer, outcome.stop, outcome.status) == (None, "monthly_budget", 422)
    assert len(seen) == 1  # counted, not retried


def test_a_blocked_key_ends_the_run_as_the_kill_switch():
    outcome = stops.run(run_agent, "Is claims-api healthy?", gateway(401, LITELLM_401, []))
    assert outcome.stop == "kill_switch" and not stops.GatewayStop("kill_switch", 401, "").retryable


def test_only_a_rate_limit_is_worth_a_retry():
    assert stops.GatewayStop("rate_limited", 429, "").retryable
    assert not any(stops.GatewayStop(kind, 0, "").retryable
                   for kind in ("monthly_budget", "run_budget", "kill_switch", "refused", "error"))


def test_an_answer_passes_through_and_the_tally_counts_both():
    tally = stops.Tally()
    tally.add(stops.Outcome(answer="claims-api has 2 of 3 pods ready."))
    tally.add(stops.Outcome(answer=None, stop="monthly_budget", status=422))
    tally.add(stops.Outcome(answer=None, stop="monthly_budget", status=422))
    assert tally.as_dict() == {"answered": 1, "monthly_budget": 2}
