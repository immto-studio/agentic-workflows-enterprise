"""The alias remap and its change record (chapter 16, step 8, O-D14): the gateway's alias moved to the candidate
(a promotion) or back to the model it served before, written whole, with one line in the change log as step 4's
switches leave one (budget/oncall.py).

A promotion rewrites one alias's deployments in a LiteLLM configuration and leaves every other alias as it was; a
remap back writes the previous configuration whole, so what the proxy starts from is the file it started from
before. The new configuration is written atomically (step 4's `record.atomic_write`), so a proxy that starts from it
never reads half a file; the proxy itself reads its configuration at start, so the remap takes effect at the next
start, which is how chapter 5's gateway is run (the lab deploys no second proxy to roll). The record names the change, its
kind (a planned change for a promotion, an emergency change for a remap back pulled from the playbook, O-D13), the
alias, the deployments before and after by id and identifier, who authorized it and on what authority, when, the
time by which it must be documented (ch02:163), the review it goes to, the reason, and the evidence files.

Run (from labs/ch16):
  python lifecycle/remap.py promote --config lifecycle/litellm.current.yaml --candidate lifecycle/litellm.staging.yaml \
      --out <folder> --change CH-1 --by platform.team@larkspur.example --reason "..."
  python lifecycle/remap.py back --config <the promoted config> --previous lifecycle/litellm.current.yaml --out <folder> ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "budget", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
from record import atomic_write  # noqa: E402

ALIAS = "larkspur-chat"
DOCUMENT_WITHIN = timedelta(hours=24)  # ch02:163
REVIEW = "the next board meeting"
KINDS = {"promote": ("planned", "the platform team, on the gate's and the canary's evidence"),
         "back": ("emergency", "on-call lead")}
LEVERS = {"promote": "alias remap, promotion", "back": "alias remap, back"}


def load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def alias_entries(config: dict[str, Any], alias: str = ALIAS) -> list[dict[str, Any]]:
    return [e for e in config["model_list"] if e["model_name"] == alias]


def describe(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An alias's deployments as the record names them: id, identifier, weight where one is set."""
    out = []
    for e in entries:
        params = e["litellm_params"]
        item = {"id": e["model_info"]["id"], "model": params["model"]}
        if "weight" in params:
            item["weight"] = params["weight"]
        out.append(item)
    return out


def remapped(config: dict[str, Any], alias: str, deployments: list[dict[str, Any]]) -> dict[str, Any]:
    """The configuration with the alias's deployments replaced and everything else kept, in place."""
    out = {k: v for k, v in config.items()}
    kept = [e for e in config["model_list"] if e["model_name"] != alias]
    first = next((i for i, e in enumerate(config["model_list"]) if e["model_name"] == alias), len(kept))
    new = [dict(e) | {"model_name": alias} for e in deployments]
    out["model_list"] = kept[:first] + new + kept[first:]
    return out


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def change_record(*, change: str, action: str, alias: str, before: list[dict[str, Any]], after: list[dict[str, Any]],
                  by: str, at: datetime, reason: str, evidence: list[str], config_before: str, config_after: str,
                  tenants: list[str]) -> dict[str, Any]:
    kind, authority = KINDS[action]
    return {"change": change, "kind": kind, "lever": LEVERS[action], "alias": alias, "workflows": tenants,
            "from": before, "to": after, "by": by, "authority": authority, "at": iso(at),
            "document_by": iso(at + DOCUMENT_WITHIN), "review": REVIEW, "reason": reason,
            "config_before": config_before, "config_after": config_after, "evidence": evidence,
            "takes_effect": "at the proxy's next start, which reads the configuration once"}


def append_record(folder: Path, line: dict[str, Any]) -> Path:
    path = Path(folder) / "changes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(line) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def tenants_of(alias: str, root: Path) -> list[str]:
    """The workflows whose manifests name the alias."""
    out = []
    for path in sorted((root / "workflows").glob("*/manifest/*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if alias in (data.get("models") or []):
            out.append(data["workflow"])
    return out


def remap(action: str, config: Path, source: Path, out: Path, *, change: str, by: str, reason: str,
          evidence: list[str], alias: str = ALIAS, now: datetime | None = None, header: str = "",
          names_as: tuple[str, str] | None = None) -> tuple[Path, dict[str, Any]]:
    """`promote`: the alias takes the deployments `source` gives it, and the rest of `config` stays; `back`: `source`
    is the configuration before the promotion, written whole. The new configuration is written to `out`, the record
    appended beside it. Returns the configuration's path and the record."""
    if action not in KINDS:
        raise ValueError(f"action {action!r} is promote or back")
    current, wanted = load(config), load(source)
    deployments = alias_entries(wanted, alias)
    if not deployments:
        raise ValueError(f"{source.name} has no deployment for {alias}")
    before, after = describe(alias_entries(current, alias)), describe(deployments)
    if before == after:
        raise ValueError(f"{config.name} already serves {alias} from {after}")
    new = wanted if action == "back" else remapped(current, alias, deployments)
    text = (header.rstrip("\n") + "\n" if header else "") + yaml.safe_dump(new, sort_keys=False, width=110)
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(out, text)
    root = LAB.parents[1]
    config_name, out_name = names_as or (config.name, out.name)
    record = change_record(change=change, action=action, alias=alias, before=before, after=after, by=by,
                           at=now or datetime.now(timezone.utc), reason=reason, evidence=evidence,
                           config_before=config_name, config_after=out_name, tenants=tenants_of(alias, root))
    append_record(out.parent, record)
    return out, record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=sorted(KINDS))
    parser.add_argument("--config", type=Path, required=True, help="the configuration the alias is remapped in")
    parser.add_argument("--candidate", type=Path, help="promote: the configuration that holds the candidate's deployment")
    parser.add_argument("--previous", type=Path, help="back: the configuration the alias served before")
    parser.add_argument("--out", type=Path, required=True, help="the new configuration's path; changes.jsonl goes beside it")
    parser.add_argument("--change", required=True)
    parser.add_argument("--by", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--evidence", nargs="*", default=[])
    args = parser.parse_args(argv)
    source = args.candidate if args.action == "promote" else args.previous
    if source is None:
        parser.error("promote needs --candidate; back needs --previous")
    path, record = remap(args.action, args.config, source, args.out, change=args.change, by=args.by,
                         reason=args.reason, evidence=args.evidence)
    print(f"wrote {path}; {record['lever']}: {record['from']} -> {record['to']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
