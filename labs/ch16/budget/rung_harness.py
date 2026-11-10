"""A small harness on chapter 1's loop that reads the rung override before each run.

Chapter 16, step 4 (companion #14, O-D7). The harness asks `rungs.plan` for the run's rung and allowlist
before it calls anything. A file it can't read stops the run there, with no model call and no tool call. At
a lowered rung the write tools are gone from the allowlist and from the tools the model is offered, so a
request for one meets chapter 1's decision box, "Refused: ... is not an allowed call", and the tool never
runs. The loop is `labs/ch01/agent_loop.py`'s `run_agent`, unchanged; the model is scripted and the tools
are fakes that count their calls, so the run needs no gateway and no cluster. W3's real harness holds a
write for a person's approval (chapter 12); here the fake restart simply records that it ran.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CH01 = HERE.parents[1] / "ch01"
for folder in (HERE, CH01):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import rungs  # noqa: E402
from agent_loop import run_agent  # noqa: E402  (listing 1.1, unchanged)


@dataclass
class ScriptedModel:
    """Replies in order; records each call and the tools the harness offered with it."""

    script: list[dict[str, Any]]
    offered: list[str]
    calls: int = 0
    __name__: str = "scripted_model"

    def __call__(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        reply = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return reply


@dataclass
class FakeTools:
    """One fake per tool in the manifest; each records its calls."""

    names: list[str]
    calls: Counter = field(default_factory=Counter)

    def table(self) -> dict[str, Callable[..., dict]]:
        def make(name: str) -> Callable[..., dict]:
            def tool(**args: Any) -> dict:
                self.calls[name] += 1
                return {"tool": name, "args": args, "ok": True}
            return tool
        return {name: make(name) for name in self.names}


def run(question: str, manifest: Mapping[str, Any], overrides: Path, script: list[dict[str, Any]]) -> dict:
    """One run: the plan first, then chapter 1's loop with the plan's allowlist."""
    try:
        plan = rungs.plan(manifest, overrides)
    except rungs.RungOverrideError as exc:
        return {"started": False, "why": str(exc), "model_calls": 0, "tool_calls": {}}
    tools = FakeTools(list(manifest["tools"]))
    model = ScriptedModel(script, offered=sorted(plan.allowed))
    answer = run_agent(question, model=model, tools=tools.table(), allowed=plan.allowed)
    return {"started": True, "manifest_rung": plan.manifest_rung, "rung": plan.rung, "note": plan.note,
            "dropped": list(plan.dropped), "offered": model.offered, "model_calls": model.calls,
            "tool_calls": dict(tools.calls), "answer": answer}


RESTART = [{"tool_call": {"name": "restart_deployment", "args": {"service": "claims-api"}}},
           {"answer": "Restarted claims-api."}]
READ = [{"tool_call": {"name": "get_pod_status", "args": {"service": "claims-api"}}},
        {"answer": "claims-api has 2 of 3 pods ready."}]
