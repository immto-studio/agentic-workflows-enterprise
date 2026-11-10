"""The loop: every tool call of a turn runs, the reasoning goes back with the results, a write ends the triage as a
proposal, and W2's refusal and outage semantics hold. The gateway model is checked against a mocked gateway."""

from __future__ import annotations

import json

import httpx
import loop
from loop import W3GatewayModel, Outcome, parse_all, run_steps, to_chat

from conftest import ALLOWED, WRITES, Reads, ScriptedModel, answer, call, reply

SERVICE = "claims-api"


def triage(model: ScriptedModel, reads: Reads, **kw) -> Outcome:
    return run_steps(f"{SERVICE} is paging", model, reads.tools(), ALLOWED, set(WRITES), **kw)


def test_every_tool_call_of_a_turn_runs_in_order():
    reads = Reads()
    model = ScriptedModel([
        reply(call("get_pod_status", {"service": SERVICE}, "c1"),
              call("get_recent_events", {"service": SERVICE, "minutes": 60}, "c2"), reasoning="health, then events"),
        answer("one of three pods ready; the container is in a back-off"),
    ])
    outcome = triage(model, reads)
    assert outcome.kind == "answer" and outcome.reads == 2
    assert [name for name, _ in reads.calls] == ["get_pod_status", "get_recent_events"]
    turn, *results = [m for m in outcome.messages if m["role"] != "user"]
    assert json.loads(turn["content"]) == {"calls": [call("get_pod_status", {"service": SERVICE}, "c1"),
                                                     call("get_recent_events", {"service": SERVICE, "minutes": 60}, "c2")],
                                           "reasoning": "health, then events"}
    assert [r["call_id"] for r in results] == ["c1", "c2"]
    assert json.loads(results[1]["content"])["events"][0]["reason"] == "BackOff"


def test_the_reasoning_travels_back_with_the_results():
    reads = Reads()
    model = ScriptedModel([
        reply(call("get_pod_status", {"service": SERVICE}, "c1"), reasoning="check the pods first"),
        answer("done"),
    ])
    triage(model, reads)
    second_request = to_chat(model.seen[1])
    assistant = second_request[2]
    assert assistant["role"] == "assistant" and assistant["content"] is None
    assert assistant["reasoning_content"] == "check the pods first"
    assert assistant["tool_calls"][0]["id"] == "c1" and assistant["tool_calls"][0]["function"]["name"] == "get_pod_status"
    assert second_request[3] == {"role": "tool", "tool_call_id": "c1", "content": model.seen[1][2]["content"]}
    assert second_request[0]["role"] == "system"


def test_a_turn_without_reasoning_sends_none_of_it():
    chat = to_chat([{"role": "user", "content": "q"}, loop.assistant_turn([call("get_pod_status", {"service": SERVICE})], None)])
    assert "reasoning_content" not in chat[2]


def test_a_write_ends_the_triage_as_a_proposal_and_does_not_run():
    reads = Reads()
    model = ScriptedModel([
        reply(call("get_pod_status", {"service": SERVICE}, "c1"), reasoning="look first"),
        reply(call("get_recent_events", {"service": SERVICE, "minutes": 60}, "c2"),
              call("restart_deployment", {"service": SERVICE}, "c3"),
              call("get_pod_status", {"service": SERVICE}, "c4"), reasoning="the runbook says restart"),
    ])
    outcome = triage(model, reads)
    assert outcome.kind == "proposal"
    assert outcome.call == call("restart_deployment", {"service": SERVICE}, "c3")
    assert outcome.reasoning == "the runbook says restart"
    # The read before the write in the same turn ran; the one after it did not.
    assert [name for name, _ in reads.calls] == ["get_pod_status", "get_recent_events"]
    assert outcome.reads == 1, "the proposal turn's results are not appended; the record holds the turn"
    last_turn = json.loads(outcome.messages[-1]["content"])
    assert [c["name"] for c in last_turn["calls"]] == ["get_recent_events", "restart_deployment"]


def test_a_call_outside_the_allowlist_is_refused_before_it_runs():
    reads = Reads()
    model = ScriptedModel([reply(call("delete_namespace", {"namespace": "larkspur-prod"}))])
    outcome = triage(model, reads)
    assert outcome.kind == "refused" and outcome.text == "Refused: delete_namespace is not an allowed call."
    assert reads.calls == []
    model = ScriptedModel([reply(call("get_pod_status", {"service": SERVICE, "namespace": "kube-system"}))])
    assert triage(model, reads).kind == "refused", "an extra argument is not the allowed shape"


def test_a_refused_read_ends_the_run_with_the_fixed_sentence():
    reads = Reads()
    reads.errors["get_pod_status"] = "Error executing tool get_pod_status: fraud-scoring is not among the ones you can ask about."
    model = ScriptedModel([reply(call("get_pod_status", {"service": "fraud-scoring"}))])
    outcome = triage(model, reads)
    assert outcome.kind == "refused" and outcome.text == loop.w2.REFUSAL
    assert len(model.seen) == 1, "no further model call: the model never learns why"


def test_a_failed_read_ends_the_run_with_the_outage_sentence():
    reads = Reads()
    reads.errors["get_recent_events"] = "connection refused"
    model = ScriptedModel([reply(call("get_recent_events", {"service": SERVICE, "minutes": 60}))])
    outcome = triage(model, reads)
    assert outcome.kind == "failed" and outcome.text == loop.w2.READ_FAILED


def test_a_bad_argument_and_a_timeout_go_back_to_the_model():
    reads = Reads()
    reads.errors["get_recent_events"] = "Error executing tool get_recent_events: bad argument: minutes above 1440"
    reads.errors["search_logs"] = loop.w2.TIMED_OUT + "the read returned nothing within 30 seconds"
    model = ScriptedModel([
        reply(call("get_recent_events", {"service": SERVICE, "minutes": 10080}, "c1"),
              call("search_logs", {"service": SERVICE, "needle": "error", "minutes": 10080}, "c2")),
        answer("corrected"),
    ])
    outcome = triage(model, reads)
    assert outcome.kind == "answer" and outcome.reads == 2
    shown = [json.loads(m["content"]) for m in model.seen[1] if m["role"] == "tool"]
    assert "bad argument" in shown[0]["error"] and shown[1]["error"].startswith(loop.w2.TIMED_OUT)


def test_the_step_budget_stops_the_loop_and_withholds_the_tools():
    reads = Reads()
    model = ScriptedModel([
        reply(call("get_pod_status", {"service": SERVICE}, "c1"), call("get_pod_status", {"service": SERVICE}, "c2")),
        reply(call("get_pod_status", {"service": SERVICE}, "c3")),
    ])
    outcome = triage(model, reads, max_reads=2)
    assert outcome.kind == "budget" and outcome.text == loop.BUDGET_EXHAUSTED and outcome.reads == 2
    assert model.offers == [True, False], "after the budget the model is offered no tool and must answer"
    model = ScriptedModel([reply(call("get_pod_status", {"service": SERVICE}, "c1"),
                                 call("get_pod_status", {"service": SERVICE}, "c2"),
                                 call("get_pod_status", {"service": SERVICE}, "c3"))])
    assert triage(model, Reads(), max_reads=2).kind == "budget", "a turn larger than the budget left is refused whole"


def test_parse_all_keeps_every_call_and_the_reasoning():
    body = {"choices": [{"message": {"role": "assistant", "content": None, "reasoning_content": "two reads",
                                     "tool_calls": [
                                         {"id": "call_a", "type": "function",
                                          "function": {"name": "get_pod_status", "arguments": json.dumps({"service": SERVICE})}},
                                         {"type": "function",
                                          "function": {"name": "get_recent_events",
                                                       "arguments": {"service": SERVICE, "minutes": 60}}}]}}]}
    parsed = parse_all(body)
    assert parsed["reasoning"] == "two reads"
    assert [c["name"] for c in parsed["tool_calls"]] == ["get_pod_status", "get_recent_events"]
    assert parsed["tool_calls"][1]["id"] == "call_2" and parsed["tool_calls"][1]["args"]["minutes"] == 60
    text = parse_all({"choices": [{"message": {"role": "assistant", "content": " healthy ", "reasoning": "r"}}]})
    assert text == {"answer": "healthy", "reasoning": "r"}


def test_the_gateway_model_passes_reasoning_back_and_withholds_tools_after_the_budget():
    requests: list[dict] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "reasoning_content": "read twice", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "get_pod_status", "arguments": json.dumps({"service": SERVICE})}},
                {"id": "call_2", "type": "function", "function": {"name": "get_recent_events",
                                                                  "arguments": json.dumps({"service": SERVICE, "minutes": 60})}}]}
        else:
            message = {"role": "assistant", "content": "one of three ready", "reasoning_content": "done"}
        return httpx.Response(200, json={"choices": [{"message": message}], "usage": {"prompt_tokens": 50, "completion_tokens": 5}})

    model = W3GatewayModel(gateway_url="http://gateway.test", alias="larkspur-chat",
                           tools=[{"type": "function", "function": {"name": "get_pod_status", "parameters": {}}}],
                           api_key="sk-test", client=httpx.Client(transport=httpx.MockTransport(gateway)))
    outcome = run_steps("q", model, Reads().tools(), ALLOWED, set(WRITES), max_reads=2)
    assert outcome.kind == "answer" and outcome.text == "one of three ready" and outcome.reasoning == "done"
    first, second = requests
    assert "tools" in first and "tools" not in second, "two reads spent the budget of two: the second call answers"
    assistant = second["messages"][2]
    assert assistant["reasoning_content"] == "read twice" and len(assistant["tool_calls"]) == 2
    assert [m["tool_call_id"] for m in second["messages"] if m["role"] == "tool"] == ["call_1", "call_2"]
    # The reads here carry no log lines, so every call is Confidential and goes to larkspur-chat (W3-D10).
    assert first["metadata"]["tags"] == ["workflow:w3-incident", "data_class:confidential"]
    assert model.labels == [("confidential", "larkspur-chat")] * 2
    assert [c.prompt_tokens for c in model.calls] == [50, 50]
