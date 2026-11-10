"""The identity chain: one identity for the workflow, one per tool, as plain objects.

Chapter 4, listing 4.1. Nothing here talks to a cloud. The point is the shape: every
identity carries an explicit set of scopes, the write identity additionally requires an
approval token, and the token is minted outside the model layer. The model can ask for
anything; it can never hold or forge any of these objects, because it only returns text.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    name: str
    scopes: frozenset[str]
    # a write identity never acts on the model's word alone
    requires_approval: bool = False

    def allows(self, scope: str) -> bool:
        return scope in self.scopes


# 1. The workflow identity. It may *invoke* two tools and nothing else.
#    It cannot read a pod or restart a deployment itself; those scopes
#    belong to the tool identities below.
WORKFLOW = Identity(
    name="workflow:ops-assistant",
    scopes=frozenset(
        {"invoke:get_pod_status", "invoke:restart_deployment"}
    ),
)

# 2. The read-only tool identity. get_pod_status runs under this alone.
POD_READER = Identity(
    name="tool:get_pod_status",
    scopes=frozenset({"pods:get"}),
)

# 3. The write tool identity, separate from the reader and gated by an
#    approval token.
DEPLOYMENT_RESTARTER = Identity(
    name="tool:restart_deployment",
    scopes=frozenset({"deployments:restart"}),
    requires_approval=True,
)


def canonical_args(args: dict) -> str:
    """One stable string per argument set, so a token covers exactly one call."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ApprovalToken:
    """A person's approval of one tool call with one exact argument set, in one run, for a while.

    Tokens are created by the harness operator (in the book: the approval service of the
    incident workflow) and passed to the harness. They never travel through the model. A token
    is bound to the run's trace id and expires, so last week's approval cannot cover today's
    injected call, and the person who asked for the call cannot be the one who approves it.
    """

    tool: str
    args: str  # canonical_args of the approved call
    trace_id: str  # the run the approval was given for
    approved_by: str
    expires_at: float  # epoch seconds

    @classmethod
    def for_call(cls, tool: str, args: dict, *, trace_id: str, approved_by: str,
                 ttl_seconds: float = 900, now: float | None = None) -> ApprovalToken:
        issued = time.time() if now is None else now
        return cls(tool=tool, args=canonical_args(args), trace_id=trace_id,
                   approved_by=approved_by, expires_at=issued + ttl_seconds)

    def refusal(self, tool: str, args: dict, *, trace_id: str,
                requested_by: str, now: float) -> str | None:
        """None when this token covers the call; else why it does not."""
        if self.tool != tool or self.args != canonical_args(args):
            return "the approval is for another call"
        if self.trace_id != trace_id:
            return "the approval is for another run"
        if now >= self.expires_at:
            return "the approval has expired"
        if self.approved_by == requested_by:
            return "the requester cannot approve their own call"
        return None
