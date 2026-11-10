"""A complete agent loop with a faked model, so it runs anywhere.

This is listing 1.1 from chapter 1. The model is replaced by `fake_model`, which asks
for exactly one tool call and then answers, so you can watch every part of the loop
without an API key. Replace `fake_model` with a real model call and `TOOLS` with real
functions and you have an agent. The allowlist check is the part most pilots skip.

Run:  python agent_loop.py
"""

from __future__ import annotations

import json
from collections.abc import Callable


def get_pod_status(service: str) -> dict:
    return {"service": service, "ready": 2, "desired": 3}


TOOLS = {"get_pod_status": get_pod_status}
ALLOWED = {"get_pod_status": {"service"}}  # the harness decides what it will run, not the model


def fake_model(messages: list[dict]) -> dict:
    """Fake model: asks for one tool call, then answers."""
    if not any(m["role"] == "tool" for m in messages):
        args = {"service": "claims-api"}
        return {"tool_call": {"name": "get_pod_status", "args": args}}
    last = json.loads(messages[-1]["content"])
    s, r, d = last["service"], last["ready"], last["desired"]
    return {"answer": f"{s} has {r} of {d} pods ready."}


def run_agent(question: str, max_steps: int = 5,
              model: Callable[[list[dict]], dict] = fake_model,
              tools: dict[str, Callable[..., dict]] = TOOLS,
              allowed: dict[str, set[str]] = ALLOWED) -> str:
    messages: list[dict] = [{"role": "user", "content": question}]
    for _ in range(max_steps):  # the step budget: a stop condition the model cannot override
        reply = model(messages)  # the model only ever returns text (parsed here into a dict)
        if "answer" in reply:  # second stop condition: the model says it is done
            return reply["answer"]
        call = reply["tool_call"]
        expected = allowed.get(call["name"])
        if expected is None or set(call["args"]) != expected:  # the decision box
            return f"Refused: {call['name']} is not an allowed call."
        result = tools[call["name"]](**call["args"])  # the harness runs the tool, under its own identity
        messages.append(
            {"role": "assistant", "content": json.dumps(call)})
        messages.append(
            {"role": "tool", "content": json.dumps(result)})  # the result becomes context
    return "Stopped: step budget exhausted."


if __name__ == "__main__":
    print(run_agent("Is claims-api healthy?"))
