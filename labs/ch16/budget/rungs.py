"""The rung-down switch: an override file the on-call lead edits, read by the harness before each run.

Chapter 16, step 4 (companion #14, O-D7). Chapter 1 says climbing down "has to be as easy as flipping a
configuration value" (ch01:221), and chapter 2 makes moving a workflow down a rung an emergency change the
on-call lead authorizes (ch02:163). The value is one small file per workflow, `<workflow>.yaml` in the
overrides folder:

    workflow: w3-incident
    rung: 1
    by: oncall.lead@larkspur.example
    at: "2026-11-03T23:40:00+00:00"
    change: EC-20261103-01
    reason: a planted line restated in two incidents; reads only until the review

The harness reads it at the start of each run, before the first model call, and the rules are these:

- No file: the manifest's rung.
- A file that names this workflow and an integer rung from 0 to 5: the lower of the two. An override at or
  above the manifest's rung changes nothing, so the file can lower a rung and never raise one; the run's
  plan says it was ignored.
- Anything else fails closed and the run doesn't start: YAML that doesn't parse, a file that isn't a mapping,
  another workflow's name, a rung that isn't an integer from 0 to 5 (a quoted "1" or `true` included), a key
  the harness doesn't know, or a field that isn't text. A file the harness can't fully read is a file whose
  intent it can't know.

Below the manifest's rung, every tool the manifest marks `writes: true` leaves the allowlist and the tools the
model is offered. The manifest marks writes and nothing finer, so the harness can't tell W4's ticket from
W3's restart: a workflow lowered by any step loses every write. Rungs 0 and 1 differ in what they read (a
curated corpus, or live systems), which the manifest doesn't say either; that difference stays with the
workflow's tool servers and identities.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

KNOWN = {"workflow", "rung", "by", "at", "change", "reason"}
TEXT = ("by", "at", "change", "reason")


class RungOverrideError(ValueError):
    """An override file the harness can't fully read: the run doesn't start."""


@dataclass(frozen=True)
class Plan:
    """What a run may do, decided before its first call."""

    workflow: str
    manifest_rung: int
    rung: int
    allowed: dict[str, set[str]]           # tool -> argument names, the shape chapter 1's loop takes
    dropped: tuple[str, ...] = ()          # write tools removed by a lowered rung
    override: dict[str, Any] | None = None
    note: str = ""
    record: dict[str, Any] = field(default_factory=dict)


def override_path(folder: Path, workflow: str) -> Path:
    return Path(folder) / f"{workflow}.yaml"


def read_override(folder: Path, workflow: str) -> dict[str, Any] | None:
    """The override for this workflow, None when there is none; RungOverrideError when it can't be read."""
    path = override_path(folder, workflow)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise RungOverrideError(f"{path.name}: unreadable ({type(exc).__name__})") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RungOverrideError(f"{path.name}: not YAML ({exc.__class__.__name__})") from exc
    if not isinstance(data, Mapping):
        raise RungOverrideError(f"{path.name}: not a mapping")
    unknown = sorted(set(map(str, data)) - KNOWN)
    if unknown:
        raise RungOverrideError(f"{path.name}: unknown key {unknown[0]!r}")
    if data.get("workflow") != workflow:
        raise RungOverrideError(f"{path.name}: names workflow {data.get('workflow')!r}, not {workflow!r}")
    rung = data.get("rung")
    if isinstance(rung, bool) or not isinstance(rung, int) or not 0 <= rung <= 5:
        raise RungOverrideError(f"{path.name}: rung {rung!r} is not an integer from 0 to 5")
    for key in TEXT:
        if key in data and not isinstance(data[key], str):
            raise RungOverrideError(f"{path.name}: {key} is not text")
    return dict(data)


def plan(manifest: Mapping[str, Any], folder: Path) -> Plan:
    """The run's rung and allowlist, from the manifest and the override. Raises RungOverrideError."""
    workflow, manifest_rung = manifest["workflow"], int(manifest["rung"])
    override = read_override(folder, workflow)
    tools = manifest["tools"]
    everything = {name: set(spec["args"]) for name, spec in tools.items()}
    if override is None:
        return Plan(workflow, manifest_rung, manifest_rung, everything, note="no override")
    if override["rung"] >= manifest_rung:
        return Plan(workflow, manifest_rung, manifest_rung, everything, override=override,
                    note=f"override rung {override['rung']} ignored: an override only lowers the manifest's "
                         f"rung {manifest_rung}")
    writes = tuple(sorted(name for name, spec in tools.items() if spec.get("writes")))
    allowed = {name: args for name, args in everything.items() if name not in writes}
    return Plan(workflow, manifest_rung, override["rung"], allowed, dropped=writes, override=override,
                note=f"lowered from rung {manifest_rung} to {override['rung']}")


def write_override(folder: Path, workflow: str, rung: int, *, by: str, at: str, change: str,
                   reason: str) -> Path:
    """Write the override atomically, so a harness never reads half a file."""
    from record import atomic_write

    body = {"workflow": workflow, "rung": rung, "by": by, "at": at, "change": change, "reason": reason}
    path = override_path(folder, workflow)
    atomic_write(path, yaml.safe_dump(body, sort_keys=False))
    return path
