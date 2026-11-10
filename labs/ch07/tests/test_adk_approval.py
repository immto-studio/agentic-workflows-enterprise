"""Approval on ADK: the long-running pattern Larkspur uses, and what tool confirmation did in 2.13.0.

Chapter 7. Each test runs the real ADK runner and session service with a rule-based model, and
starts a second runner on a fresh session-service object before the approver answers, the way a
new Agent Runtime instance would pick the conversation up.
"""

from __future__ import annotations

import asyncio
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "adk"))

from approval import ApprovalService, Deployments, RestartTool  # noqa: E402
from approval_matrix import confirmation, long_running  # noqa: E402

PERSISTENT = ["sqlite", "database"]


@pytest.mark.parametrize("kind", PERSISTENT)
def test_long_running_approval_survives_a_restart(kind: str, tmp_path: Path) -> None:
    outcome = asyncio.run(long_running(kind, tmp_path))
    assert outcome.paused, "the first turn must stop at the request, with nothing restarted"
    assert "waiting for approval APR-0001" in outcome.waiting
    assert outcome.restarts == 1
    assert outcome.answer.startswith("Restarted claims-api")
    assert not outcome.error


@pytest.mark.parametrize("kind", PERSISTENT)
def test_a_decision_delivered_twice_restarts_once(kind: str, tmp_path: Path) -> None:
    """ADK hands the duplicate to the model without the restart it already made, so the model asks
    again; the write tool's one restart per approval is what holds (2.13.0, both services)."""
    outcome = asyncio.run(long_running(kind, tmp_path, deliveries=2))
    assert outcome.restarts == 1
    assert outcome.write_calls == 2, "if ADK starts dropping the duplicate, update the chapter"


@pytest.mark.parametrize("kind", PERSISTENT)
def test_a_rejection_restarts_nothing_and_says_so(kind: str, tmp_path: Path) -> None:
    outcome = asyncio.run(long_running(kind, tmp_path, approved=False))
    assert outcome.restarts == 0
    assert "not restarted" in outcome.answer


ARGS = {"namespace": "claims", "deployment": "claims-api"}


def test_the_approval_service_records_who_decided_and_writes_nothing() -> None:
    approvals = ApprovalService()
    approval_id = approvals.file("restart_deployment", ARGS)
    approvals.decide(approval_id, approver="tomasz.nowak@larkspur.example", approved=True)
    assert approvals.relay(approval_id) == {"status": "approved", "approval_id": approval_id,
                                            "approver": "tomasz.nowak@larkspur.example", "reason": ""}
    assert approvals.approves(approval_id, "restart_deployment", ARGS)


def test_the_write_tool_refuses_what_the_approval_does_not_cover() -> None:
    approvals = ApprovalService()
    tool = RestartTool(approvals, Deployments())
    approval_id = approvals.file("restart_deployment", ARGS)
    assert tool.call(ARGS, approval_id)["status"] == "refused", "no decision yet"
    approvals.decide(approval_id, approver="tomasz.nowak@larkspur.example", approved=True)
    other = {"namespace": "payments", "deployment": "ledger"}
    assert tool.call(other, approval_id)["status"] == "refused", "a yes for another restart"
    assert tool.call(ARGS, approval_id)["status"] == "restarted"
    assert tool.call(ARGS, approval_id)["status"] == "restarted"
    assert tool.cluster.restarts == 1, "one restart per approval"


def test_tool_confirmation_works_in_memory(tmp_path: Path) -> None:
    outcome = asyncio.run(confirmation("in-memory", tmp_path))
    assert outcome.paused and outcome.restarts == 1


@pytest.mark.parametrize("kind", PERSISTENT)
def test_tool_confirmation_on_persistent_sessions_as_observed(kind: str, tmp_path: Path) -> None:
    """ADK's documentation lists the database service as unsupported for tool confirmation.

    In google-adk 2.13.0 the flow paused and resumed on both SQLite-backed services, across a
    new runner. This test runs on any ADK version and fails with what it saw, so an upgrade that
    changes the behaviour shows up here. The status that decides Larkspur's design is the
    documented one.
    """
    adk = version("google-adk")
    outcome = asyncio.run(confirmation(kind, tmp_path))
    (tmp_path / "no").mkdir()
    rejected = asyncio.run(confirmation(kind, tmp_path / "no", approved=False))
    observed = (f"google-adk {adk}, {kind}: paused={outcome.paused} restarts={outcome.restarts} "
                f"error={outcome.error!r}; rejected restarts={rejected.restarts}")
    assert outcome.paused and outcome.restarts == 1 and not outcome.error, observed
    assert rejected.restarts == 0, observed
