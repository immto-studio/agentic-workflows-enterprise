"""Larkspur's change policy, as the evidence pack applies it: the freeze window, the CAB cadence, and
which services are tier-0 or in the payments slice.

Chapter 13, W4-D10. The facts are the current change-management policy (the companion's
`pol-change-management.md`, and the fact sheet C.0): the change advisory board meets Thursdays at 14:00
ET; standard, normal, and emergency are the change types; the year-end freeze runs 2026-12-14 to
2027-01-04; a production deploy through the GitHub Actions `production` environment needs an approved
ServiceNow change number and one reviewer from the owning team. W4 reads these and flags a change that
lands in the freeze window or that a normal change cannot get a CAB slot for in time; it enforces
nothing (GitHub's environment gate and the board do).

The service tiers are Larkspur's: `fraud-scoring` is tier-0, and the payments slice (chapter 4's never
slice) is kept off every workflow, so a change that touches it is always High and is flagged here.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

FREEZE_START = date(2026, 12, 14)
FREEZE_END = date(2027, 1, 4)
CAB_WEEKDAY = 3  # Thursday (Monday is 0)
CAB_TIME_ET = "14:00 ET"
PRODUCTION_ENVIRONMENT_RULE = ("the production GitHub Actions environment needs an approved ServiceNow "
                               "change number and one reviewer from the owning team")

TIER0_SERVICES = frozenset({"fraud-scoring"})
PAYMENTS_SLICE_SERVICES = frozenset({"billing-worker"})
# A changed file path under the payments slice, whatever the service: the slice is chapter 4's never slice.
PAYMENTS_PATH_HINTS = ("terraform/payments/", "/payments/", "payments-", "billing-ledger", "cardholder")


def _parse(iso_date: str | None) -> date | None:
    if not iso_date:
        return None
    try:
        return date.fromisoformat(iso_date[:10])
    except ValueError:
        return None


def in_freeze_window(iso_date: str | None) -> bool:
    day = _parse(iso_date)
    return day is not None and FREEZE_START <= day <= FREEZE_END


def next_cab_date(iso_date: str | None) -> str | None:
    """The next Thursday on or after the given date: when the board could review the change."""
    day = _parse(iso_date)
    if day is None:
        return None
    ahead = (CAB_WEEKDAY - day.weekday()) % 7
    return (day + timedelta(days=ahead)).isoformat()


def check(evidence: dict[str, Any]) -> dict[str, Any]:
    """Apply the policy to one change's evidence; return the facts and any
    flags for the board."""
    planned = evidence.get("planned_start")
    frozen = in_freeze_window(planned)
    flags: list[str] = []
    if frozen:
        flags.append("in-freeze-window")
    if frozen and evidence.get("change_class") == "normal":
        flags.append("normal change needs a pre-freeze CAB "
                     "or an emergency path")
    if evidence.get("touches_payments_slice"):
        flags.append("touches the payments slice")
    return {
        "planned_start": planned,
        "in_freeze_window": frozen,
        "freeze_window": (f"{FREEZE_START.isoformat()} to "
                          f"{FREEZE_END.isoformat()}"),
        "next_cab": next_cab_date(planned),
        "cab_cadence": f"Thursdays at {CAB_TIME_ET}",
        "production_rule": PRODUCTION_ENVIRONMENT_RULE,
        "flags": flags,
    }
