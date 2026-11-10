"""The risk rubric: a class from the evidence's facts, and the seam a model fills with a rationale.

Chapter 13, W4-D9. The risk score is one of Low, Medium, or High, computed by a fixed rule over the
analyst's evidence fields, in the shape of ServiceNow's rule-ordered risk conditions (the fact sheet,
D.1). The model never sets the class; it writes only the rationale prose, behind the `rationale` seam
that step 5 swaps for a model call. A score cannot authorize a change, and because the class is a pure
function of the fields, a hijacked analyst message cannot move it past the facts (W4-D12).
"""

from __future__ import annotations

from typing import Any

CLASSES = ("Low", "Medium", "High")

# Each condition is (field-test, the reason it records, the class it forces). Ordered high to low, as
# ServiceNow runs risk conditions by order; the score is the highest class any condition forces, and
# the reasons are every condition that matched, so the evidence pack shows why.
LARGE_DIFF = 800  # additions plus deletions above which a change is large enough to raise the class


def _has_destroy(e: dict[str, Any]) -> bool:
    return bool((e.get("terraform") or {}).get("has_destroy"))


def _has_replace(e: dict[str, Any]) -> bool:
    return bool((e.get("terraform") or {}).get("has_replace"))


_HIGH = [
    (lambda e: e.get("touches_payments_slice"),
     "the change touches the payments slice"),
    (lambda e: e.get("ci_state") == "failure", "CI failed"),
    (lambda e: e.get("change_class") == "emergency",
     "an emergency change"),
    (lambda e: e.get("in_freeze_window"),
     "the change lands in the freeze window"),
    (_has_destroy, "the Terraform plan destroys a resource"),
    (lambda e: (e.get("touches_tier0")
                and not e.get("rollback_plan_present")),
     "a tier-0 service with no rollback plan"),
]
_MEDIUM = [
    (lambda e: e.get("touches_tier0"), "a tier-0 service is touched"),
    (lambda e: (e.get("touches_deploy")
                and e.get("ci_state") != "success"),
     "a deployment change whose CI has not passed"),
    (_has_replace, "the Terraform plan replaces a resource"),
    (lambda e: not e.get("rollback_plan_present"),
     "no rollback plan is named"),
    (lambda e: e.get("additions", 0) + e.get("deletions", 0) > LARGE_DIFF,
     "a large diff"),
]


def score(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return {"risk_class", "reasons"} from the evidence's fields alone.
    Pure and deterministic."""
    high = [reason for test, reason in _HIGH if test(evidence)]
    medium = [reason for test, reason in _MEDIUM if test(evidence)]
    if high:
        return {"risk_class": "High", "reasons": high + medium}
    if medium:
        return {"risk_class": "Medium", "reasons": medium}
    return {"risk_class": "Low", "reasons": [
        "a standard-shaped change: CI passed, a rollback is named, "
        "nothing tier-0 or payments touched, outside the freeze"]}


def rationale(evidence: dict[str, Any], risk_class: str, reasons: list[str]) -> str:
    """STUB (step 2): a deterministic sentence from the class and the reasons. Step 5 swaps a model call
    here; the model writes the prose, never the class."""
    service = evidence.get("service", "the service")
    ref = evidence.get("change_ref", "the change")
    head = f"{risk_class} risk for {ref} on {service}"
    if not reasons:
        return head + "."
    joined = reasons[0] if len(reasons) == 1 else "; ".join(reasons[:-1]) + f"; and {reasons[-1]}"
    return f"{head}: {joined}."
