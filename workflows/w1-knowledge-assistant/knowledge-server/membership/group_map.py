"""Security engineering's reviewed map from group names to Entra object IDs, as code reads it.

Chapter 10 (W1-D17). Pages name groups, and a name is only as good as the group it points to.
groups.yaml says which group each name means, by object ID, and which groups are broad. The
ingestion gate reads the names (a page may name nothing else), the sync reads the IDs (it tracks
nothing else), and the broad groups are what a stale membership table still grants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
GROUP_MAP = HERE / "groups.yaml"
OBJECT_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass(frozen=True)
class GroupMap:
    ids: dict[str, str]  # the name pages use -> the group's object ID
    broad: frozenset[str]  # names nearly everyone holds

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self.ids)


def load(path: Path = GROUP_MAP) -> GroupMap:
    """The map, checked: every ID a GUID, no ID under two names."""
    groups = yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]
    ids = {str(name): str(entry["id"]).lower() for name, entry in groups.items()}
    bad = sorted(name for name, gid in ids.items() if not OBJECT_ID.match(gid))
    if bad:
        raise ValueError(f"{path.name}: not an object ID for {bad}")
    if len(set(ids.values())) != len(ids):
        raise ValueError(f"{path.name}: one object ID under two names")
    broad = frozenset(name for name, entry in groups.items() if entry.get("broad"))
    return GroupMap(ids, broad)
