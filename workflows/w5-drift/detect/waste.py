"""The four waste detectors against the tagging standard and the cost export, and the exception that suppresses.

Chapter 14, W5-D5, W5-D9, and W5-D10. Waste is the FinOps Framework's own list (the fact sheet, D.3):
resources created and no longer needed, stranded volumes, excessive snapshots, the wrong size or family.
Four detectors, each a pure function over what the readers returned, each with its thresholds as
constants here:

- `untagged`: a resource lacking one of the standard's five required tags, or carrying an `env` outside
  its values; one finding per resource, listing the missing and the bad tags. No saving: it is ownership.
- `idle`: an instance whose daily CPU over the last IDLE_WINDOW_DAYS days averages under IDLE_AVERAGE_PCT
  and never peaks over IDLE_MAXIMUM_PCT, with the figures in the evidence. Its proposal is one size down.
- `stranded`: a volume unattached for UNATTACHED_MIN_DAYS days or more (the standard's own seven days
  before it stops an untagged resource), and a snapshot older than SNAPSHOT_MAX_AGE_DAYS, from the night
  the harness passes in.
- `graviton`: an x86 instance of a family ADR-0050 would have on Graviton (GRAVITON_FAMILIES), with the
  suggested family and type in the evidence.

The estimated monthly saving is read from the cost export's rows for the resource id, in the fixture's
synthetic unit: the resource's unblended cost in the last complete billing month as the export holds it
(no extrapolation: a resource that appeared mid-month shows the part of the month it was billed for),
whole for a resource to remove (a stranded volume, an old snapshot), and a fixed fraction for one to
resize: IDLE_SAVING_FRACTION for one size down, GRAVITON_SAVING_FRACTION for the Graviton family (ADR-0050
measured 22 percent lower cost per request; the lab rounds down). A resource with no row has no estimate.

`suppress` applies the approved, unexpired exceptions from ServiceNow's catalogue item (W5-D9): an
exception names a resource and the required tag it excuses; the tag is struck from the finding's missing
list, recorded under `excused`, and the finding is marked `suppressed_by` the exception's number. A
finding with nothing left missing is fully excused and step 4 raises no pull request for it; one with a
tag still missing is raised with the exception named, so an exception for one tag never hides another.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from drift import KIND_TYPES, ManagedResource, index_state, index_tags, live_items, tags_of  # noqa: E402
from findings import Finding, Scope, finding_key, sort_findings  # noqa: E402
from render import template_for  # noqa: E402

__all__ = ["IDLE_WINDOW_DAYS", "IDLE_AVERAGE_PCT", "IDLE_MAXIMUM_PCT", "IDLE_SAVING_FRACTION", "GRAVITON_SAVING_FRACTION",
           "UNATTACHED_MIN_DAYS", "SNAPSHOT_MAX_AGE_DAYS", "GRAVITON_FAMILIES", "SIZES", "Costs", "cost_index",
           "managed_by_id", "untagged", "idle", "stranded", "graviton", "detect_waste", "suppress"]

IDLE_WINDOW_DAYS = 7
IDLE_AVERAGE_PCT = 5.0  # the window's mean of the daily averages must be under this ...
IDLE_MAXIMUM_PCT = 10.0  # ... and no daily maximum over this
IDLE_SAVING_FRACTION = 0.5  # one size down on the ladder is half the on-demand rate
GRAVITON_SAVING_FRACTION = 0.2  # ADR-0050: 22 percent lower cost per request, rounded down
UNATTACHED_MIN_DAYS = 7  # the standard's seven days
SNAPSHOT_MAX_AGE_DAYS = 90
# x86 families ADR-0050 would have on Graviton, and the family it would have.
GRAVITON_FAMILIES: dict[str, str] = {
    "m5": "m7g", "m5a": "m7g", "m6i": "m7g", "m6a": "m7g",
    "c5": "c7g", "c5a": "c7g", "c6i": "c7g", "c6a": "c7g",
    "r5": "r7g", "r5a": "r7g", "r6i": "r7g", "r6a": "r7g",
    "t3": "t4g", "t3a": "t4g",
}
SIZES = ("nano", "micro", "small", "medium", "large", "xlarge", "2xlarge", "3xlarge", "4xlarge", "6xlarge", "8xlarge",
         "9xlarge", "12xlarge", "16xlarge", "18xlarge", "24xlarge", "32xlarge", "48xlarge")


class Costs(NamedTuple):
    period: str  # the billing period the figures come from
    by_resource: dict[str, float]  # resource id -> unblended cost in that period

    def of(self, resource_id: str) -> float | None:
        cost = self.by_resource.get(resource_id)
        return None if cost is None else round(cost, 2)


def cost_index(*exports: dict[str, Any]) -> Costs:
    """The cost export's rows summed by resource id: one figure per resource for the period."""
    by_resource: dict[str, float] = {}
    period = ""
    for export in exports:
        period = period or export.get("billing_period", "")
        for row in export.get("rows", []):
            rid = row.get("line_item_resource_id") or ""
            if rid:
                by_resource[rid] = by_resource.get(rid, 0.0) + float(row.get("line_item_unblended_cost") or 0.0)
    return Costs(period, by_resource)


def managed_by_id(state: dict[str, Any]) -> dict[str, ManagedResource]:
    """The state's managed resources by cloud id, for the address a template needs."""
    return {rid: resource for (_, rid), resource in index_state(state).items()}


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _finding(scope: Scope, kind: str, type_: str, rid: str, managed: dict[str, ManagedResource], evidence: dict[str, Any],
             saving: float | None = None) -> Finding:
    resource = managed.get(rid)
    address = resource.address if resource is not None and resource.type == type_ else None
    finding = Finding(key=finding_key(scope, kind, address, rid), kind=kind, workspace=scope.workspace, account=scope.account,
                      region=scope.region, resource_type=type_, address=address, resource_id=rid, evidence=evidence,
                      estimated_monthly_saving=saving)
    return replace(finding, template=template_for(finding))


def _cost_evidence(costs: Costs, rid: str, fraction: float) -> tuple[dict[str, Any], float | None]:
    monthly = costs.of(rid)
    evidence = {"period": costs.period, "monthly": monthly, "fraction": fraction, "unit": "synthetic"}
    return evidence, None if monthly is None else round(monthly * fraction, 2)


def _size_down(instance_type: str) -> str | None:
    family, _, size = instance_type.partition(".")
    if size not in SIZES or SIZES.index(size) == 0:
        return None
    return f"{family}.{SIZES[SIZES.index(size) - 1]}"


# --- the detectors ---------------------------------------------------------------------------------------

def untagged(scope: Scope, inventory: Any, tags_by_resource: Any, standard: dict[str, Any],
             managed: dict[str, ManagedResource]) -> list[Finding]:
    """One finding per resource missing a required tag or carrying an env outside the standard's values."""
    required = list(standard.get("required_tags", []))
    allowed = {"env": list(standard.get("env_values", []))}
    tags_index = index_tags(*([tags_by_resource] if isinstance(tags_by_resource, dict) else tags_by_resource or []))
    out = []
    id_fields = {"instances": "InstanceId", "volumes": "VolumeId", "snapshots": "SnapshotId", "security_groups": "GroupId",
                 "route_tables": "RouteTableId", "load_balancers": "LoadBalancerArn"}
    for kind, type_ in KIND_TYPES.items():
        for item in live_items(inventory, kind):
            tags = tags_of(item, kind, tags_index)
            missing = [key for key in required if not tags.get(key)]
            bad = {key: tags[key] for key, values in allowed.items() if tags.get(key) and tags[key] not in values}
            if not missing and not bad:
                continue
            evidence = {"missing": missing, "bad": bad, "present": {k: tags[k] for k in required if tags.get(k)},
                        "required": required, "allowed": allowed}
            out.append(_finding(scope, "untagged", type_, item[id_fields[kind]], managed, evidence))
    return out


def idle(scope: Scope, inventory: Any, cpu_by_instance: dict[str, dict[str, Any]], costs: Costs,
         managed: dict[str, ManagedResource]) -> list[Finding]:
    """Instances quiet for the whole window: the mean of the daily averages under IDLE_AVERAGE_PCT and
    every daily maximum under IDLE_MAXIMUM_PCT, over at least IDLE_WINDOW_DAYS datapoints."""
    out = []
    for item in live_items(inventory, "instances"):
        rid = item["InstanceId"]
        if item.get("State", {}).get("Name") not in (None, "running"):
            continue
        series = (cpu_by_instance.get(rid) or {}).get("response", {}).get("Datapoints", [])
        points = sorted(series, key=lambda p: p["Timestamp"])[-IDLE_WINDOW_DAYS:]
        if len(points) < IDLE_WINDOW_DAYS:
            continue
        average = round(sum(p["Average"] for p in points) / len(points), 2)
        maximum = round(max(p.get("Maximum", p["Average"]) for p in points), 2)
        if average >= IDLE_AVERAGE_PCT or maximum >= IDLE_MAXIMUM_PCT:
            continue
        resource = managed.get(rid)
        cost, saving = _cost_evidence(costs, rid, IDLE_SAVING_FRACTION)
        evidence = {"instance_type": item.get("InstanceType"), "window_days": IDLE_WINDOW_DAYS, "average": average,
                    "maximum": maximum, "thresholds": {"average": IDLE_AVERAGE_PCT, "maximum": IDLE_MAXIMUM_PCT},
                    "datapoints": [{"date": p["Timestamp"][:10], "average": p["Average"], "maximum": p.get("Maximum")}
                                   for p in points],
                    "code_instance_type": resource.values.get("instance_type") if resource else None,
                    "suggested_type": _size_down(item.get("InstanceType", "")), "cost": cost}
        out.append(_finding(scope, "idle", "aws_instance", rid, managed, evidence, saving))
    return out


def stranded(scope: Scope, inventory: Any, night: datetime, costs: Costs, managed: dict[str, ManagedResource]) -> list[Finding]:
    """Unattached volumes and old snapshots, aged from the night."""
    out = []
    for item in live_items(inventory, "volumes"):
        if item.get("Attachments") or item.get("State") != "available":
            continue
        age = (night - _parse(item["CreateTime"])).days
        if age < UNATTACHED_MIN_DAYS:
            continue
        rid = item["VolumeId"]
        cost, saving = _cost_evidence(costs, rid, 1.0)
        evidence = {"created": item["CreateTime"], "age_days": age, "min_days": UNATTACHED_MIN_DAYS, "size": item.get("Size"),
                    "type": item.get("VolumeType"), "availability_zone": item.get("AvailabilityZone"), "state": item.get("State"),
                    "cost": cost}
        out.append(_finding(scope, "unattached_volume", "aws_ebs_volume", rid, managed, evidence, saving))
    for item in live_items(inventory, "snapshots"):
        age = (night - _parse(item["StartTime"])).days
        if age <= SNAPSHOT_MAX_AGE_DAYS:
            continue
        rid = item["SnapshotId"]
        cost, saving = _cost_evidence(costs, rid, 1.0)
        evidence = {"started": item["StartTime"], "age_days": age, "max_days": SNAPSHOT_MAX_AGE_DAYS, "volume_id": item.get("VolumeId"),
                    "volume_size": item.get("VolumeSize"), "description": item.get("Description", ""), "cost": cost}
        out.append(_finding(scope, "old_snapshot", "aws_ebs_snapshot", rid, managed, evidence, saving))
    return out


def graviton(scope: Scope, inventory: Any, costs: Costs, managed: dict[str, ManagedResource]) -> list[Finding]:
    """x86 instances of a family ADR-0050 would have on Graviton."""
    out = []
    for item in live_items(inventory, "instances"):
        instance_type = item.get("InstanceType", "")
        family, _, size = instance_type.partition(".")
        if item.get("Architecture") == "arm64" or family not in GRAVITON_FAMILIES:
            continue
        rid = item["InstanceId"]
        resource = managed.get(rid)
        cost, saving = _cost_evidence(costs, rid, GRAVITON_SAVING_FRACTION)
        evidence = {"instance_type": instance_type, "architecture": item.get("Architecture"), "family": family,
                    "suggested_family": GRAVITON_FAMILIES[family], "suggested_type": f"{GRAVITON_FAMILIES[family]}.{size}",
                    "code_instance_type": resource.values.get("instance_type") if resource else None,
                    "adr": "ADR-0050", "cost": cost}
        out.append(_finding(scope, "graviton_candidate", "aws_instance", rid, managed, evidence, saving))
    return out


def detect_waste(scope: Scope, inventory: Any, tags_by_resource: Any, standard: dict[str, Any],
                 cpu_by_instance: dict[str, dict[str, Any]], export: Any, night: datetime,
                 managed: dict[str, ManagedResource]) -> list[Finding]:
    """The four detectors over one account, sorted. `export` is the cost reader's CostExport (or a list of
    them) for the last complete billing month; `managed` is managed_by_id(state)."""
    costs = cost_index(*([export] if isinstance(export, dict) else export or []))
    return sort_findings(untagged(scope, inventory, tags_by_resource, standard, managed)
                         + idle(scope, inventory, cpu_by_instance, costs, managed)
                         + stranded(scope, inventory, night, costs, managed)
                         + graviton(scope, inventory, costs, managed))


# --- the exceptions ---------------------------------------------------------------------------------------

def _records(exceptions: Any) -> list[dict[str, Any]]:
    if isinstance(exceptions, dict):
        return list(exceptions.get("exceptions", []))
    return list(exceptions or [])


def suppress(findings: list[Finding], exceptions: Any, night: datetime) -> list[Finding]:
    """The findings with ServiceNow's approved, unexpired exceptions applied: for an untagged finding whose
    resource and tag an exception names, the tag is struck from `missing` (or `bad`) and recorded under
    `excused` with the exception's number. An exception excuses a tag, not a finding: `suppressed_by` (the
    first matching number) is set only when nothing remains after the excusing; a partly excused finding
    keeps `suppressed_by` None and is raised for what remains, with the exceptions named in `excused`, so an
    exception for one tag never hides another. Nothing is dropped."""
    today = night.date().isoformat()
    approved = [r for r in _records(exceptions)
                if r.get("state") == "approved" and r.get("expires") and str(r["expires"]) >= today]
    out = []
    for finding in findings:
        if finding.kind != "untagged":
            out.append(finding)
            continue
        matching = sorted((r for r in approved if r.get("resource_id") == finding.resource_id
                           and (not r.get("account") or r["account"] == finding.account)
                           and (r.get("tag") in finding.evidence.get("missing", []) or r.get("tag") in finding.evidence.get("bad", {}))),
                          key=lambda r: str(r.get("number")))
        if not matching:
            out.append(finding)
            continue
        evidence = dict(finding.evidence)
        excused = dict(evidence.get("excused", {}))
        missing, bad = list(evidence.get("missing", [])), dict(evidence.get("bad", {}))
        for record in matching:
            tag = record["tag"]
            excused[tag] = record["number"]
            missing = [t for t in missing if t != tag]
            bad.pop(tag, None)
        evidence.update(missing=missing, bad=bad, excused=excused)
        fully_excused = not missing and not bad
        out.append(replace(finding, evidence=evidence, suppressed_by=matching[0]["number"] if fully_excused else None))
    return out
