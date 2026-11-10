"""The agent loop of chapter 1 with the identity chain of chapter 4 wired in.

Four structural controls, none of which consult the model: the pinned-hash check on the
tool catalog, the allowlist plus argument check, the per-tool identity lookup, and the
approval gate on write identities. Every refusal is logged with the trace id of the run, and
every call that ran is logged with the tool identity, the person who asked and the approver.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable, Sequence

from identity import WORKFLOW, ApprovalToken, Identity
from tools import CATALOG, PINNED, Tool

log = logging.getLogger("ch04.harness")
Model = Callable[[list[dict], dict[str, Tool]], dict]


def run_agent(question: str, model: Model, *,
              catalog: dict[str, Tool] = CATALOG,
              approvals: Sequence[ApprovalToken] = (),
              workflow: Identity = WORKFLOW, max_steps: int = 5,
              requested_by: str = "unknown", trace_id: str | None = None,
              clock: Callable[[], float] = time.time) -> str:
    trace_id = trace_id or uuid.uuid4().hex

    def refuse(tool: str, reason: str) -> str:
        log.warning("refused trace_id=%s tool=%s reason=%s",
                    trace_id, tool, reason)
        return f"Refused: {tool}: {reason}."

    for name, tool in catalog.items():  # control 1: pinned hashes
        if PINNED.get(name) != tool.digest():
            return refuse(name, "definition hash does not match "
                                "the pinned hash")
    messages: list[dict] = [{"role": "user", "content": question}]
    for _ in range(max_steps):  # a step budget the model cannot change
        reply = model(messages, catalog)  # the model returns text only
        if "answer" in reply:
            return reply["answer"]
        call = reply["tool_call"]
        name, args = call["name"], call["args"]
        tool = catalog.get(name)  # control 2a: the allowlist
        if tool is None or not workflow.allows(f"invoke:{name}"):
            return refuse(name, "not an allowed call for this workflow")
        if set(args) != tool.args:  # control 2b: exact arguments
            return refuse(name, "unexpected arguments")
        identity = tool.identity  # control 3: the tool's own identity
        approver = "-"
        if identity.requires_approval:  # control 4: the approval gate
            reasons = [t.refusal(name, args, trace_id=trace_id,
                                 requested_by=requested_by, now=clock())
                       for t in approvals] or ["needs an approval token"]
            if None not in reasons:
                return refuse(name, reasons[0])
            approver = approvals[reasons.index(None)].approved_by
        result = tool.run(identity, **args)  # untrusted context
        log.info("ran trace_id=%s tool=%s identity=%s requested_by=%s "
                 "approved_by=%s", trace_id, name, identity.name,
                 requested_by, approver)
        messages += [{"role": "assistant", "content": json.dumps(call)},
                     {"role": "tool", "content": json.dumps(result)}]
    return "Stopped: step budget exhausted."
