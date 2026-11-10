"""The finding: one record per thing the detectors decided, keyed so two nights agree.

Chapter 14, W5-D5 and W5-D9. A finding is what the drift comparison (drift.py) and the four waste
detectors (waste.py) return, what the attribution (attribution.py) and the suppression (waste.suppress)
annotate, what the templates (render.py) turn into HCL, and what step 4's ledger stores and keys a pull
request on. Everything in it is computed from fields the readers returned; no model wrote any of it.

The key is the pull request's identity (W5-D9): the workspace, the resource's state address or, where it
has none, its cloud id, and the kind. The same inputs on two nights give the same key, so the night after
updates the same pull request instead of opening another. A route inside a route table is its own finding
keyed by the route's id (`<route table id>_<destination>`), the id the AWS provider imports it by.

Author-controlled text (a tag value, a user agent, a description) may appear in `evidence` and
`attribution` as data (W5-D12); nothing here reads it, and the tests show it moves no decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, NamedTuple

__all__ = ["KINDS", "DRIFT_KINDS", "WASTE_KINDS", "MASK_PREFIX", "Finding", "Scope", "finding_key",
           "is_masked", "sort_findings", "replace"]

DRIFT_KINDS = ("unmanaged", "changed", "missing")
WASTE_KINDS = ("untagged", "idle", "unattached_volume", "old_snapshot", "graviton_candidate")
KINDS = DRIFT_KINDS + WASTE_KINDS
MASK_PREFIX = "[masked hmac-sha256:"  # servers/common.MASK's prefix: a state value the reader masked (W5-D4)


class Scope(NamedTuple):
    """One workspace and the account and Region behind it: what every finding of a night's pass carries."""
    workspace: str
    account: str
    account_id: str
    region: str


@dataclass(frozen=True)
class Finding:
    key: str
    kind: str
    workspace: str
    account: str
    region: str
    resource_type: str  # the Terraform type (aws_instance, aws_route, ...) whatever the finding's source
    address: str | None  # the state address, or None for a resource (or a route) the state does not hold
    resource_id: str  # the cloud id: an instance id, a volume id, a group id, an ARN, `<rtb>_<cidr>` for a route
    evidence: dict[str, Any] = field(default_factory=dict)  # the facts that decided it
    attribution: dict[str, Any] | None = None  # from the audit trail (attribution.attribute), or None
    estimated_monthly_saving: float | None = None  # in the fixture's synthetic unit; None for drift
    suppressed_by: str | None = None  # a ServiceNow exception number (waste.suppress), or None
    template: str = ""  # which template renders it (render.TEMPLATES)

    def subject(self) -> str:
        """The address when the state holds the resource, its cloud id otherwise: the key's middle part."""
        return self.address or self.resource_id


def finding_key(scope: Scope, kind: str, address: str | None, resource_id: str) -> str:
    """workspace:subject:kind, the stable identity of a finding across nights (W5-D9). A route's subject
    is always its id, because the route table's address is the table's, not the route's."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}, got {kind!r}")
    return f"{scope.workspace}:{address or resource_id}:{kind}"


def is_masked(value: Any) -> bool:
    """Whether a state value is the reader's mask marker rather than the value."""
    return isinstance(value, str) and value.startswith(MASK_PREFIX) and value.endswith("]")


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Drift first, then waste, each kind in KINDS' order, then by key: the same order every night."""
    return sorted(findings, key=lambda f: (KINDS.index(f.kind), f.key))
