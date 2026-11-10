"""Two ways to hold a write for a person's approval in ADK, built on the same restart.

Chapter 7. ADK's tool confirmation (`require_confirmation=True`) is marked experimental, and its
documentation lists the database and Agent Platform session services as unsupported. A
long-running tool is the documented alternative. Here the long-running call files a request with
Larkspur's approval service and returns "pending"; when the approver decides, the approval
service relays the decision back as the call's final response, and the agent then calls the write
tool with the approval's number.

The approval service records decisions and writes nothing. The write tool holds the write
identity, checks that a recorded yes covers exactly this call, and applies each approval once, as
the tool servers of the identity chapter do. All three classes here are stand-ins: in production
the approval service is the one Larkspur runs for every framework (Teams for the approver, Entra
for who they are, one audit trail), and the write tool is on the Kubernetes MCP server.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool, LongRunningFunctionTool

from runbook_model import RunbookModel

INSTRUCTION = "You are the incident workflow. Restart only what the engineer asks for."


@dataclass
class ApprovalService:
    """Holds requests until a person decides, and remembers who decided what."""

    requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def file(self, action: str, args: dict[str, Any]) -> str:
        approval_id = f"APR-{next(self._ids):04d}"
        self.requests[approval_id] = {"action": action, "args": args, "decision": None}
        return approval_id

    def decide(self, approval_id: str, approver: str, approved: bool, reason: str = "") -> None:
        self.requests[approval_id]["decision"] = {"approver": approver, "approved": approved, "reason": reason}

    def approves(self, approval_id: str, action: str, args: dict[str, Any]) -> bool:
        """True only for a recorded yes to exactly this action with exactly these arguments."""
        request = self.requests.get(approval_id)
        decision = request and request["decision"]
        return bool(decision and decision["approved"] and request["action"] == action and request["args"] == args)

    def relay(self, approval_id: str) -> dict[str, Any]:
        """The final response the approval service sends back to the waiting call."""
        decision = self.requests[approval_id]["decision"]
        status = "approved" if decision["approved"] else "rejected"
        return {"status": status, "approval_id": approval_id, "approver": decision["approver"],
                "reason": decision["reason"] or ("" if decision["approved"] else "declined")}


@dataclass
class Deployments:
    """The cluster, reduced to what the tests count."""

    restarts: int = 0


@dataclass
class RestartTool:
    """The write tool: its own identity, the approval check, one restart per approval."""

    approvals: ApprovalService
    cluster: Deployments
    applied: dict[str, str] = field(default_factory=dict)  # approval -> change
    calls: int = 0  # how often an agent asked, which can exceed the restarts

    def call(self, args: dict[str, Any], approval_id: str) -> dict[str, Any]:
        self.calls += 1
        if not self.approvals.approves(approval_id, "restart_deployment", args):
            return {"status": "refused",
                    "reason": f"{approval_id} does not approve this restart"}
        if approval_id not in self.applied:  # a repeat changes nothing
            self.cluster.restarts += 1
            change = f"CHG{len(self.applied) + 1:04d}"
            self.applied[approval_id] = f"{change} {args['namespace']}/{args['deployment']}"
        return {"status": "restarted", "approval_id": approval_id,
                "change": self.applied[approval_id]}


def long_running_agent(approvals: ApprovalService,
                       write_tool: RestartTool) -> LlmAgent:
    """Approval as a long-running call; the write as a tool."""

    def request_approval(action: str, namespace: str,
                         deployment: str) -> dict[str, Any]:
        """Ask a person to approve an action; pending until then."""
        args = {"namespace": namespace, "deployment": deployment}
        approval_id = approvals.file(action, args)
        return {"status": "pending", "approval_id": approval_id}

    def restart_deployment(namespace: str, deployment: str,
                           approval_id: str) -> dict[str, Any]:
        """Restart a deployment that a person has approved."""
        args = {"namespace": namespace, "deployment": deployment}
        return write_tool.call(args, approval_id)

    tools = [LongRunningFunctionTool(request_approval),
             FunctionTool(restart_deployment)]
    return LlmAgent(name="incident", model=RunbookModel(),
                    instruction=INSTRUCTION, tools=tools)


def confirmation_agent(write_tool: RestartTool) -> LlmAgent:
    """The same write behind ADK's tool confirmation, as the ADK documentation shows it."""

    def restart_deployment(namespace: str, deployment: str) -> dict[str, Any]:
        """Restart a deployment in a namespace. A person must confirm first."""
        args = {"namespace": namespace, "deployment": deployment}
        # ADK's confirmation says yes without saying who; the record can only name the mechanism.
        approval_id = write_tool.approvals.file("restart_deployment", args)
        write_tool.approvals.decide(approval_id, approver="unknown (adk confirmation)", approved=True)
        return write_tool.call(args, approval_id)

    tool = FunctionTool(restart_deployment, require_confirmation=True)
    return LlmAgent(name="incident", model=RunbookModel(), instruction=INSTRUCTION, tools=[tool])
