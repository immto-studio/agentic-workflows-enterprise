"""The evidence the analyst gathers for one change, derived from the GitHub, Terraform, and ServiceNow fakes.

Chapter 13, W4-D3 and W4-D5. The analyst returns one structured artifact: the facts about a change,
read from the fakes (step 3). Everything here is a fact about the change, never an instruction: the pull
request's title and body are untrusted text (W4-D12), and the rubric reads the fields below, not any
prose. `derive_evidence` is the pure function the tests exercise; `gather_evidence` wires the fakes to it
and keeps the signature the analyst calls, so the agents did not change from step 2.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SERVERS = Path(__file__).resolve().parents[1] / "servers"
if str(_SERVERS) not in sys.path:
    sys.path.insert(0, str(_SERVERS))

import github_fake  # noqa: E402
import servicenow_fake  # noqa: E402
import terraform_fake  # noqa: E402

import policy  # noqa: E402  (sibling in a2a/)

# The fields the analyst produces and the rubric reads. Booleans are facts the analyst derives.
EVIDENCE_FIELDS = (
    "change_ref", "service", "title", "author",
    "files_changed", "additions", "deletions",
    "touches_deploy", "touches_tier0", "touches_payments_slice",
    "ci_state", "rollback_plan_present", "change_class", "in_freeze_window",
)

CHANGES_WINDOW_MINUTES = 30 * 24 * 60  # a month of change history


class SourceUnavailable(RuntimeError):
    """A source the analyst reads could not be read. `source` names it, so the analyst can fail the task
    with the source's name rather than leave it in working (chapter 13's reader review, finding 1)."""

    def __init__(self, source: str, change_ref: str, cause: Exception) -> None:
        super().__init__(f"the {source} read for {change_ref} failed: {cause}")
        self.source = source


def blank_evidence(change_ref: str, service: str) -> dict[str, Any]:
    """A low-risk default: a normal change, CI green, a rollback named, nothing special touched."""
    return {
        "change_ref": change_ref, "service": service, "title": "", "author": "",
        "files_changed": 1, "additions": 0, "deletions": 0,
        "touches_deploy": False, "touches_tier0": False, "touches_payments_slice": False,
        "ci_state": "success", "rollback_plan_present": True, "change_class": "normal",
        "in_freeze_window": False,
    }


def parse_change_ref(text: str) -> tuple[str, str]:
    """Pull a `repo#number` reference and the service out of the task text. Lenient on purpose."""
    token = ""
    for word in text.replace(",", " ").split():
        if "#" in word:
            token = word.strip(".;:)(")
            break
    if not token:
        raise ValueError("no change reference of the form repo#number in the request")
    service = token.split("#", 1)[0].rsplit("/", 1)[-1]
    return token, service


def _is_deploy(path: str) -> bool:
    low = path.lower()
    return low.startswith("deploy/") or "/deploy/" in low or low.endswith(".tf") or low.startswith("terraform/")


def _names_tier0(path: str) -> bool:
    low = path.lower()
    return any(svc in low for svc in policy.TIER0_SERVICES)


def _is_payments(path: str) -> bool:
    low = path.lower()
    return any(hint in low for hint in policy.PAYMENTS_PATH_HINTS)


def _change_class(labels: list[str]) -> str:
    lower = {label.lower() for label in labels}
    if "emergency" in lower:
        return "emergency"
    if "standard" in lower:
        return "standard"
    return "normal"


def derive_evidence(pr: dict[str, Any], ci_state: str, plan: dict[str, Any] | None) -> dict[str, Any]:
    """Derive the evidence fields from a pull request, its CI state, and its Terraform plan. Pure."""
    files = pr["files"]
    service = pr["repo"]
    paths = [f["filename"] for f in files]
    body = (pr.get("body") or "").lower()
    change_ref = f"{pr['repo']}#{pr['number']}"
    evidence = {
        "change_ref": change_ref,
        "service": service,
        "title": pr.get("title", ""),
        "author": pr.get("user", ""),
        "files_changed": len(files),
        "additions": sum(f["additions"] for f in files),
        "deletions": sum(f["deletions"] for f in files),
        "touches_deploy": any(_is_deploy(p) for p in paths) or plan is not None,
        "touches_tier0": service in policy.TIER0_SERVICES or any(_names_tier0(p) for p in paths),
        "touches_payments_slice": service in policy.PAYMENTS_SLICE_SERVICES or any(_is_payments(p) for p in paths),
        "ci_state": ci_state,
        "rollback_plan_present": "rollback" in body or "backout" in body,
        "change_class": _change_class(pr.get("labels", [])),
        "in_freeze_window": policy.in_freeze_window(pr.get("planned_start")),
        "planned_start": pr.get("planned_start"),
        "pr_url": f"https://github.invalid/larkspur/{pr['repo']}/pull/{pr['number']}",
        "terraform": {"has_destroy": plan["has_destroy"], "has_replace": plan["has_replace"],
                      "resource_changes": plan["resource_changes"]} if plan else None,
    }
    return evidence


def gather_evidence(change_ref: str, service: str) -> dict[str, Any]:
    """Read the GitHub, Terraform, and ServiceNow fakes for a change and derive the evidence (step 3).

    A read that fails raises SourceUnavailable with the source's name; the analyst fails the task with it.
    """
    try:
        pr = github_fake.get_pull_request(change_ref)
        ci_state = github_fake.combined_status(pr)
    except Exception as exc:
        raise SourceUnavailable("GitHub", change_ref, exc) from exc
    try:
        plan = terraform_fake.plan(change_ref)
    except Exception as exc:
        raise SourceUnavailable("Terraform plan", change_ref, exc) from exc
    evidence = derive_evidence(pr, ci_state, plan)
    try:
        recent = servicenow_fake.recent_changes(service, CHANGES_WINDOW_MINUTES)
    except Exception as exc:
        raise SourceUnavailable("ServiceNow", change_ref, exc) from exc
    evidence["recent_changes_count"] = recent["count"]
    return evidence
