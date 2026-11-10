"""The membership table: rebuilt every night from Graph's transitive members, kept current by a delta.

Chapter 10 (W1-D16, W1-D17, W1-D27). Pages name groups. Security engineering's reviewed map,
groups.yaml, says which Entra group each name means, by object ID, and the sync tracks those IDs
and nothing else. A second group that copies a tracked display name, which any member can create
in a tenant with default settings, never counts. The table's rows hold the reviewed names, never
Graph's displayName.

Two jobs write the table, and both write users only: the server accepts only a user's token
(W1-D19), so a row for a device or a daemon's service principal could only ever be a way in.

- `rebuild`, every night, reads each tracked group's `transitiveMembers`. Graph returns that list
  flat, so a user in a nested group counts, while the nested group itself, a device or a service
  principal is skipped. The rebuild is also what drops a deleted account, since Graph's delta
  doesn't report a member removed by deleting the user. When Graph no longer has a tracked ID,
  the rebuild stops: the old table stays, ages, and raises an alarm, and the server grants only
  the broad groups once the table is more than 36 hours old. A group that copies a tracked name
  is reported, as is a tracked group renamed in Entra.
- `apply_delta`, every five minutes, applies Graph's group delta on the tracked IDs, whose
  `members@delta` lists the direct members added and removed (`@removed`). A user removed as a
  direct member of a tracked group stops reading within minutes. When the direct member that
  came or went is a nested group, the delta can't say which users came with it, so the job
  reads that tracked group's transitive members again, one request. A change inside a nested
  group never shows in the tracked group's delta and waits for the night. A removal can take
  away a group the user still holds through a nested one; the night's rebuild puts it back, so
  the error is a refusal, never a grant. The table records when a delta last ran, so an alarm
  can tell that the deltas stopped.

In production the table is a versioned object in S3 under its own key, written only by the sync
job's role, and the knowledge server reloads it when it changes. The lab reads stand-ins for Graph
(graph-export.json, graph-delta.json) and writes table.json, replacing the file whole so the
server never reads half of one.

Run:
  python sync.py                              # the nightly rebuild, from graph-export.json
  python sync.py --delta graph-delta.json     # a delta, applied to table.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from group_map import GROUP_MAP, GroupMap  # noqa: E402
from group_map import load as load_group_map  # noqa: E402

USER = "#microsoft.graph.user"
GROUP = "#microsoft.graph.group"


class SyncError(Exception):
    """The sync can't vouch for a new table: the old one stays, and an alarm goes off."""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rebuild(export: dict, groups: GroupMap, synced_at: str) -> tuple[dict, dict]:
    """The nightly table from the tracked groups' transitive members, users only, and what to report."""
    graph = {g["id"]: g for g in export["groups"]}
    names = {gid: name for name, gid in groups.ids.items()}
    missing = [f"{name} ({gid})" for gid, name in names.items() if gid not in graph]
    if missing:
        raise SyncError(f"tracked groups missing from Graph: {', '.join(missing)}")
    members: dict[str, set[str]] = {}
    skipped: Counter[str] = Counter()
    for gid, name in names.items():
        for member in graph[gid].get("transitiveMembers", []):
            kind = str(member.get("@odata.type", ""))
            if kind != USER:
                skipped[kind.rsplit(".", 1)[-1]] += 1
                continue
            members.setdefault(member["id"], set()).add(name)
    report = {
        "lookalikes": [f"{g['id']} is also named {g['displayName']!r} and isn't tracked"
                       for g in export["groups"] if g["id"] not in names and g.get("displayName") in groups.ids],
        "renamed": [f"{gid} is {graph[gid].get('displayName')!r} in Entra and {name!r} in the map"
                    for gid, name in names.items() if graph[gid].get("displayName") != name],
        "skipped": dict(sorted(skipped.items())),
    }
    table = {"synced_at": synced_at, "delta_applied_at": None, "groups": names,
             "broad": sorted(groups.broad), "members": _rows(members)}
    return table, report


def apply_delta(table: dict, delta: dict, applied_at: str,
                transitive: Callable[[str], list[dict]] | None = None) -> dict:
    """The table with a delta's direct-member changes on tracked groups, stamped with when it ran.

    `transitive(group_id)` reads one group's transitive members from Graph; the job calls it for
    a tracked group whose delta adds or removes a nested group.
    """
    names = table["groups"]
    members = {oid: set(held) for oid, held in table["members"].items()}
    reread: list[str] = []
    for group in delta.get("value", []):
        name = names.get(group.get("id"))
        if name is None:
            continue  # the delta query names tracked IDs only
        if "@removed" in group:
            raise SyncError(f"tracked group {name} ({group['id']}) was deleted")
        for member in group.get("members@delta", []):
            kind = member.get("@odata.type")
            if kind == GROUP:
                reread.append(group["id"])  # which users came or went with it, only Graph knows
            if kind != USER:
                continue  # devices and service principals never hold rows
            held = members.setdefault(member["id"], set())
            if "@removed" in member:
                held.discard(name)
            else:
                held.add(name)
    for gid in dict.fromkeys(reread):
        if transitive is None:
            raise SyncError(f"{names[gid]} gained or lost a nested group, and the delta can't say who came with it")
        users = {m["id"] for m in transitive(gid) if m.get("@odata.type") == USER}
        for oid in set(members) | users:
            held = members.setdefault(oid, set())
            if oid in users:
                held.add(names[gid])
            else:
                held.discard(names[gid])
    return {**table, "delta_applied_at": applied_at, "members": _rows(members)}


def _rows(members: dict[str, set[str]]) -> dict[str, list[str]]:
    return {oid: sorted(held) for oid, held in sorted(members.items()) if held}


def users(export: dict) -> dict[str, str]:
    """User principal name -> object ID for every user the export lists: the lab's personas."""
    return {m["userPrincipalName"]: m["id"] for g in export["groups"]
            for m in g.get("transitiveMembers", []) if m.get("@odata.type") == USER}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_table(table: dict, path: Path) -> None:
    """Replace the table whole: a temporary file beside it, renamed over the old one."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps(table, indent=2) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--export", type=Path, default=HERE / "graph-export.json")
    parser.add_argument("--delta", type=Path, help="apply this delta to the table instead of rebuilding it")
    parser.add_argument("--map", type=Path, default=GROUP_MAP)
    parser.add_argument("--out", type=Path, default=HERE / "table.json")
    parser.add_argument("--at", help="the time to stamp, ISO 8601 in UTC; now by default")
    args = parser.parse_args(argv)
    at = args.at or now_utc()
    try:
        offset = datetime.fromisoformat(at).utcoffset()
    except ValueError:
        offset = None
    if offset is None or offset.total_seconds() != 0:
        parser.error(f"--at {at!r} is not a time in UTC, such as 2026-10-29T02:00:00Z")
    try:
        if args.delta:
            graph = {g["id"]: g for g in read_json(args.export)["groups"]}  # Graph now, in the lab
            table = apply_delta(read_json(args.out), read_json(args.delta), at,
                                lambda gid: graph[gid].get("transitiveMembers", []))
        else:
            table, report = rebuild(read_json(args.export), load_group_map(args.map), at)
            for line in report["lookalikes"]:
                print(f"lookalike: {line}")
            for line in report["renamed"]:
                print(f"renamed: {line}")
            if report["skipped"]:
                print("skipped, not users: " + ", ".join(f"{n} {kind}" for kind, n in report["skipped"].items()))
    except SyncError as exc:
        print(f"alarm: {exc}; {args.out.name} is unchanged", file=sys.stderr)
        return 1
    write_table(table, args.out)
    print(f"{len(table['members'])} users, {len(table['groups'])} groups, synced at {table['synced_at']}"
          + (f", delta applied at {table['delta_applied_at']}" if table["delta_applied_at"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
