"""The harness's model, served through the model gateway: `model(messages)` over Chat Completions.

Chapter 5, part 3. The chapter 1 loop (and this harness, which wraps it) calls `model(messages)`
and expects one of two answers: `{"tool_call": {"name": ..., "args": {...}}}` or
`{"answer": "..."}`. Parts 1 and 2 used a rule-based stand-in called in-process. `GatewayModel`
sends the same messages to the gateway as a Chat Completions request instead: by alias, never by
deployment, with the metadata the gateway requires (workflow, data class, trace id) and the
caller's `traceparent`, so the gateway's `chat` span lands under the harness's span. The reply
comes back as one of the two answers. The harness still owns the allowlist; the model proposes.

Behind the alias, the lab's fake backends answer with the same rules as the stand-in, so a run
through the gateway gives the same answers as a run without it. Chapter 9 points an alias at a
local model and uses this class unchanged.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tracing"))
import trace_setup as tracing  # noqa: E402

SYSTEM_PROMPT = (
    "You are the read-only operations assistant of Larkspur Mutual's platform team. "
    "Answer questions about deployments and alerts in the larkspur-prod namespace by calling the "
    "tools you are given; never guess numbers. You cannot change anything: if asked to restart, "
    "scale, delete or change something, say that you can only read and do not call a tool. "
    "When a tool returns an error, report it plainly. Answer in one or two sentences."
)


def tool_specs(tools: list[Any], allowed: set[str] | None = None) -> list[dict[str, Any]]:
    """MCP tool definitions as Chat Completions function tools, only the allowed ones if given.

    Accepts MCP SDK `Tool` objects (from tools/list) or the same thing as plain dicts, such as the
    `definition` entries of tools.lock.json, which are the definitions the harness verified.
    """
    specs = []
    for tool in tools:
        data = tool.model_dump(by_alias=True, exclude_none=True) if hasattr(tool, "model_dump") else tool
        if allowed is not None and data["name"] not in allowed:
            continue
        schema = data.get("inputSchema") or {"type": "object"}
        specs.append({"type": "function", "function": {
            "name": data["name"], "description": data.get("description", ""), "parameters": schema}})
    return specs


def pinned_tool_specs(lock_path: Path, allowed: set[str]) -> list[dict[str, Any]]:
    """The allowed tools as the lock file pins them: what the model is told is what was reviewed."""
    data = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    return tool_specs([entry["definition"] for entry in data["tools"].values()], allowed)


def to_chat_messages(messages: list[dict[str, str]], system: str = SYSTEM_PROMPT) -> list[dict[str, Any]]:
    """The loop's messages (user, assistant = a JSON tool call, tool = a JSON result) in Chat format."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    call_index = 0
    for message in messages:
        role = message["role"]
        if role == "user":
            out.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            call = json.loads(message["content"])
            call_index += 1
            out.append({"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call_{call_index}", "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["args"])}}]})
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": f"call_{call_index}", "content": message["content"]})
        else:
            raise ValueError(f"unexpected role {role!r}")
    return out


def from_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The inverse of `to_chat_messages`, without the system prompt. The fake backends use it."""
    out: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        if role == "user":
            content = message.get("content")
            if not isinstance(content, str):  # content can be a list of parts
                content = " ".join(p.get("text", "") for p in content or [] if isinstance(p, dict))
            out.append({"role": "user", "content": content})
        elif role == "assistant" and message.get("tool_calls"):
            function = message["tool_calls"][0]["function"]
            arguments = function.get("arguments") or "{}"
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
            out.append({"role": "assistant", "content": json.dumps({"name": function["name"], "args": args})})
        elif role == "tool":
            out.append({"role": "tool", "content": message.get("content") or ""})
    return out


def parse_reply(body: dict[str, Any]) -> dict[str, Any]:
    """A Chat Completions response as the loop's answer: the first tool call, or the text."""
    message = body["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if calls:
        function = calls[0]["function"]
        arguments = function.get("arguments") or "{}"
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        return {"tool_call": {"name": function["name"], "args": args}}
    return {"answer": (message.get("content") or "").strip()}


@dataclass
class CallRecord:
    latency_s: float
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None


@dataclass
class GatewayModel:
    """`model(messages)` for the chapter 1 loop, served by the gateway under an alias.

    `trace_id` defaults to the trace of the span the call is made in, which is the harness's
    `invoke_agent` span when the harness runs the loop.
    """

    gateway_url: str
    alias: str
    tools: list[dict[str, Any]]
    trace_id: str | None = None
    workflow: str = "w2-ops-assistant"
    data_class: str = "internal"
    api_key: str = field(default_factory=lambda: os.environ.get("LITELLM_MASTER_KEY", ""))
    timeout_s: float = 300.0
    client: httpx.Client | None = None
    calls: list[CallRecord] = field(default_factory=list)
    __name__: str = "gateway_model"  # the harness records the model's name in its span

    def request(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        metadata: dict[str, Any] = {"tags": [f"workflow:{self.workflow}", f"data_class:{self.data_class}"],
                                    "trace_id": self.trace_id or tracing.current_trace_id()}
        traceparent = tracing.current_traceparent()
        if traceparent:
            metadata["traceparent"] = traceparent
        return {"model": self.alias, "messages": to_chat_messages(messages), "tools": self.tools,
                "temperature": 0, "metadata": metadata}

    def __call__(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        client = self.client or httpx.Client(timeout=self.timeout_s)
        started = time.perf_counter()
        response = client.post(f"{self.gateway_url}/chat/completions", json=self.request(messages),
                               headers={"Authorization": f"Bearer {self.api_key}"})
        elapsed = time.perf_counter() - started
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        cost = response.headers.get("x-litellm-response-cost")
        self.calls.append(CallRecord(elapsed, usage.get("prompt_tokens"), usage.get("completion_tokens"),
                                     float(cost) if cost not in (None, "None") else None))
        return parse_reply(body)
