"""The ServiceNow fake: the service's recent changes (a read), and the evidence pack W4 writes.

Chapter 13, W4-D7. W4 writes an evidence pack to a ServiceNow change request: the scribe fills the
request's fields and attaches the gathered evidence, by this tool and not the model, keyed once on the
change reference so a re-run updates the one record rather than opening another. The record is left in
Assess for the owning team and the change advisory board; W4 never moves it to Implement (rung 2). The
fields are ServiceNow's, as the fact sheet lists them (C.3). This mirrors W3's `servers/changes.py`
store pattern (one JSON file, `SERVICENOW_STATE_FILE`, an atomic replace), with evidence-pack semantics.

The pack's text is plain: the pull request's title and body are quoted as data, never as instructions,
because the incident workflow reads these tickets later (chapter 4's second-order injection, W4-D12).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

MAX_WINDOW_MINUTES = 30 * 24 * 60  # a month: change history looks back further than an incident
SHORT_DESCRIPTION_MAX = 160  # the field's length; the title is cut to fit after the reference
JUSTIFICATION_MAX = 320


def short_description(change_ref: str, title: str) -> str:
    """The record's short description: the change reference first, then the pull request's title, cut to
    the field's length. The title is an author's text, so it is labeled as one and bounded, and cannot
    pass as a system note to the incident workflow that reads these records later (W4-D12; the reader
    review's finding 2)."""
    return f"PR {change_ref}: {' '.join(title.split())}"[:SHORT_DESCRIPTION_MAX]


class Change(TypedDict):
    number: str
    age_minutes: int
    type: Literal["standard", "normal", "emergency"]
    state: str
    short_description: str
    configuration_item: str


_RECENT: dict[str, list[Change]] = {
    "claims-api": [
        Change(number="CHG0041001", age_minutes=4320, type="standard", state="Closed",
               short_description="Rotate the claims-api TLS certificate", configuration_item="claims-api"),
    ],
    "fraud-scoring": [
        Change(number="CHG0041010", age_minutes=10080, type="normal", state="Closed",
               short_description="fraud-scoring model refresh", configuration_item="fraud-scoring"),
    ],
}


def recent_changes(service: str, minutes: int) -> dict[str, Any]:
    """The change records on one service within the last `minutes` minutes, newest first (a read)."""
    if not 1 <= minutes <= MAX_WINDOW_MINUTES:
        raise ValueError(f"minutes must be between 1 and {MAX_WINDOW_MINUTES}, got {minutes}")
    hits = sorted((c for c in _RECENT.get(service, []) if c["age_minutes"] <= minutes),
                  key=lambda c: c["age_minutes"])
    return {"service": service, "window_minutes": minutes, "count": len(hits), "changes": hits}


def _iso(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_path() -> Path:
    path = os.environ.get("SERVICENOW_STATE_FILE", "").strip()
    if not path:
        raise RuntimeError("SERVICENOW_STATE_FILE is not set")
    return Path(path)


def _load(path: Path) -> dict[str, dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(path: Path, data: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(tmp, path)


_COUNTER = {"n": 41100}


def write_evidence_pack(*, change_ref: str, service: str, title: str, pr_url: str, risk_class: str,
                        rationale: str, reasons: list[str], justification: str, implementation_plan: str,
                        backout_plan: str, assignment_group: str, change_class: str, trace_id: str,
                        requested_by: str, evidence: dict[str, Any], policy: dict[str, Any],
                        path: Path | None = None) -> dict[str, Any]:
    """Create or update one change request with the evidence pack, keyed on the change reference (W4-D7).

    The record is left in New (or Assess once CI has passed); W4 does not move it to Implement, which is
    the rung-2 line. The fields map to ServiceNow's (fact sheet C.3). The gathered evidence is attached.
    """
    store = path or _state_path()
    data = _load(store)
    existing = data.get(change_ref)
    if existing is None:
        _COUNTER["n"] += 1
        number = f"CHG{_COUNTER['n']:07d}"
    else:
        number = existing["number"]  # keep the record's number across updates: one record per change
    state = "Assess" if evidence.get("ci_state") == "success" else "New"
    record = {
        "number": number,
        "change_ref": change_ref,
        "type": change_class,
        "state": state,
        "short_description": short_description(change_ref, title),
        "description": f"Change {change_ref} ({pr_url}); run {trace_id[:8]}.",
        "justification": justification[:JUSTIFICATION_MAX],
        "implementation_plan": implementation_plan,
        "backout_plan": backout_plan,
        "risk": risk_class,
        "risk_reasons": reasons,
        "risk_rationale": rationale,
        "configuration_item": service,
        "assignment_group": assignment_group,
        "planned_start_date": evidence.get("planned_start"),
        "requested_by": requested_by,
        "trace_id": trace_id,
        "policy": policy,
        "evidence": evidence,  # the gathered facts, attached; quoted data, not instructions
        "close_code": None,
        "close_notes": None,
        "opened_at": existing["opened_at"] if existing else _iso(),
        "updated_at": _iso(),
    }
    data[change_ref] = record
    _save(store, data)
    return record


def get_change(change_ref: str, *, path: Path | None = None) -> dict[str, Any] | None:
    return _load(path or _state_path()).get(change_ref)
