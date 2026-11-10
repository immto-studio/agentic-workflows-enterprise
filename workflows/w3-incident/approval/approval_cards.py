"""The approval card: what an approver sees in Teams, and the lab's stand-in for the bot that posts it.

Chapter 12, W3-D13. The card is an Adaptive Card of schema version 1.5 with Universal Actions: an
`Action.Execute` for yes and one for no, each carrying the approval's number as data, an
`Action.Submit` fallback for older clients, and a `refresh` whose `userIds` list the approvers, so
that once a decision is in, the listed users see who decided and when in place of the buttons
(the fact sheet, D.1: Teams supports 1.6 or earlier; Universal Actions need 1.5 on the Teams page
and 1.4 on the Adaptive Cards page; a refresh addresses at most sixty users). The card does not
enforce anything: the approval service refuses a second press, whoever presses.

The lab has no Teams. `CardFolder` is the bot's stand-in: it writes each card as JSON into a folder,
one file per request and one per decision, and a test reads them back. A decision reaches the
service over HTTP with the approver's token, which is what the bot would do after an
`adaptiveCard/action` invoke, reading `from.aadObjectId` for the person.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
VERSION = "1.5"


def request_card(record: dict[str, Any], approver_mris: list[str]) -> dict[str, Any]:
    """The card an approver gets while the request is pending."""
    step = f"{record['tool']} {json.dumps(record['args'], sort_keys=True)}"
    return {
        "$schema": SCHEMA, "type": "AdaptiveCard", "version": VERSION,
        "refresh": {"userIds": approver_mris[:60],
                    "action": {"type": "Action.Execute", "verb": "refresh", "data": {"approval_id": record["approval_id"]}}},
        "body": [
            {"type": "TextBlock", "size": "Medium", "weight": "Bolder",
             "text": f"W3 asks to run a runbook step on {record['service']}"},
            {"type": "FactSet", "facts": [
                {"title": "Step", "value": step},
                {"title": "Requested by", "value": record["requester_upn"]},
                {"title": "Run", "value": record["trace_id"][:8]},
                {"title": "Expires", "value": record["expires_at"]},
                {"title": "Approvals needed", "value": str(record["required"])},
            ]},
            {"type": "TextBlock", "wrap": True, "isSubtle": True,
             "text": "The step runs only after approval, under the approval's number; the requester cannot approve it."},
        ],
        "actions": [
            {"type": "Action.Execute", "title": "Approve", "verb": "approve",
             "data": {"approval_id": record["approval_id"], "approved": True},
             "fallback": {"type": "Action.Submit", "title": "Approve", "data": {"approval_id": record["approval_id"], "approved": True}}},
            {"type": "Action.Execute", "title": "Decline", "verb": "decline",
             "data": {"approval_id": record["approval_id"], "approved": False},
             "fallback": {"type": "Action.Submit", "title": "Decline", "data": {"approval_id": record["approval_id"], "approved": False}}},
        ],
    }


def decided_card(record: dict[str, Any]) -> dict[str, Any]:
    """The card the refresh replaces the buttons with: the decision, by whom, and when."""
    accepted = [d for d in record["decisions"] if d["accepted"]]
    last = accepted[-1] if accepted else None
    verdict = {"approved": "Approved", "declined": "Declined", "expired": "Expired, nobody decided in time"}.get(
        record["status"], record["status"])
    facts = [{"title": "Step", "value": f"{record['tool']} {json.dumps(record['args'], sort_keys=True)}"},
             {"title": "Decision", "value": verdict}]
    if last:
        facts.append({"title": "By", "value": last["upn"] or last["oid"]})
        facts.append({"title": "At", "value": last["at"]})
    return {"$schema": SCHEMA, "type": "AdaptiveCard", "version": VERSION,
            "body": [{"type": "TextBlock", "size": "Medium", "weight": "Bolder",
                      "text": f"W3 runbook step on {record['service']}: {verdict.lower()}"},
                     {"type": "FactSet", "facts": facts}],
            "actions": []}


class CardFolder:
    """The bot's stand-in: cards as files. `mris` maps an Entra object ID to the Teams user MRI the bot would
    put in `refresh.userIds`; in the lab it is the identity function over the approvers' object IDs."""

    def __init__(self, folder: Path, approver_mris: dict[str, list[str]] | None = None) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.approver_mris = approver_mris or {}

    def on_request(self, record: dict[str, Any]) -> None:
        card = request_card(record, self.approver_mris.get(record["approvers"], []))
        (self.folder / f"{record['approval_id']}-request.json").write_text(json.dumps(card, indent=2), encoding="utf-8")

    def on_decided(self, record: dict[str, Any]) -> None:
        card = decided_card(record)
        (self.folder / f"{record['approval_id']}-decided.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
