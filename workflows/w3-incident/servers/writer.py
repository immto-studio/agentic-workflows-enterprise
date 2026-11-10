"""The writer: the two write tools W3 runs after an approval, each under its own identity, and the
verification read and rollback the harness uses.

Chapter 12, W3-D4, W3-D8. W2's three servers stay read-only in every annotation and every identity, so
the writes live here, on a server of their own. Each write tool, before it acts, asks the approval
service whether a recorded yes covers exactly this call in this run, within its time, and not yet
applied; it marks the approval applied, so a retry after a timeout finds it applied and does nothing
(chapter 7's write tool asks the same). The approval's number does the idempotency key's job. A tool
that cannot ask the service, or cannot set the mark, does not act either.

A write's result names, under `previous`, the state its rollback returns to. A scale has one, the
replica count before it. A restart has none (W3-D8), so its `previous` is None and what it replaced
is kept under `replaced`, for the record only.

In production each write tool is a tool on a Kubernetes MCP server whose identities hold only the verbs
the two writes need: `restart_deployment` patches the deployment's pod template (the `restartedAt`
annotation), `scale_deployment` patches `deployments/scale` (the fact sheet, B.1 and B.3). In the lab
the writes change the shared cluster state (`cluster_state.py`) that W2's `get_pod_status` reads back,
so the verification sees the write. The verification's definition is the Deployment's own three marks
of completion (B.5): every replica updated, every replica available, and no old replica running, which
the lab reads as `ready` at `desired` with no pod pending.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from cluster_state import ClusterState


class ApprovalCheck(Protocol):
    def check(self, approval_id: str, *, tool: str, args: dict[str, Any], trace_id: str) -> dict[str, Any]: ...
    def applied(self, approval_id: str) -> dict[str, Any]: ...


class ApprovalNotCovered(Exception):
    """The approval does not cover this call; the write does not run. The text is the service's reason."""


class ApprovalUnchecked(Exception):
    """The approval service could not be asked, or could not record the apply mark; the write does not run."""


IDENTITY = {"restart_deployment": "larkspur-ops-restarter", "scale_deployment": "larkspur-ops-scaler"}


class Writer:
    """The write path. `approvals` is the approval client; `state_path` is the shared cluster-state file."""

    def __init__(self, approvals: ApprovalCheck, state_path: Path | str) -> None:
        self.approvals = approvals
        self.state = ClusterState(Path(state_path))

    def _gate(self, tool: str, args: dict[str, Any], approval_id: str, trace_id: str) -> dict[str, Any] | None:
        """The approval check and the once-only apply mark. Returns the prior result when already applied."""
        try:
            verdict = self.approvals.check(approval_id, tool=tool, args=args, trace_id=trace_id)
        except Exception as exc:  # the service is down or unreachable: no yes was read, so nothing runs
            raise ApprovalUnchecked(f"the approval could not be checked ({type(exc).__name__})") from exc
        if not verdict.get("covers"):
            raise ApprovalNotCovered(verdict.get("reason", "the approval does not cover this call"))
        try:
            marked = self.approvals.applied(approval_id)
        except Exception as exc:  # the mark comes before the write, so a mark that failed means no write
            raise ApprovalUnchecked(f"the approval could not be marked applied ({type(exc).__name__})") from exc
        return marked

    def restart_deployment(self, args: dict[str, Any], approval_id: str, *, trace_id: str) -> dict[str, Any]:
        self._gate("restart_deployment", args, approval_id, trace_id)
        replaced, applied = self.state.restart(args["service"])
        return {"tool": "restart_deployment", "service": args["service"], "approval_id": approval_id,
                "previous": None, "replaced": replaced, "applied": applied}

    def scale_deployment(self, args: dict[str, Any], approval_id: str, *, trace_id: str) -> dict[str, Any]:
        self._gate("scale_deployment", args, approval_id, trace_id)
        previous, applied = self.state.scale(args["service"], args["replicas"])
        return {"tool": "scale_deployment", "service": args["service"], "approval_id": approval_id,
                "previous": previous, "applied": applied}

    # --- the verification read and the rollback the harness calls (triage.Services) ----------------

    def verify(self, run: Any, proposal: dict[str, Any], write: dict[str, Any]) -> dict[str, Any]:
        """A Deployment is complete when every replica is updated and available and no old replica is running
        (B.5): the lab reads `ready` at `desired` with no pod still Pending."""
        service = proposal["args"]["service"]
        current = self.state.current(service)
        pending = [p for p in current["pods"] if p["phase"] != "Running"]
        ok = current["ready"] == current["desired"] and not pending
        return {"ok": ok, "ready": current["ready"], "desired": current["desired"],
                "pending": len(pending), "generation": current["generation"]}

    def rollback(self, run: Any, proposal: dict[str, Any], write: dict[str, Any], approval_id: str) -> dict[str, Any]:
        """A scale whose verification failed is scaled back to the recorded count, under the same approval."""
        result = write.get("result") or {}
        previous = result.get("previous") or {}
        service = proposal["args"]["service"]
        if proposal["name"] == "scale_deployment" and "replicas" in previous:
            _, applied = self.state.scale(service, previous["replicas"])
            return {"scaled_back_to": previous["replicas"], "ready": applied["ready"]}
        return {"no_rollback": "a restart has no state to return to; the verification is its record"}
