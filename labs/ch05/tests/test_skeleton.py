"""The skeleton end to end: harness, MCP server, model gateway, trace and golden set in one run.

Parts 1 and 2 call the model in-process. Here every model call goes through the LiteLLM proxy as
a Chat Completions request with tool calls, to a fake backend that answers with the same rules.
What is proven: the golden set passes through the gateway exactly as it does in-process; the
gateway's `chat` spans sit under the harness's `invoke_agent` span in one trace; the gateway's
cost lines carry the run's trace id; and the model is offered only the tools the harness allows,
as the lock file pins them.
"""

from __future__ import annotations

import io
import json
import time

import pytest

import client as harness
import trace_setup as tracing
from gateway_model import GatewayModel, pinned_tool_specs
from gateway_support import MASTER_KEY, lines, wait_for_line
from run_golden import BOTH_TOOLS, inproc_server, run_golden

pytestmark = pytest.mark.anyio


def model_for(gateway: dict, allowed: set[str]) -> GatewayModel:
    return GatewayModel(gateway["url"], "larkspur-chat", tools=pinned_tool_specs(harness.LOCK_PATH, allowed),
                        api_key=MASTER_KEY, timeout_s=30)


async def test_golden_set_passes_through_the_gateway(gateway) -> None:
    model = model_for(gateway, set(BOTH_TOOLS))
    report = await run_golden(inproc_server, model=model)
    assert report.pass_rate == 1.0, "\n".join(report.lines())
    assert len(model.calls) >= len(report.results)  # at least one model call per case
    assert all(call.cost_usd and call.cost_usd > 0 for call in model.calls)


def spans_when(trace_file, trace_id: str, ready, seconds: float = 5.0) -> list[dict]:
    """The trace's spans once `ready(spans)` holds; the gateway exports after it has responded."""
    deadline = time.time() + seconds
    while True:
        spans = [s for s in tracing.read_spans(trace_file) if s["trace_id"] == trace_id]
        if ready(spans) or time.time() > deadline:
            return spans
        time.sleep(0.2)


async def test_one_run_is_one_trace_across_harness_gateway_and_server(gateway, trace_file) -> None:
    trace_id = tracing.new_trace_id()
    model = model_for(gateway, set(harness.ALLOWED))
    answer = await harness.run_harness(inproc_server(), "Is claims-api healthy?", model=model,
                                       trace_id=trace_id, log=io.StringIO())
    assert answer == ("claims-api has 2 of 3 pods ready. "
                      "Not ready: claims-api-7d9f8b6c4-t8w2c (CrashLoopBackOff, 7 restarts).")
    assert len(model.calls) == 2  # propose the tool call, then answer from its result

    def chats(spans: list[dict]) -> list[dict]:
        return [s for s in spans if s["name"] == "chat larkspur-chat"]

    spans = spans_when(trace_file, trace_id, lambda found: len(chats(found)) == 2)
    run = [s for s in spans if s["name"] == "invoke_agent harness"][0]
    tool = [s for s in spans if s["name"] == "execute_tool get_pod_status"
            and s["attributes"].get(tracing.LARKSPUR_COMPONENT) == "harness"][0]
    assert run["parent_span_id"] is None  # a real root
    assert len(chats(spans)) == 2
    assert all(c["parent_span_id"] == run["span_id"] for c in chats(spans))  # via the traceparent
    assert all(c["resource"]["service.name"] == "gateway" for c in chats(spans))
    assert tool["parent_span_id"] == run["span_id"]
    # And the gateway's cost lines carry the same id, so the log and the trace join.
    wait_for_line(gateway["log"], lambda e: e["event"] == "call" and e["trace_id"] == trace_id)
    assert len([e for e in lines(gateway["log"]) if e["event"] == "call" and e["trace_id"] == trace_id]) == 2


async def test_the_model_is_offered_only_the_allowed_tools_as_pinned() -> None:
    specs = pinned_tool_specs(harness.LOCK_PATH, set(harness.ALLOWED))
    assert [s["function"]["name"] for s in specs] == ["get_pod_status"]
    pinned = json.loads(harness.LOCK_PATH.read_text(encoding="utf-8"))["tools"]["get_pod_status"]["definition"]
    assert specs[0]["function"]["description"] == pinned["description"]
    assert specs[0]["function"]["parameters"] == pinned["inputSchema"]
