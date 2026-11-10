"""The adapter between the chapter 1 loop and a Chat Completions endpoint, without a gateway.

The endpoint here is an httpx mock. test_skeleton.py runs the same adapter through the real proxy.
"""

from __future__ import annotations

import json

import httpx

import trace_setup as tracing
from gateway_model import (
    GatewayModel, from_chat_messages, parse_reply, pinned_tool_specs, to_chat_messages, tool_specs,
)

TOOLS = [{"name": "get_pod_status", "description": "Pods. Read-only.",
          "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}},
                          "required": ["service"]}},
         {"name": "get_recent_alerts", "description": "Alerts. Read-only.",
          "inputSchema": {"type": "object"}}]
LOOP = [{"role": "user", "content": "Is claims-api healthy?"},
        {"role": "assistant", "content": json.dumps({"name": "get_pod_status", "args": {"service": "claims-api"}})},
        {"role": "tool", "content": json.dumps({"service": "claims-api", "ready": 2, "desired": 3})}]


def test_tool_specs_are_function_tools_and_respect_the_allowlist() -> None:
    specs = tool_specs(TOOLS, allowed={"get_pod_status"})
    assert specs == [{"type": "function", "function": {
        "name": "get_pod_status", "description": "Pods. Read-only.", "parameters": TOOLS[0]["inputSchema"]}}]
    assert len(tool_specs(TOOLS)) == 2


def test_loop_messages_become_chat_messages_with_matching_call_ids() -> None:
    chat = to_chat_messages(LOOP, system="sys")
    assert [m["role"] for m in chat] == ["system", "user", "assistant", "tool"]
    call = chat[2]["tool_calls"][0]
    assert call["function"] == {"name": "get_pod_status", "arguments": json.dumps({"service": "claims-api"})}
    assert chat[3]["tool_call_id"] == call["id"]


def test_chat_messages_convert_back_to_loop_messages() -> None:
    assert from_chat_messages(to_chat_messages(LOOP)) == LOOP


def test_reply_with_a_tool_call_becomes_the_loops_tool_call() -> None:
    body = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "x", "type": "function",
            "function": {"name": "get_pod_status", "arguments": "{\"service\": \"claims-api\"}"}}]}}]}
    assert parse_reply(body) == {"tool_call": {"name": "get_pod_status", "args": {"service": "claims-api"}}}


def test_reply_with_text_becomes_the_loops_answer() -> None:
    body = {"choices": [{"message": {"content": "  claims-api has 2 of 3 pods ready.  "}}]}
    assert parse_reply(body) == {"answer": "claims-api has 2 of 3 pods ready."}


def mock_client(seen: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, headers={"x-litellm-response-cost": "0.0"}, json={
            "choices": [{"message": {"content": "done"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_gateway_model_sends_alias_metadata_and_tools() -> None:
    seen: dict = {}
    model = GatewayModel(gateway_url="http://gw", alias="larkspur-chat-restricted", tools=tool_specs(TOOLS),
                         trace_id="0af7651916cd43dd8448eb211c80319c", api_key="sk-test",
                         client=mock_client(seen))
    assert model([{"role": "user", "content": "hi"}]) == {"answer": "done"}
    assert seen["url"] == "http://gw/chat/completions"
    assert seen["body"]["model"] == "larkspur-chat-restricted"
    assert seen["body"]["metadata"] == {"tags": ["workflow:w2-ops-assistant", "data_class:internal"],
                                        "trace_id": "0af7651916cd43dd8448eb211c80319c"}
    assert seen["body"]["tools"][0]["function"]["name"] == "get_pod_status"
    assert seen["auth"] == "Bearer sk-test"
    assert model.calls[0].completion_tokens == 2 and model.calls[0].cost_usd == 0.0


def test_inside_a_span_the_model_sends_its_trace_id_and_traceparent() -> None:
    seen: dict = {}
    model = GatewayModel(gateway_url="http://gw", alias="larkspur-chat", tools=[], api_key="sk-test",
                         client=mock_client(seen))
    with tracing.start_span("caller", trace_id=tracing.new_trace_id()) as span:
        model([{"role": "user", "content": "hi"}])
        context = span.get_span_context()
    metadata = seen["body"]["metadata"]
    assert metadata["trace_id"] == format(context.trace_id, "032x")
    # version, trace id, parent span id, flags (sampled; newer SDKs also set the W3C "random" bit)
    assert metadata["traceparent"].startswith(f"00-{context.trace_id:032x}-{context.span_id:016x}-")


def test_pinned_tool_specs_come_from_the_lock_file() -> None:
    import client as harness

    specs = pinned_tool_specs(harness.LOCK_PATH, {"get_pod_status", "get_recent_alerts"})
    assert [s["function"]["name"] for s in specs] == ["get_pod_status", "get_recent_alerts"]
