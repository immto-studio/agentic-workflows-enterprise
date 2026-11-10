"""W3's durable store: every transition of a run written before the next step acts, and "apply once" records.

Chapter 12, W3-D2. The lab's store is one SQLite file; in production the same three tables are a
database the next invocation reads (the fact sheet, section A: a DynamoDB table with a conditional
write, or a LangGraph checkpointer in `sync` mode, has this shape). Three tables:

- `runs`: one row per run, keyed by the trace identifier, with its current state. A restarted
  harness reads this row and continues from it; it holds nothing a restart loses.
- `transitions`: one row per state change, in order, with the payload that caused it (the
  proposal, the approval's number, the write's result, the verification). Together with the
  approval record they are the change record chapter 2's board asked for.
- `applied`: one row per side effect that may run once (a write, a change record), keyed by the
  approval's number and the tool. The row is inserted before the effect runs and completed after
  it; a second attempt finds the row and does not act. The insert is the conditional write: it
  succeeds only if no row with that key exists.

The store knows nothing about the states' meaning; `machine.py` does.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    trace_id   TEXT PRIMARY KEY,
    workflow   TEXT NOT NULL,
    requester  TEXT NOT NULL,
    service    TEXT,
    question   TEXT NOT NULL,
    state      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transitions (
    trace_id   TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    from_state TEXT,
    to_state   TEXT NOT NULL,
    at         TEXT NOT NULL,
    payload    TEXT NOT NULL,
    PRIMARY KEY (trace_id, seq)
);
CREATE TABLE IF NOT EXISTS applied (
    key        TEXT PRIMARY KEY,
    trace_id   TEXT NOT NULL,
    started_at TEXT NOT NULL,
    done_at    TEXT,
    result     TEXT
);
"""


class AlreadyApplied(Exception):
    """The side effect behind this key has run, or started to run, before."""

    def __init__(self, key: str, result: Any, finished: bool) -> None:
        super().__init__(f"{key} already applied" if finished else f"{key} already started")
        self.key = key
        self.result = result
        self.finished = finished


@dataclass(frozen=True)
class Transition:
    seq: int
    from_state: str | None
    to_state: str
    at: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RunRow:
    trace_id: str
    workflow: str
    requester: str
    service: str | None
    question: str
    state: str
    created_at: str
    updated_at: str


class Store:
    """The SQLite store. One connection per Store; every write is one transaction."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(str(self.path), isolation_level=None)  # explicit transactions below
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")  # the write is on disk before the next step runs
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")

    # --- runs and transitions -------------------------------------------------------------------

    def create_run(self, trace_id: str, *, workflow: str, requester: str, question: str, state: str,
                   service: str | None = None, payload: dict[str, Any] | None = None) -> None:
        """The run's row and its first transition, in one transaction."""
        at = now_iso()
        with self.transaction() as c:
            c.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (trace_id, workflow, requester, service, question, state, at, at))
            c.execute("INSERT INTO transitions VALUES (?, 1, NULL, ?, ?, ?)",
                      (trace_id, state, at, json.dumps(payload or {}, sort_keys=True)))

    def record_transition(self, trace_id: str, from_state: str, to_state: str, payload: dict[str, Any],
                          *, service: str | None = None) -> int:
        """Write the transition and move the run's row, in one transaction; returns the sequence number.

        The caller writes before it acts: the row says the run is in `to_state` even if the process dies
        a moment later, and a resumed run continues from `to_state` without repeating what came before."""
        at = now_iso()
        with self.transaction() as c:
            row = c.execute("SELECT state FROM runs WHERE trace_id = ?", (trace_id,)).fetchone()
            if row is None:
                raise KeyError(trace_id)
            if row[0] != from_state:
                raise ValueError(f"{trace_id} is in {row[0]}, not {from_state}")
            seq = c.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM transitions WHERE trace_id = ?",
                            (trace_id,)).fetchone()[0]
            c.execute("INSERT INTO transitions VALUES (?, ?, ?, ?, ?, ?)",
                      (trace_id, seq, from_state, to_state, at, json.dumps(payload, sort_keys=True)))
            if service is not None:
                c.execute("UPDATE runs SET state = ?, updated_at = ?, service = ? WHERE trace_id = ?",
                          (to_state, at, service, trace_id))
            else:
                c.execute("UPDATE runs SET state = ?, updated_at = ? WHERE trace_id = ?", (to_state, at, trace_id))
        return seq

    def run(self, trace_id: str) -> RunRow | None:
        row = self.connection.execute("SELECT * FROM runs WHERE trace_id = ?", (trace_id,)).fetchone()
        return RunRow(*row) if row else None

    def transitions(self, trace_id: str) -> list[Transition]:
        rows = self.connection.execute(
            "SELECT seq, from_state, to_state, at, payload FROM transitions WHERE trace_id = ? ORDER BY seq",
            (trace_id,)).fetchall()
        return [Transition(seq, from_state, to_state, at, json.loads(payload))
                for seq, from_state, to_state, at, payload in rows]

    def runs_in(self, *states: str) -> list[RunRow]:
        """The runs waiting in one of the given states, oldest first: what a resumed harness looks for."""
        marks = ",".join("?" for _ in states)
        rows = self.connection.execute(f"SELECT * FROM runs WHERE state IN ({marks}) ORDER BY updated_at",
                                       states).fetchall()
        return [RunRow(*row) for row in rows]

    # --- apply once -----------------------------------------------------------------------------

    def reserve(self, key: str, trace_id: str) -> None:
        """Claim the key before the effect runs; raises AlreadyApplied
        if the key exists, done or not.

        This is the conditional write: an `INSERT` on a primary key, which
        fails if the row exists. A key present without `done_at` means the
        effect began and the process died before it was recorded; the
        caller must not act again and should verify instead."""
        try:
            with self.transaction() as c:
                c.execute(
                    "INSERT INTO applied (key, trace_id, started_at) "
                    "VALUES (?, ?, ?)", (key, trace_id, now_iso()))
        except sqlite3.IntegrityError:
            row = self.connection.execute(
                "SELECT done_at, result FROM applied WHERE key = ?",
                (key,)).fetchone()
            done_at, result = row
            raise AlreadyApplied(
                key, json.loads(result) if result else None,
                finished=done_at is not None) from None

    def complete(self, key: str, result: Any) -> None:
        with self.transaction() as c:
            c.execute("UPDATE applied SET done_at = ?, result = ? WHERE key = ?",
                      (now_iso(), json.dumps(result, sort_keys=True), key))

    def applied(self, key: str) -> tuple[bool, Any] | None:
        """(finished, result) for a key, or None if the effect was never started."""
        row = self.connection.execute("SELECT done_at, result FROM applied WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        done_at, result = row
        return done_at is not None, (json.loads(result) if result else None)
