"""Shared fixtures for W3's tests: a store in a temporary folder, a scripted model, fake reads and writes, a stub
approval service. Step 2 of the plan (#10) tests the machine, the store, and the loop with these; later steps
replace the fakes with W2's servers, the writer, and the approval service."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

W3 = Path(__file__).resolve().parents[1]
for folder in (W3 / "state", W3 / "harness"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from machine import Machine  # noqa: E402
from store import Store  # noqa: E402
from triage import Harness, Services  # noqa: E402

ENGINEER = "oncall.engineer"  # the lab persona of W2, a member of engineering
APPROVER = "incident.responder"  # holds lm-sec-incident-response, the default approvers group
ALLOWED = {"get_pod_status": {"service"}, "get_recent_events": {"service", "minutes"},
           "search_logs": {"service", "needle", "minutes"}}
WRITES = ("restart_deployment", "scale_deployment")


class KillSwitch(BaseException):
    """The process dies here: raised by a fake at the moment the test names, never caught by the harness."""


class ScriptedModel:
    """Replies in order; records every message list it was shown and whether tools were offered."""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.seen: list[list[dict[str, str]]] = []
        self.offers: list[bool] = []
        self.offer_tools = True

    def __call__(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.seen.append([dict(m) for m in messages])
        self.offers.append(self.offer_tools)
        if not self.replies:
            return {"answer": "nothing more to say", "reasoning": None}
        return self.replies.pop(0)


def call(name: str, args: dict[str, Any], call_id: str = "c1") -> dict[str, Any]:
    return {"id": call_id, "name": name, "args": args}


def reply(*calls: dict[str, Any], reasoning: str | None = None) -> dict[str, Any]:
    return {"tool_calls": list(calls), "reasoning": reasoning}


def answer(text: str, reasoning: str | None = None) -> dict[str, Any]:
    return {"answer": text, "reasoning": reasoning}


class Reads:
    """Fake read tools that record their calls. `failing` names tools that return a given error."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.errors: dict[str, str] = {}

    def get_pod_status(self, service: str) -> dict[str, Any]:
        self.calls.append(("get_pod_status", {"service": service}))
        if "get_pod_status" in self.errors:
            return {"error": self.errors["get_pod_status"]}
        return {"service": service, "ready": 1, "desired": 3, "replicas": 3, "image": "claims-api:4.2.1"}

    def get_recent_events(self, service: str, minutes: int) -> dict[str, Any]:
        self.calls.append(("get_recent_events", {"service": service, "minutes": minutes}))
        if "get_recent_events" in self.errors:
            return {"error": self.errors["get_recent_events"]}
        return {"service": service, "events": [{"reason": "BackOff", "message": "restarting failed container"}]}

    def search_logs(self, service: str, needle: str, minutes: int) -> dict[str, Any]:
        self.calls.append(("search_logs", {"service": service, "needle": needle, "minutes": minutes}))
        if "search_logs" in self.errors:
            return {"error": self.errors["search_logs"]}
        return {"service": service, "lines": []}

    def tools(self) -> dict[str, Any]:
        return {"get_pod_status": self.get_pod_status, "get_recent_events": self.get_recent_events,
                "search_logs": self.search_logs}


class Writer:
    """Fake write tools: each records its call and returns the state before and after. `kill_after` names a
    tool that dies right after acting, before the harness can record the result."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self.kill_after: set[str] = set()
        self.replicas = 3

    def restart_deployment(self, args: dict[str, Any], approval_id: str) -> dict[str, Any]:
        self.calls.append(("restart_deployment", args, approval_id))
        if "restart_deployment" in self.kill_after:
            raise KillSwitch()
        return {"previous": None, "applied": {"restartedAt": "2026-11-02T13:00:00Z"}}

    def scale_deployment(self, args: dict[str, Any], approval_id: str) -> dict[str, Any]:
        self.calls.append(("scale_deployment", args, approval_id))
        previous, self.replicas = self.replicas, args["replicas"]
        if "scale_deployment" in self.kill_after:
            raise KillSwitch()
        return {"previous": {"replicas": previous}, "applied": {"replicas": args["replicas"]}}

    def tools(self) -> dict[str, Any]:
        return {"restart_deployment": self.restart_deployment, "scale_deployment": self.scale_deployment}


class Verifier:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.rollbacks: list[tuple[str, dict[str, Any], str]] = []

    def verify(self, run, proposal, write) -> dict[str, Any]:
        self.calls.append((run.trace_id, write))
        return {"ok": self.ok, "ready": 3 if self.ok else 1, "desired": 3}

    def rollback(self, run, proposal, write, approval_id) -> dict[str, Any]:
        self.rollbacks.append((run.trace_id, write, approval_id))
        return {"replicas": write["result"]["previous"]["replicas"]}


class StubApprovals:
    """The approval service's interface, in memory: a request gets a number; a test decides or expires it."""

    def __init__(self) -> None:
        self.requests: dict[str, tuple[str, dict[str, Any], str]] = {}
        self.decisions: dict[str, dict[str, Any]] = {}
        self.expired_ids: set[str] = set()
        self.count = 0

    def request(self, trace_id: str, call: dict[str, Any], requester: str) -> str:
        self.count += 1
        approval_id = f"apr-{self.count:03d}"
        self.requests[approval_id] = (trace_id, call, requester)
        return approval_id

    def decision(self, approval_id: str) -> dict[str, Any] | None:
        return self.decisions.get(approval_id)

    def expired(self, approval_id: str) -> bool:
        return approval_id in self.expired_ids

    def decide(self, approval_id: str, approved: bool, by: str = APPROVER, reason: str = "") -> None:
        self.decisions[approval_id] = {"approved": approved, "by": by, "reason": reason}

    def last(self) -> str:
        return f"apr-{self.count:03d}"


# --- the approval service (step 3): W1's membership table and tokens, a clock the tests move -----------------

import importlib.util  # noqa: E402
import threading  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

for folder in (W3 / "approval", W3.parent / "w1-knowledge-assistant" / "knowledge-server"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

_spec = importlib.util.spec_from_file_location("w2_conftest", W3.parent / "w2-ops-assistant" / "tests" / "conftest.py")
w2c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w2c)

from access import MembershipTable, issue  # noqa: E402
from approval_cards import CardFolder  # noqa: E402
from approval_client import ApprovalClient  # noqa: E402
from approval_service import APPROVAL_APP, APPROVAL_SCOPE, TEAMS_BOT, Service, load_approvers, serve  # noqa: E402

USERS = w2c.USERS  # upn stem -> object ID, from W1's synthetic directory export
SECRET = w2c.SECRET
SERVICE_KEY = "w3-approval-service-key-for-tests"
APPROVERS = load_approvers()


def membership_table(age: timedelta = timedelta(minutes=1)) -> MembershipTable:
    now = datetime.now(timezone.utc) - age + timedelta(minutes=1)
    return MembershipTable.from_dict(w2c.fresh_table(now))


def approver_token(user: str, **overrides) -> str:
    """The token the bot gets for a person who pressed Approve: the approval service's app and scope."""
    shape = {"scope": APPROVAL_SCOPE, "client": TEAMS_BOT, "audience": APPROVAL_APP, **overrides}
    return issue(SECRET, USERS[user], f"{user}@larkspur.example", **shape)


class Clock:
    def __init__(self) -> None:
        # Real time, not a fixed date: the membership table is stamped at real time, and a clock behind it
        # would make the table look stale (W1-D27's clock skew rule) and strip the narrow groups.
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def cards_dir(tmp_path: Path) -> Path:
    return tmp_path / "cards"


@pytest.fixture
def approval_service(tmp_path: Path, clock: Clock, cards_dir: Path):
    """The service over a fresh store, a fresh membership table, and the card folder as the bot."""
    import io
    log = io.StringIO()
    folder = CardFolder(cards_dir, approver_mris={group: [f"29:{group}-member"] for group in
                                                  {a.group for a in APPROVERS.values()}})
    table = membership_table()
    service = Service(tmp_path / "approvals.sqlite", lambda: table, SECRET, APPROVERS, log, clock=clock,
                      on_request=folder.on_request, on_decided=folder.on_decided)
    service.test_log = log  # type: ignore[attr-defined]
    return service


@pytest.fixture
def approval_http(approval_service):
    """The service behind its HTTP layer on a free port, and a client for it."""
    server: ThreadingHTTPServer = serve(approval_service, SERVICE_KEY, port=free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield url, ApprovalClient(url, SERVICE_KEY, requester_upn=f"{ENGINEER}@larkspur.example")
    finally:
        server.shutdown()
        server.server_close()


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "w3-state.sqlite"


@pytest.fixture
def parts():
    """The fakes one test shares across harness instances, as the real services outlive a harness process."""
    return {"reads": Reads(), "writer": Writer(), "verifier": Verifier(), "approvals": StubApprovals()}


def harness_over(store_path: Path, model, parts: dict[str, Any], *, max_reads: int = 8,
                 with_rollback: bool = True) -> Harness:
    """A fresh harness process over the same store file and the same external services."""
    machine = Machine(Store(store_path))
    verifier = parts["verifier"]
    services = Services(model=model, tools=parts["reads"].tools(), allowed=dict(ALLOWED),
                        writes=parts["writer"].tools(), verify=verifier.verify, approvals=parts["approvals"],
                        rollback=verifier.rollback if with_rollback else None, max_reads=max_reads)
    return Harness(machine, services)


def states(harness: Harness, trace_id: str) -> list[str]:
    return [t.to_state for t in harness.machine.history(trace_id)]
