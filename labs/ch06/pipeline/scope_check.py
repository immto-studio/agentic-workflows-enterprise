"""Refuse a manifest or catalog change that grows a workflow's scope without a change record.

Chapter 6, keeping chapter 4's promise. terraform/modules/manifest_roles turns a manifest and the
tool catalog into roles and Cedar permits; this check runs before it, on every change to either
file, against the version on the main branch:

  git show origin/main:labs/ch06/manifests/w3-incident.yaml > base-manifest.yaml
  git show origin/main:labs/ch06/catalog/tools.yaml > base-catalog.yaml
  python pipeline/scope_check.py --base-manifest base-manifest.yaml --manifest manifests/w3-incident.yaml \
      --base-catalog base-catalog.yaml --catalog catalog/tools.yaml --change-record "$CHANGE_RECORD"

Growth is anything that lets the workflow reach more: a tool, an argument, a write, a model
alias, a Region, a higher data class or autonomy rung, prompts in spans, a larger budget, a value
added to an allow list or the list removed, a never-list entry dropped, and, for the tools the
manifest lists, any AWS action, resource or Kubernetes access the catalog adds. A new workflow is
all growth. Narrowing needs no record and is listed anyway.

The change record comes from --change-record or CHANGE_RECORD, in the form CHG-1234. Exit status:
0 when nothing grew, or it grew under a change record; 1 when it grew without one; 2 when an input
is not a valid manifest or catalog.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB.parent / "ch05" / "manifest"))

import manifest as manifests  # noqa: E402  chapter 5's schema and loader

CHANGE_RECORD = re.compile(r"^CHG-[0-9]{4,}$")


class CatalogError(ValueError):
    """A catalog without the shape terraform/modules/manifest_roles reads."""


def load_catalog(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(data.get(k), dict) for k in ("servers", "tools", "never")):
        raise CatalogError(f"{path.name}: a catalog has servers, tools and never")
    for name, tool in data["tools"].items():
        if tool.get("server") not in data["servers"]:
            raise CatalogError(f"{path.name}: {name} names server {tool.get('server')!r}, which isn't listed")
    return data


def _grants(catalog: Mapping[str, Any] | None, tool: str) -> set[str]:
    """`action on resource` for every pair the catalog gives the tool's role, as written (unrendered)."""
    entry = (catalog or {}).get("tools", {}).get(tool) or {}
    return {f"{action} on {resource}" for statement in entry.get("aws") or []
            for action in statement["actions"] for resource in statement["resources"]}


def _kubernetes(catalog: Mapping[str, Any] | None, tool: str) -> set[str]:
    access = ((catalog or {}).get("tools", {}).get(tool) or {}).get("eks_access") or {}
    return ({f"access policy {access['policy']}"} if access.get("policy") else set()) \
        | {f"namespace {ns}" for ns in access.get("namespaces") or []} \
        | {f"group {group}" for group in access.get("groups") or []}


def _server(catalog: Mapping[str, Any] | None, tool: str) -> tuple[str | None, str | None]:
    entry = (catalog or {}).get("tools", {}).get(tool) or {}
    server = entry.get("server")
    return server, ((catalog or {}).get("servers", {}).get(server) or {}).get("principal")


def compare(base: Mapping[str, Any] | None, head: Mapping[str, Any],
            base_catalog: Mapping[str, Any] | None, catalog: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(grown, narrowed): one line for each way the head reaches more, or less, than the base."""
    grown: list[str] = []
    narrowed: list[str] = []
    if base is None:
        grown.append(f"new workflow {head['workflow']}")
        base = {"tools": {}, "models": [], "regions": [], "never": [], "rung": 0, "data_class_max": "public",
                "trace_content": False, "budget": {}}

    def sets(label: str, before: Iterable[str], after: Iterable[str]) -> None:
        before, after = set(before), set(after)
        if after - before:
            grown.append(f"{label} added: {', '.join(sorted(after - before))}")
        if before - after:
            narrowed.append(f"{label} removed: {', '.join(sorted(before - after))}")

    def raised(label: str, before: float, after: float) -> None:
        if after > before:
            grown.append(f"{label} raised from {before} to {after}")
        elif after < before:
            narrowed.append(f"{label} lowered from {before} to {after}")

    if manifests.rank(head["data_class_max"]) > manifests.rank(base["data_class_max"]):
        grown.append(f"data class raised from {base['data_class_max']} to {head['data_class_max']}")
    elif manifests.rank(head["data_class_max"]) < manifests.rank(base["data_class_max"]):
        narrowed.append(f"data class lowered from {base['data_class_max']} to {head['data_class_max']}")
    raised("rung", base["rung"], head["rung"])
    sets("model aliases", base["models"], head["models"])
    sets("regions", base["regions"], head["regions"])
    if head["trace_content"] and not base["trace_content"]:
        grown.append("prompts and outputs now go into spans (trace_content)")
    for limit in ("per_run_usd", "per_month_usd", "requests_per_minute"):
        if limit in head["budget"]:
            raised(f"budget {limit}", base["budget"].get(limit, 0), head["budget"][limit])

    # The never-list: an entry dropped, or a deny the catalog no longer maps it to, is growth.
    dropped, added = set(base["never"]) - set(head["never"]), set(head["never"]) - set(base["never"])
    if dropped:
        grown.append(f"never-list entries dropped: {', '.join(sorted(dropped))}")
    if added:
        narrowed.append(f"never-list entries added: {', '.join(sorted(added))}")
    for item in head["never"]:
        before = set((base_catalog or {}).get("never", {}).get(item) or [])
        after = set(catalog["never"].get(item) or [])
        if before - after:
            grown.append(f"never-list {item}: deny dropped for {', '.join(sorted(before - after))}")

    before_tools, after_tools = base["tools"], head["tools"]
    for tool in sorted(set(before_tools) - set(after_tools)):
        narrowed.append(f"tool removed: {tool}")
    for tool, spec in sorted(after_tools.items()):
        old = before_tools.get(tool)
        if old is None:
            grown.append(f"tool added: {tool}{' (writes)' if spec.get('writes') else ''}")
            old_catalog = None  # every grant of a new tool is new
        else:
            old_catalog = base_catalog
            if spec.get("writes") and not old.get("writes"):
                grown.append(f"{tool} now writes")
            sets(f"{tool} arguments", old["args"], spec["args"])
            for arg in sorted(set(old.get("allow", {})) | set(spec.get("allow", {}))):
                was, now = old.get("allow", {}).get(arg), spec.get("allow", {}).get(arg)
                if was is not None and now is None:
                    grown.append(f"{tool}: allow list on {arg} removed")
                elif was is None and now is not None:
                    narrowed.append(f"{tool}: {arg} only {', '.join(now)}")
                else:
                    sets(f"{tool}: allowed {arg} values", was, now)
        if old is not None and _server(old_catalog, tool) != _server(catalog, tool):
            grown.append(f"{tool}: server or its principal changed to {_server(catalog, tool)[0]}")
        # One line per grant, so a reviewer reads each one.
        for label, before, after in (("IAM", _grants(old_catalog, tool), _grants(catalog, tool)),
                                     ("Kubernetes", _kubernetes(old_catalog, tool), _kubernetes(catalog, tool))):
            grown.extend(f"{tool}: {label} {item}" for item in sorted(after - before))
            narrowed.extend(f"{tool}: {label} removed: {item}" for item in sorted(before - after))
    return grown, narrowed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, help="the main branch's version; omit for a new workflow")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--base-catalog", type=Path, help="the main branch's version; required with --base-manifest")
    parser.add_argument("--change-record", default=os.environ.get("CHANGE_RECORD", ""))
    args = parser.parse_args(argv)
    try:
        head = manifests.load_manifest(args.manifest)
        base = manifests.load_manifest(args.base_manifest) if args.base_manifest else None
        catalog = load_catalog(args.catalog)
        base_catalog = load_catalog(args.base_catalog) if args.base_catalog else catalog
    except (manifests.ManifestError, CatalogError, OSError, yaml.YAMLError) as exc:
        print(f"scope check: {exc}", file=sys.stderr)
        return 2
    if args.base_manifest and not args.base_catalog:
        # Without the base catalog the catalog would be compared with itself, and a grant it adds
        # would pass unseen.
        print("scope check: --base-catalog is required with --base-manifest", file=sys.stderr)
        return 2
    if base is not None and base["workflow"] != head["workflow"]:
        print(f"scope check: the base is {base['workflow']!r} and the head {head['workflow']!r}", file=sys.stderr)
        return 2
    grown, narrowed = compare(base, head, base_catalog, catalog)
    for line in grown:
        print(f"grown: {line}")
    for line in narrowed:
        print(f"narrowed: {line}")
    record = args.change_record.strip()
    if not grown:
        print(f"scope check: {head['workflow']} reaches no further than before")
        return 0
    if CHANGE_RECORD.match(record):
        print(f"scope check: {len(grown)} grown scope(s) for {head['workflow']}, under {record}")
        return 0
    reason = f"{record!r} is not a change record (CHG-1234)" if record else "no change record"
    sys.stdout.flush()  # the lines above come first in the pipeline's log
    print(f"scope check: refused: {len(grown)} grown scope(s) for {head['workflow']}, {reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
