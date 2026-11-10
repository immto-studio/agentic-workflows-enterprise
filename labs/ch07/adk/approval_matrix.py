"""Run both approval patterns against ADK's session services, with a restart in the middle.

Chapter 7. Each scenario is one engineer asking the incident workflow for a restart. The first
turn runs on one runner; the approver's answer arrives on a second runner, built on a fresh
session-service object over the same database, the way a new Agent Runtime instance would pick the
conversation up. The in-memory service can't survive a restart, so its second turn reuses the same
object, which is its best case.

The Agent Platform session service (VertexAiSessionService) needs a Google Cloud project, so it is
not in the matrix; ADK's documentation lists it beside the database service as unsupported for
tool confirmation.

Run:  python adk/approval_matrix.py --out results/2026-10-29/adk-approval.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService
from google.genai import types

from approval import ApprovalService, Deployments, RestartTool, confirmation_agent, long_running_agent

APP, USER = "incident", "engineer@larkspur.example"
QUESTION = "Restart claims-api in the claims namespace."
CONFIRMATION_CALL = "adk_request_confirmation"


class Sessions:
    """The session service for the first turn, and a fresh one after the restart."""

    def __init__(self, kind: str, folder: Path) -> None:
        self.kind, self.folder, self.opened = kind, folder, []
        self.first = self.after_restart() if kind != "in-memory" else self._keep(InMemorySessionService())

    def _keep(self, service: BaseSessionService) -> BaseSessionService:
        self.opened.append(service)
        return service

    def after_restart(self) -> BaseSessionService:
        if self.kind == "in-memory":  # nothing survives a restart, so reuse the object
            return self.opened[0]
        if self.kind == "sqlite":
            from google.adk.sessions.sqlite_session_service import SqliteSessionService

            return self._keep(SqliteSessionService(str(self.folder / "sessions-sqlite.db")))
        if self.kind == "database":
            from google.adk.sessions import DatabaseSessionService

            url = f"sqlite+aiosqlite:///{(self.folder / 'sessions-sqlalchemy.db').as_posix()}"
            return self._keep(DatabaseSessionService(db_url=url))
        raise ValueError(self.kind)

    async def close(self) -> None:
        for service in self.opened:
            close = getattr(service, "close", None)
            if close is not None:
                await close()


async def turn(runner: Runner, session_id: str, message: types.Content) -> list[Event]:
    return [event async for event in runner.run_async(user_id=USER, session_id=session_id, new_message=message)]


def calls(events: list[Event], name: str) -> list[types.FunctionCall]:
    return [call for event in events for call in event.get_function_calls() if call.name == name]


def final_text(events: list[Event]) -> str:
    texts = [part.text for event in events if event.content for part in event.content.parts or [] if part.text]
    return texts[-1] if texts else ""


def reply(call_id: str, name: str, response: dict[str, Any]) -> types.Content:
    part = types.Part(function_response=types.FunctionResponse(id=call_id, name=name, response=response))
    return types.Content(role="user", parts=[part])


@dataclass
class Outcome:
    pattern: str
    sessions: str
    approved: bool  # the approver's answer
    paused: bool  # the first turn stopped and waited for a person, with nothing restarted
    waiting: str  # what the engineer read while the request waited
    answer: str  # what the engineer read after the approver's answer
    restarts: int  # how many times the deployment restarted
    write_calls: int = 0  # how many times the agent called the write tool
    error: str = ""


async def confirmation(kind: str, folder: Path, approved: bool = True) -> Outcome:
    """ADK's tool confirmation: the runner pauses on adk_request_confirmation; the reply confirms."""
    deployments = Deployments()
    write_tool = RestartTool(ApprovalService(), deployments)
    agent = confirmation_agent(write_tool)
    sessions = Sessions(kind, folder)
    try:
        session = await sessions.first.create_session(app_name=APP, user_id=USER)
        events = await turn(Runner(app_name=APP, agent=agent, session_service=sessions.first), session.id,
                            types.Content(role="user", parts=[types.Part(text=QUESTION)]))
        pending = calls(events, CONFIRMATION_CALL)
        outcome = Outcome("tool confirmation", kind, approved, paused=bool(pending) and deployments.restarts == 0,
                          waiting=final_text(events), answer="", restarts=deployments.restarts)
        if not pending:
            return outcome
        runner = Runner(app_name=APP, agent=agent, session_service=sessions.after_restart())
        try:
            events = await turn(runner, session.id, reply(pending[0].id or "", CONFIRMATION_CALL, {"confirmed": approved}))
            outcome.answer = final_text(events)
        except Exception as exc:  # noqa: BLE001 - the matrix records whatever ADK does
            outcome.error = f"{type(exc).__name__}: {exc}"
        outcome.restarts = deployments.restarts
        outcome.write_calls = write_tool.calls
        return outcome
    finally:
        await sessions.close()


async def long_running(kind: str, folder: Path, approved: bool = True, deliveries: int = 1) -> Outcome:
    """A long-running approval call: the decision comes back as its response, then the write runs."""
    deployments = Deployments()
    approvals = ApprovalService()
    write_tool = RestartTool(approvals, deployments)
    agent = long_running_agent(approvals, write_tool)
    sessions = Sessions(kind, folder)
    try:
        session = await sessions.first.create_session(app_name=APP, user_id=USER)
        events = await turn(Runner(app_name=APP, agent=agent, session_service=sessions.first), session.id,
                            types.Content(role="user", parts=[types.Part(text=QUESTION)]))
        pending = calls(events, "request_approval")
        outcome = Outcome("long-running tool", kind, approved, paused=bool(pending) and deployments.restarts == 0,
                          waiting=final_text(events), answer="", restarts=deployments.restarts)
        if not pending:
            return outcome
        runner = Runner(app_name=APP, agent=agent, session_service=sessions.after_restart())
        try:
            for _ in range(deliveries):  # the approval service may deliver the same decision twice
                approvals.decide("APR-0001", approver="tomasz.nowak@larkspur.example", approved=approved)
                decision = approvals.relay("APR-0001")
                events = await turn(runner, session.id, reply(pending[0].id or "", "request_approval", decision))
                outcome.answer = final_text(events)
        except Exception as exc:  # noqa: BLE001
            outcome.error = f"{type(exc).__name__}: {exc}"
        outcome.restarts = deployments.restarts
        outcome.write_calls = write_tool.calls
        return outcome
    finally:
        await sessions.close()


async def matrix(folder: Path) -> list[Outcome]:
    results = []
    for kind in ("in-memory", "sqlite", "database"):
        for approved in (True, False):
            name = f"{kind}-{'yes' if approved else 'no'}"
            results.append(await confirmation(kind, folder / f"confirm-{name}", approved))
            results.append(await long_running(kind, folder / f"long-{name}", approved, deliveries=2))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="write the results as JSON here")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        for kind in ("in-memory", "sqlite", "database"):
            for prefix in ("confirm", "long"):
                for answer in ("yes", "no"):
                    (Path(tmp) / f"{prefix}-{kind}-{answer}").mkdir()
        results = asyncio.run(matrix(Path(tmp)))
    for result in results:
        print(f"{result.pattern:18} {result.sessions:9} approved={result.approved!s:5} paused={result.paused!s:5} "
              f"write_calls={result.write_calls} restarts={result.restarts} answer={result.answer!r} {result.error}")
    if args.out:
        record = {"google-adk": version("google-adk"), "python": sys.version.split()[0],
                  "results": [asdict(r) for r in results]}
        args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
