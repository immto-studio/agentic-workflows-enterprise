"""In-memory fake of what W5's policy reader reads: the tagging standard as data, and ServiceNow's exceptions.

Chapter 14, W5-D3 and W5-D9. The standard is Larkspur's "Cloud resource tagging standard" from the
corpus (workflows/w1-knowledge-assistant/corpus/docs/pol-cloud-resource-tagging-standard.md), turned into
fields a detector reads: the five required tags, the values `env` may take, the stop-and-delete days for
untagged non-production resources, and how an exception is granted. The exceptions are the records the
catalogue item "Policy exception" produces in ServiceNow, in the style of W4's ServiceNow fake
(workflows/w4-change/servers/servicenow_fake.py): a number, the resource, the tag, the reason, who approved,
and when it expires. FinOps approves for up to ninety days; one approved record covers a sandbox-quill
resource so step 3 can suppress a finding (W5-D9), one has expired, and one is still pending.

A reason is a requester's text and is served as data; nothing here is planted, because the four planted
texts of W5-D12 sit in the state, the inventory, the trail, and the bill.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TypedDict

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from cloud_fake import IDS  # noqa: E402

__all__ = ["TAGGING_STANDARD", "EXCEPTION_STATES", "TaggingStandard", "ExceptionList", "get_tagging_standard",
           "list_policy_exceptions"]

EXCEPTION_STATES = ("approved", "expired", "pending", "all")


class TaggingStandard(TypedDict):
    title: str
    doc_type: str
    owner_team: str
    classification: str
    effective: str
    approved_by: str
    last_reviewed: str
    review_cycle: str
    required_tags: list[str]
    env_values: list[str]
    untagged_non_production: dict[str, int]
    enforcement: str
    exceptions: dict[str, Any]
    source: str


class ExceptionList(TypedDict):
    state: str
    count: int
    exceptions: list[dict[str, Any]]


TAGGING_STANDARD = TaggingStandard(
    title="Cloud resource tagging standard",
    doc_type="policy",
    owner_team="finops",
    classification="Internal",
    effective="2025-01-10",
    approved_by="CISO",
    last_reviewed="2025-02-02",
    review_cycle="yearly",
    required_tags=["owner_team", "cost_center", "env", "service", "data_classification"],
    env_values=["prod", "stg", "dev", "sandbox", "lab"],
    untagged_non_production={"stop_after_days": 7, "delete_after_days": 30},
    enforcement="Tag policies in AWS Organizations and Azure Policy enforce the values; exceptions go through FinOps.",
    exceptions={"channel": "ServiceNow catalogue item: Policy exception", "approved_by": "finops", "max_days": 90},
    source="corpus/docs/pol-cloud-resource-tagging-standard.md",
)

# ServiceNow requested items from the catalogue item, keyed by number. `tag` names the required tag the
# exception excuses; `expires` is at most ninety days after the approval.
_EXCEPTIONS: list[dict[str, Any]] = [
    {"number": "RITM0045021", "catalog_item": "Policy exception", "state": "approved",
     "account": "lm-sandbox", "resource_id": IDS["notebook_instance"], "tag": "cost_center",
     "reason": "Quill research sandbox; the cost centre is assigned at the integration's quarter-end review",
     "requested_by": "quill.data-lead", "approved_by": "finops", "approved": "2026-10-01", "expires": "2026-12-30"},
    {"number": "RITM0044310", "catalog_item": "Policy exception", "state": "expired",
     "account": "lm-sandbox", "resource_id": IDS["archive_volume"], "tag": "data_classification",
     "reason": "archive of the pre-migration batch outputs, classification pending the data review",
     "requested_by": "quill.data-lead", "approved_by": "finops", "approved": "2026-07-02", "expires": "2026-09-30"},
    {"number": "RITM0045188", "catalog_item": "Policy exception", "state": "pending",
     "account": "lm-sandbox", "resource_id": IDS["orphan_volume"], "tag": "owner_team",
     "reason": "scratch space for the notebook migration; owner to be confirmed",
     "requested_by": "quill.data-lead", "approved_by": None, "approved": None, "expires": None},
    # The notebook host's root volume lacks the same two tags; both are excused, so this is the fixture night's
    # one fully excused finding: suppressed, no pull request (W5-D9). The notebook itself keeps one tag missing.
    {"number": "RITM0045233", "catalog_item": "Policy exception", "state": "approved",
     "account": "lm-sandbox", "resource_id": IDS["notebook_root_volume"], "tag": "cost_center",
     "reason": "sandbox root volume of the notebook host, tagged with the host at its quarter-end review",
     "requested_by": "quill.data-lead", "approved_by": "finops", "approved": "2026-10-20", "expires": "2026-12-15"},
    {"number": "RITM0045234", "catalog_item": "Policy exception", "state": "approved",
     "account": "lm-sandbox", "resource_id": IDS["notebook_root_volume"], "tag": "data_classification",
     "reason": "sandbox root volume of the notebook host; it carries the host's classification once the host is tagged",
     "requested_by": "quill.data-lead", "approved_by": "finops", "approved": "2026-10-20", "expires": "2026-12-15"},
]


def get_tagging_standard() -> TaggingStandard:
    """The current version of the standard as fields: the required tags, the env values, the days, and
    the exception path. The source is the corpus document; its text is the policy, this is its data."""
    return TaggingStandard(**TAGGING_STANDARD)


def list_policy_exceptions(state: str) -> ExceptionList:
    """The exception records in one state (approved, expired, pending) or all of them."""
    if state not in EXCEPTION_STATES:
        raise ValueError(f"state must be one of {', '.join(EXCEPTION_STATES)}, got {state!r}")
    hits = [dict(record) for record in _EXCEPTIONS if state == "all" or record["state"] == state]
    return ExceptionList(state=state, count=len(hits), exceptions=hits)
