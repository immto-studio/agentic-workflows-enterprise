"""The class of each call (W3-D10): a call carrying log lines is Restricted and goes to the self-hosted alias,
every other W3 call is Confidential and goes to larkspur-chat; the gateway's grid refuses a Restricted call on
the Confidential alias; a Restricted prompt's logs are trimmed to the self-hosted window; a self-hosted route
that is down ends the run as "model unavailable"."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import loop
import pytest
from loop import (CHAT_ALIAS, FLOOR_CLASS, LOG_TRIM_LINES, MODEL_UNAVAILABLE, RESTRICTED, RESTRICTED_ALIAS,
                  W3GatewayModel, alias_for, prompt_class, result_class, run_steps, trim_logs)
from machine import State

from conftest import ALLOWED, WRITES, ENGINEER, Reads, ScriptedModel, harness_over

CH05_GW = Path(__file__).resolve().parents[3] / "labs" / "ch05" / "gateway"
if str(CH05_GW) not in sys.path:
    sys.path.insert(0, str(CH05_GW))

SERVICE = "claims-api"


def pod_result(call_id="c1"):
    return loop.tool_result(call_id, {"service": SERVICE, "ready": 2, "desired": 3})


def log_result(call_id="c2", n=3):
    lines = [{"age_minutes": i, "pod": f"{SERVICE}-x", "level": "ERROR", "line": f"boom {i}"} for i in range(n)]
    return loop.tool_result(call_id, {"service": SERVICE, "source": "/larkspur/prod/claims-api",
                                      "window_minutes": 30, "returned": n, "truncated": False, "lines": lines})


def test_a_result_with_no_log_lines_is_confidential():
    assert result_class(pod_result()["content"]) == FLOOR_CLASS
    changes = json.dumps({"service": SERVICE, "changes": [{"number": "CHG1", "description": "a ticket"}]})
    assert result_class(changes) == FLOOR_CLASS
    assert result_class("not json") == FLOOR_CLASS


def test_a_result_carrying_log_lines_is_restricted():
    assert result_class(log_result()["content"]) == RESTRICTED
    # An empty log result carries no line, so it is not Restricted on its own.
    empty = json.dumps({"service": SERVICE, "lines": []})
    assert result_class(empty) == FLOOR_CLASS


def test_the_prompt_class_is_the_highest_in_it():
    base = [{"role": "user", "content": "q"}]
    assert prompt_class(base) == FLOOR_CLASS, "a question with no reads is Confidential (the floor)"
    assert prompt_class(base + [pod_result()]) == FLOOR_CLASS
    assert prompt_class(base + [pod_result(), log_result()]) == RESTRICTED, "one log result lifts the whole call"


def test_the_alias_follows_the_class():
    assert alias_for(FLOOR_CLASS) == CHAT_ALIAS
    assert alias_for(RESTRICTED) == RESTRICTED_ALIAS


def test_a_restricted_prompt_is_trimmed_to_the_window():
    messages = [{"role": "user", "content": "q"}, log_result("c2", n=LOG_TRIM_LINES + 25)]
    trimmed = trim_logs(messages)
    result = json.loads(trimmed[1]["content"])
    assert len(result["lines"]) == LOG_TRIM_LINES and result["truncated"] is True
    assert result["lines"][-1]["line"] == f"boom {LOG_TRIM_LINES + 24}", "the newest lines are kept"
    # A short log result and a non-log result are untouched.
    assert trim_logs([pod_result(), log_result("c2", n=3)]) == [pod_result(), log_result("c2", n=3)]


def _gateway_model(handler, floor=FLOOR_CLASS):
    return W3GatewayModel(gateway_url="http://gateway.test", alias=CHAT_ALIAS, floor=floor,
                          tools=[{"type": "function", "function": {"name": "get_pod_status", "parameters": {}}}],
                          api_key="sk-test", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_gateway_model_labels_and_routes_each_call_by_class():
    seen: list[dict] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok",
                                                                  "reasoning_content": "done"}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    model = _gateway_model(gateway)
    model([{"role": "user", "content": "q"}, pod_result()])  # Confidential
    model([{"role": "user", "content": "q"}, pod_result(), log_result()])  # Restricted
    assert seen[0]["model"] == CHAT_ALIAS and "data_class:confidential" in seen[0]["metadata"]["tags"]
    assert seen[1]["model"] == RESTRICTED_ALIAS and "data_class:restricted" in seen[1]["metadata"]["tags"]
    assert model.labels == [("confidential", CHAT_ALIAS), ("restricted", RESTRICTED_ALIAS)]


def test_the_gateways_grid_refuses_a_restricted_call_on_the_confidential_alias():
    """chapter 2's grid, by row (ch05 gateway_rules.may_receive): the managed model in Canada takes a
    Confidential call, a Restricted call goes only to the self-hosted model, so W3's class picks the alias."""
    import gateway_rules
    managed = gateway_rules.Destination("larkspur-chat", "nova-lite", "ca-central-1", "CA", "managed")
    self_hosted = gateway_rules.Destination("larkspur-chat-restricted", "gpt-oss", "ca-central-1", "CA", "self-hosted")
    assert gateway_rules.may_receive("confidential", managed) is True
    assert gateway_rules.may_receive("restricted", managed) is False, "Restricted may not go to the managed alias"
    assert gateway_rules.may_receive("restricted", self_hosted) is True
    # W3's own routing agrees: the class picks the alias the grid would accept.
    assert alias_for("confidential") == managed.alias and alias_for("restricted") == self_hosted.alias


def test_an_unavailable_self_hosted_route_ends_the_run_as_model_unavailable():
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "no healthy upstream"})

    model = _gateway_model(down)
    verdict = model([{"role": "user", "content": "q"}, log_result()])
    assert verdict == {"model_unavailable": True, "reasoning": None}

    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "data class 'restricted' may not go to 'larkspur-chat'"})

    with pytest.raises(httpx.HTTPStatusError):
        _gateway_model(refused)([{"role": "user", "content": "q"}])  # a 4xx is a bug, not an outage


def test_the_loop_ends_a_run_when_the_model_is_unavailable():
    unavailable = ScriptedModel([])
    unavailable.replies = [{"model_unavailable": True, "reasoning": None}]
    outcome = run_steps("q", unavailable, Reads().tools(), ALLOWED, set(WRITES))
    assert outcome.kind == "unavailable" and outcome.text == MODEL_UNAVAILABLE and outcome.reason == "model unavailable"


def test_the_harness_refuses_a_run_whose_model_is_unavailable(store_path, parts):
    model = ScriptedModel([])
    model.replies = [{"model_unavailable": True, "reasoning": None}]
    harness = harness_over(store_path, model, parts)
    run = harness.start(f"{SERVICE} is paging", ENGINEER, trace_id="t-unavail")
    assert run.state is State.REFUSED
    payload = harness.machine.payload("t-unavail", State.REFUSED)
    assert payload["reason"] == "model unavailable" and payload["text"] == MODEL_UNAVAILABLE
    assert parts["writer"].calls == [] and parts["approvals"].requests == {}
