"""The on-call lead's levers, and the change record each one leaves.

Chapter 16, step 4 (companion #14, O-D7). Chapter 2 gives the on-call lead two emergency levers: "the on-call
lead can stop a workflow's spend by flipping its state in the gateway, without a deployment", and moving a
workflow down a rung. Either is "an emergency change authorized by the on-call lead, documented within
twenty-four hours, and reviewed at the next board meeting" (ch02:146, ch02:163). The levers:

- `kill`: the gateway half of the kill switch. The workflow's virtual key is blocked with LiteLLM's
  `/key/block`, found by its alias, so the lead never handles the key itself. LiteLLM evicts the key from
  its cache when it blocks it (fact sheet 8.1), so the next call through the key is refused; the proxy
  doesn't restart. The identity half is `identity.py pull`, run with AWS credentials (step 7).
- `reopen`: `/key/unblock`.
- `rung` and `restore-rung`: the override file `rungs.py` reads before each run, written atomically, or
  removed to go back to the manifest's rung.

Every lever appends one line to `changes.jsonl` in the state folder: the change's number, the lever, the
workflow, the state before and after, who authorized it and on what authority, when, the time by which it
must be documented (24 hours on), the review it goes to, the reason, and what the gateway answered. The
line is the start of the emergency change's record, not the whole of it: the 24-hour write-up and the
board's review follow it.

Run (from labs/ch16; LITELLM_MASTER_KEY and --gateway for the gateway levers):
    python budget/oncall.py kill w2-ops-assistant --by oncall.lead@larkspur.example --change EC-1 --reason "..."
    python budget/oncall.py reopen w2-ops-assistant --by ... --change EC-1 --reason "..."
    python budget/oncall.py rung w3-incident 1 --by ... --change EC-2 --reason "..."
    python budget/oncall.py restore-rung w3-incident --by ... --change EC-2 --reason "..."
State folder: BUDGET_STATE_DIR, default budget/_lab/state (git-ignored).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rungs  # noqa: E402
from keys import Admin  # noqa: E402

DOCUMENT_WITHIN = timedelta(hours=24)  # ch02:163
REVIEW = "the next board meeting"


def state_dir() -> Path:
    return Path(os.environ.get("BUDGET_STATE_DIR") or HERE / "_lab" / "state")


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def change_record(*, change: str, lever: str, workflow: str, before: Any, after: Any, by: str, at: datetime,
                  reason: str, answer: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One line of the emergency-change log (ch02:163)."""
    return {"change": change, "kind": "emergency", "lever": lever, "workflow": workflow, "from": before,
            "to": after, "by": by, "authority": "on-call lead", "at": iso(at),
            "document_by": iso(at + DOCUMENT_WITHIN), "review": REVIEW, "reason": reason,
            "answer": dict(answer or {})}


def append_record(folder: Path, line: Mapping[str, Any]) -> Path:
    path = Path(folder) / "changes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(line) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _gate(admin: Admin, workflow: str, block: bool, *, by: str, change: str, reason: str, folder: Path,
          now: datetime | None) -> dict[str, Any]:
    token = admin.token_for(workflow)
    before = "blocked" if admin.info(token).get("blocked") else "open"
    at = now or datetime.now(timezone.utc)
    started = time.perf_counter()
    answer = admin.block(token) if block else admin.unblock(token)
    seconds = round(time.perf_counter() - started, 3)
    line = change_record(change=change, lever="kill switch, gateway half" if block else "kill switch released",
                         workflow=workflow, before=before, after="blocked" if block else "open", by=by, at=at,
                         reason=reason, answer={"blocked": answer.get("blocked"), "seconds": seconds})
    append_record(folder, line)
    return line


def kill(admin: Admin, workflow: str, *, by: str, change: str, reason: str, folder: Path | None = None,
         now: datetime | None = None) -> dict[str, Any]:
    """Block the workflow's key at the gateway; every call through it is refused from the next one on."""
    return _gate(admin, workflow, True, by=by, change=change, reason=reason, folder=folder or state_dir(), now=now)


def reopen(admin: Admin, workflow: str, *, by: str, change: str, reason: str, folder: Path | None = None,
           now: datetime | None = None) -> dict[str, Any]:
    return _gate(admin, workflow, False, by=by, change=change, reason=reason, folder=folder or state_dir(), now=now)


def lower_rung(workflow: str, rung: int | None, *, manifest_rung: int, by: str, change: str, reason: str,
               folder: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Write the rung override (or remove it, with rung None); the next run reads it."""
    folder = folder or state_dir()
    overrides = folder / "rungs"
    at = now or datetime.now(timezone.utc)
    try:
        current = rungs.read_override(overrides, workflow)
        before = current["rung"] if current else f"manifest ({manifest_rung})"
    except rungs.RungOverrideError:
        before = "unreadable"
    if rung is None:
        rungs.override_path(overrides, workflow).unlink(missing_ok=True)
        after: Any = f"manifest ({manifest_rung})"
    else:
        if rung >= manifest_rung:
            raise ValueError(f"rung {rung} is not below the manifest's {manifest_rung}; an override only lowers")
        rungs.write_override(overrides, workflow, rung, by=by, at=iso(at), change=change, reason=reason)
        after = rung
    line = change_record(change=change, lever="rung down" if rung is not None else "rung restored",
                         workflow=workflow, before=before, after=after, by=by, at=at, reason=reason)
    append_record(folder, line)
    return line


def main(argv: list[str] | None = None) -> int:
    import yaml

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("kill", "reopen", "rung", "restore-rung"))
    parser.add_argument("workflow")
    parser.add_argument("rung", nargs="?", type=int, help="for `rung`: the rung to lower the workflow to")
    parser.add_argument("--by", required=True, help="the on-call lead who authorizes the change")
    parser.add_argument("--change", required=True, help="the emergency change's number")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--gateway", default=os.environ.get("BUDGET_GATEWAY_URL", "http://127.0.0.1:4010"))
    parser.add_argument("--manifest-dir", type=Path, default=HERE.parents[1] / "ch05" / "manifest")
    parser.add_argument("--state", type=Path, default=None, help="the state folder (BUDGET_STATE_DIR)")
    args = parser.parse_args(argv)
    folder = args.state or state_dir()
    if args.action in ("kill", "reopen"):
        admin = Admin(args.gateway, os.environ["LITELLM_MASTER_KEY"])
        lever = kill if args.action == "kill" else reopen
        line = lever(admin, args.workflow, by=args.by, change=args.change, reason=args.reason, folder=folder)
    else:
        manifest = yaml.safe_load((args.manifest_dir / f"{args.workflow}.yaml").read_text(encoding="utf-8"))
        if args.action == "rung" and args.rung is None:
            parser.error("rung needs the rung to lower to")
        line = lower_rung(args.workflow, args.rung if args.action == "rung" else None,
                          manifest_rung=int(manifest["rung"]), by=args.by, change=args.change, reason=args.reason,
                          folder=folder)
    print(json.dumps(line, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
