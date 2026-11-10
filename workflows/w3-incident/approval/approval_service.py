"""Larkspur's approval service: the gate that holds a write until a person with the right identity says yes.

Chapter 12, W3-D5, W3-D6, W3-D7. Chapter 3 said no vendor sells approval and Larkspur built one
service for all its workflows, backed by Teams and Entra, with one audit trail; chapter 4's
lst-04-03 gave the record's shape as a token: a person's yes to one call with one argument set, in
one run, for fifteen minutes by default, from someone other than the requester. This service is
that token made durable, with the rules chapters 2 and 4 add:

- a request names the workflow, the run (trace identifier), the tool and its canonical arguments,
  the service, the requester, and its expiry; the approvers are the group the service map names for
  the service, and the number of distinct approvals the step needs (W3-D6);
- a decision arrives with the approver's own token (the bot asks for it on the approver's behalf),
  and is refused, and the refusal recorded, when the request is unknown, expired, or already
  decided, when the approver is the requester, when the approver does not hold the approvers
  group, or when the same person approves twice;
- a check answers the write tool's question, whether a recorded yes covers exactly this call in
  this run and has not been applied yet (chapter 7's write tool asks the same); the apply mark is
  set once;
- the model never sees any of it: the harness passes the approval's number to the write tool.

The store is one SQLite file of its own; the service is one system with one audit log, not a part
of the harness. The HTTP layer at the bottom is the lab's; the interface is what matters.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO

import yaml

HERE = Path(__file__).resolve().parent
W3 = HERE.parent
W2 = W3.parent / "w2-ops-assistant"
W1 = W3.parent / "w1-knowledge-assistant"
CH05 = W3.parents[1] / "labs" / "ch05"
for folder in (W1 / "knowledge-server", CH05 / "harness"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from access import AccessError, MembershipTable, TokenPolicy, caller_from_headers  # noqa: E402
from client import json_line  # noqa: E402

SERVICE_MAP_PATH = W2 / "catalog" / "service-map.yaml"
DEFAULT_TTL_SECONDS = 900  # fifteen minutes, lst-04-03's default
# The approval service's own app registration, the delegated scope a person's token carries to decide, and
# the clients that may ask for such a token on a person's behalf: the Teams bot and the Slack bridge. The
# values are synthetic, like W1's and W2's.
APPROVAL_APP = "5c6d7e8f-9a0b-5c1d-8e2f-3a4b5c6d7e8f"
APPROVAL_SCOPE = "Approvals.Decide"
TEAMS_BOT = "c1d2e3f4-a5b6-5c7d-9e8f-0a1b2c3d4e5f"
SLACK_BRIDGE = "d2e3f4a5-b6c7-5d8e-8f9a-1b2c3d4e5f6a"
APPROVER_POLICY = TokenPolicy(audience=APPROVAL_APP, scope=APPROVAL_SCOPE, clients=frozenset({TEAMS_BOT, SLACK_BRIDGE}))

PENDING, APPROVED, DECLINED, EXPIRED = "pending", "approved", "declined", "expired"


def canonical_args(args: dict[str, Any]) -> str:
    """One stable string per argument set, so a record covers exactly one call (lst-04-03)."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"))


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Refused(Exception):
    """A request, decision, check, or apply the rules do not allow; the text is the reason, recorded."""


@dataclass(frozen=True)
class Approvers:
    group: str
    required: int = 1


def load_approvers(path: Path = SERVICE_MAP_PATH) -> dict[str, Approvers]:
    """The service map's `approvers` section: who may approve a step on each service, and how many (W3-D6)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    section = data.get("approvers") or {}
    if "default" not in section:
        raise ValueError(f"{path} has no approvers.default entry")
    return {service: Approvers(str(spec["group"]), int(spec.get("required", 1))) for service, spec in section.items()}


SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    approval_id    TEXT PRIMARY KEY,
    workflow       TEXT NOT NULL,
    trace_id       TEXT NOT NULL,
    tool           TEXT NOT NULL,
    args           TEXT NOT NULL,
    service        TEXT NOT NULL,
    requester_oid  TEXT NOT NULL,
    requester_upn  TEXT NOT NULL,
    approvers      TEXT NOT NULL,
    required       INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    status         TEXT NOT NULL,
    applied_at     TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    approval_id TEXT NOT NULL,
    at          TEXT NOT NULL,
    oid         TEXT,
    upn         TEXT,
    approved    INTEGER,
    accepted    INTEGER NOT NULL,
    reason      TEXT NOT NULL
);
"""


class Service:
    """The approval service's rules over its store. `clock` is injectable so the tests can let time pass."""

    def __init__(self, store_path: Path | str, table: Callable[[], MembershipTable], secret: str,
                 approvers: dict[str, Approvers], log: TextIO, *, clock: Callable[[], datetime] | None = None,
                 on_request: Callable[[dict[str, Any]], None] | None = None,
                 on_decided: Callable[[dict[str, Any]], None] | None = None,
                 policy: TokenPolicy = APPROVER_POLICY) -> None:
        self.db = sqlite3.connect(str(store_path), isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)
        self.table, self.secret, self.approvers, self.log = table, secret, approvers, log
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.on_request, self.on_decided, self.policy = on_request, on_decided, policy

    # --- requests ---------------------------------------------------------------------------------

    def approvers_for(self, service: str) -> Approvers:
        return self.approvers.get(service) or self.approvers["default"]

    def request(self, *, workflow: str, trace_id: str, tool: str, args: dict[str, Any], service: str,
                requester_oid: str, requester_upn: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict[str, Any]:
        who = self.approvers_for(service)
        now = self.clock()
        approval_id = f"APR-{uuid.uuid4().hex[:10]}"
        self.db.execute(
            "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (approval_id, workflow, trace_id, tool, canonical_args(args), service, requester_oid, requester_upn,
             who.group, who.required, iso(now), iso(now + timedelta(seconds=ttl_seconds)), PENDING))
        record = self.get(approval_id)
        json_line(self.log, event="approval_requested", approval_id=approval_id, trace_id=trace_id, workflow=workflow,
                  tool=tool, args=args, service=service, requester=requester_oid, approvers=who.group,
                  required=who.required, expires_at=record["expires_at"])
        if self.on_request:
            self.on_request(record)
        return record

    def get(self, approval_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM requests WHERE approval_id = ?", (approval_id,)).fetchone()
        if row is None:
            raise Refused("no such approval")
        columns = [c[1] for c in self.db.execute("PRAGMA table_info(requests)")]
        record = dict(zip(columns, row))
        record["args"] = json.loads(record["args"])
        if record["status"] == PENDING and self.clock() >= parse_iso(record["expires_at"]):
            self.db.execute("UPDATE requests SET status = ? WHERE approval_id = ?", (EXPIRED, approval_id))
            record["status"] = EXPIRED
        rows = self.db.execute("SELECT at, oid, upn, approved, accepted, reason FROM decisions WHERE approval_id = ? "
                               "ORDER BY rowid", (approval_id,)).fetchall()
        record["decisions"] = [{"at": at, "oid": oid, "upn": upn, "approved": bool(approved) if approved is not None else None,
                                "accepted": bool(accepted), "reason": reason}
                               for at, oid, upn, approved, accepted, reason in rows]
        record["approved_by"] = [d["oid"] for d in record["decisions"] if d["accepted"] and d["approved"]]
        return record

    # --- decisions --------------------------------------------------------------------------------

    def decide(self, approval_id: str, token: str, approved: bool, reason: str = "") -> dict[str, Any]:
        """A person's decision, with their own token. Every refusal is recorded against the request."""
        record = self.get(approval_id)
        now = self.clock()
        try:
            caller = caller_from_headers({"x-larkspur-actor": token}, self.table(), self.secret, now=now,
                                         policy=self.policy)
        except AccessError as exc:
            self._refuse(approval_id, now, None, None, approved, str(exc))
        if record["status"] == EXPIRED:
            self._refuse(approval_id, now, caller.oid, caller.upn, approved, "the approval has expired")
        if record["status"] != PENDING:
            self._refuse(approval_id, now, caller.oid, caller.upn, approved, "already decided")
        if caller.oid == record["requester_oid"]:
            self._refuse(approval_id, now, caller.oid, caller.upn, approved, "the requester cannot approve their own call")
        if record["approvers"] not in caller.groups:
            self._refuse(approval_id, now, caller.oid, caller.upn, approved, f"not in the approvers group {record['approvers']}")
        if approved and caller.oid in record["approved_by"]:
            self._refuse(approval_id, now, caller.oid, caller.upn, approved, "already approved by this person")
        self.db.execute("INSERT INTO decisions VALUES (?, ?, ?, ?, ?, 1, ?)",
                        (approval_id, iso(now), caller.oid, caller.upn, int(approved), reason))
        if not approved:
            status = DECLINED
        elif len(record["approved_by"]) + 1 >= record["required"]:
            status = APPROVED
        else:
            status = PENDING
        self.db.execute("UPDATE requests SET status = ? WHERE approval_id = ?", (status, approval_id))
        json_line(self.log, event="approval_decision", approval_id=approval_id, trace_id=record["trace_id"],
                  by=caller.oid, approved=approved, accepted=True, status=status, reason=reason)
        record = self.get(approval_id)
        if status != PENDING and self.on_decided:
            self.on_decided(record)
        return record

    def _refuse(self, approval_id: str, now: datetime, oid: str | None, upn: str | None, approved: bool,
                reason: str) -> None:
        self.db.execute("INSERT INTO decisions VALUES (?, ?, ?, ?, ?, 0, ?)",
                        (approval_id, iso(now), oid, upn, int(approved), reason))
        json_line(self.log, event="approval_decision", approval_id=approval_id, by=oid, approved=approved,
                  accepted=False, reason=reason)
        raise Refused(reason)

    # --- the write tool's questions ---------------------------------------------------------------

    def check(self, approval_id: str, *, tool: str, args: dict[str, Any],
              trace_id: str) -> dict[str, Any]:
        """Does a recorded yes cover exactly this call in this run, within
        its time, not yet applied?"""
        try:
            record = self.get(approval_id)
        except Refused as exc:
            return self._checked(approval_id, trace_id, False, str(exc))
        if record["tool"] != tool or \
                canonical_args(record["args"]) != canonical_args(args):
            return self._checked(
                approval_id, trace_id, False,
                "the approval is for another call")
        if record["trace_id"] != trace_id:
            return self._checked(
                approval_id, trace_id, False,
                "the approval is for another run")
        if self.clock() >= parse_iso(record["expires_at"]):
            return self._checked(
                approval_id, trace_id, False, "the approval has expired")
        if record["status"] != APPROVED:
            return self._checked(
                approval_id, trace_id, False,
                f"the approval is {record['status']}")
        if record["applied_at"]:
            return self._checked(
                approval_id, trace_id, False, "already applied")
        return self._checked(approval_id, trace_id, True, "covered",
                             approved_by=record["approved_by"])

    def _checked(self, approval_id: str, trace_id: str, covers: bool, reason: str, **extra: Any) -> dict[str, Any]:
        json_line(self.log, event="approval_check", approval_id=approval_id, trace_id=trace_id, covers=covers, reason=reason)
        return {"covers": covers, "reason": reason, **extra}

    def mark_applied(self, approval_id: str) -> dict[str, Any]:
        """The write tool reports that it acted; a second mark is refused, so each approval applies once."""
        record = self.get(approval_id)
        if record["status"] != APPROVED:
            raise Refused(f"the approval is {record['status']}")
        if record["applied_at"]:
            raise Refused("already applied")
        self.db.execute("UPDATE requests SET applied_at = ? WHERE approval_id = ?", (iso(self.clock()), approval_id))
        json_line(self.log, event="approval_applied", approval_id=approval_id, trace_id=record["trace_id"])
        return self.get(approval_id)


# --- the lab's HTTP layer ---------------------------------------------------------------------------

def http_handler(service: Service, key: str) -> type[BaseHTTPRequestHandler]:
    """POST /requests; GET /requests/{id}; POST /requests/{id}/decisions (the approver's token in
    X-Larkspur-Actor); POST /requests/{id}/check; POST /requests/{id}/applied. The harness and the write tools
    carry the service's key; a decision carries the person's token and nothing else."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:  # the audit log is the service's, not the socket's
            pass

        def _json(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")

        def _keyed(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {key}"

        def do_GET(self) -> None:  # noqa: N802
            parts = self.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "requests":
                if not self._keyed():
                    return self._json(401, {"error": "the service's key is required"})
                try:
                    return self._json(200, service.get(parts[1]))
                except Refused as exc:
                    return self._json(404, {"error": str(exc)})
            self._json(404, {"error": "no such path"})

        def do_POST(self) -> None:  # noqa: N802
            parts = self.path.strip("/").split("/")
            try:
                body = self._body()
            except ValueError:
                return self._json(400, {"error": "the body is not JSON"})
            try:
                if parts == ["requests"]:
                    if not self._keyed():
                        return self._json(401, {"error": "the service's key is required"})
                    return self._json(201, service.request(**body))
                if len(parts) == 3 and parts[0] == "requests":
                    approval_id, action = parts[1], parts[2]
                    if action == "decisions":
                        token = self.headers.get("X-Larkspur-Actor", "")
                        if token.lower().startswith("bearer "):
                            token = token[7:]
                        return self._json(200, service.decide(approval_id, token, bool(body.get("approved")),
                                                              str(body.get("reason", ""))))
                    if not self._keyed():
                        return self._json(401, {"error": "the service's key is required"})
                    if action == "check":
                        return self._json(200, service.check(approval_id, tool=body["tool"], args=body["args"],
                                                             trace_id=body["trace_id"]))
                    if action == "applied":
                        return self._json(200, service.mark_applied(approval_id))
            except Refused as exc:
                return self._json(403, {"error": str(exc)})
            except (KeyError, TypeError) as exc:
                return self._json(400, {"error": f"bad request: {exc}"})
            self._json(404, {"error": "no such path"})

    return Handler


def serve(service: Service, key: str, host: str = "127.0.0.1", port: int = 8780) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), http_handler(service, key))
    json_line(service.log, event="approval_service_start", host=host, port=port)
    return server
