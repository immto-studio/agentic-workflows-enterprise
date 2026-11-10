"""The ledger: W5's only state, a row per finding key and a row per night, in one JSON file.

Chapter 14, W5-D9, W5-D10, W5-D14. A night is short and idempotent, so W5 keeps no store of runs
(W5-D2); what it keeps is this: for every finding key, when it was first and last seen, the pull request
it has (number and state: open, merged, closed), the estimated monthly saving, and the realized saving,
set when a later night finds the resource or the waste gone after the pull request was merged; and for
every night, the agent's own cost: the gateway's calls and token counts for the night's trace id, read
from the gateway log the night wrote (chapter 5's hooks, W4's gateway.jsonl shape), and the night's
duration, with the account spend the night read so the savings can be given as shares.

`summary(month)` is what the chapter's "agent cost against savings" section and chapter 16's monthly
review read: the savings proposed and realized as shares of the accounts' spend and of each other, the
pull requests by state, the findings by kind, and the agent's cost as counts; never an amount, never a
currency (W5-D10). The file is `LEDGER_FILE` in the lab (W4's store shape, an atomic replace). Deployed, it
is a file on a branch of W5's own fork, written by the fork App, so every change to it is a commit, and the
owning team, which can push to the fork, can correct a row the same way.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
for folder in (HERE, W5 / "detect"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from findings import Finding  # noqa: E402
from github_fake import UPSTREAM, GitHubError, GitHubFake  # noqa: E402
from pull_requests import WriteResult  # noqa: E402

__all__ = ["Ledger", "cost_from_gateway_log", "STATES"]

STATES = ("open", "merged", "closed")


def cost_from_gateway_log(path: Path | None, trace_id: str) -> dict[str, int]:
    """The gateway's calls for one trace id, counted from the log chapter 5's hooks write (one JSON line
    per call with prompt_tokens and completion_tokens; `refused` and `failed` lines beside them)."""
    out = {"gateway_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "refused": 0, "failed": 0}
    if path is None or not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("trace_id") != trace_id:
            continue
        event = record.get("event")
        if event == "call":
            out["gateway_calls"] += 1
            out["prompt_tokens"] += int(record.get("prompt_tokens") or 0)
            out["completion_tokens"] += int(record.get("completion_tokens") or 0)
        elif event in ("refused", "failed"):
            out[event] += 1
    return out


def _day(night: datetime) -> str:
    return night.date().isoformat()


class Ledger:
    def __init__(self, path: Path | None = None) -> None:
        given = path or Path(os.environ.get("LEDGER_FILE", "").strip() or "")
        if not str(given):
            raise RuntimeError("LEDGER_FILE is not set")
        self.path = given
        self.data: dict[str, Any] = {"findings": {}, "nights": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    # --- the rows -------------------------------------------------------------------------------------------------

    @property
    def findings(self) -> dict[str, dict[str, Any]]:
        return self.data["findings"]

    @property
    def nights(self) -> dict[str, dict[str, Any]]:
        return self.data["nights"]

    def observe(self, findings: list[Finding], night: datetime) -> None:
        """Every finding of the night: a new row, or the row's last_seen, saving, and suppression refreshed."""
        for finding in findings:
            row = self.findings.setdefault(finding.key, {
                "key": finding.key, "kind": finding.kind, "workspace": finding.workspace, "account": finding.account,
                "resource_type": finding.resource_type, "resource_id": finding.resource_id, "address": finding.address,
                "first_seen": _day(night), "last_seen": _day(night), "pull_request": None,
                "estimated_monthly_saving": None, "realized_monthly_saving": None, "realized_on": None, "suppressed_by": None,
            })
            row["last_seen"] = _day(night)
            row["estimated_monthly_saving"] = finding.estimated_monthly_saving
            row["suppressed_by"] = finding.suppressed_by
            row["template"] = finding.template

    def record_writes(self, results: list[WriteResult], night: datetime) -> None:
        for result in results:
            row = self.findings.get(result.key)
            if row is None or result.number is None:
                continue
            pr = row.get("pull_request") or {}
            if result.action == "skipped":
                if not pr:  # a pull request the ledger never saw (the store was new): its state comes from the skip's reason,
                    # open when an approval kept its prose, else merged or closed inside its thirty days
                    state = "open" if " approved by " in result.reason else "merged" if "merged" in result.reason else "closed"
                    pr = {"repo": result.repo, "number": result.number, "branch": result.branch,
                          "state": state, "opened": None, "updated": None, "closed": None, "merged": None}
            elif result.action == "opened" or pr.get("number") != result.number:
                pr = {"repo": result.repo, "number": result.number, "branch": result.branch, "state": "open",
                      "opened": _day(night), "updated": _day(night), "closed": None, "merged": None}
            elif result.action == "updated":
                pr["updated"] = _day(night)
            row["pull_request"] = pr
            row["last_write"] = {**asdict(result), "refused_words": list(result.refused_words), "night": _day(night)}

    def sync_pull_requests(self, github: GitHubFake, token: str) -> dict[str, str]:
        """Each row's pull request as GitHub has it now: open, merged, or closed, with its dates."""
        states: dict[str, str] = {}
        for key, row in self.findings.items():
            pr = row.get("pull_request")
            if not pr:
                continue
            try:
                live = github.get_pull(token, pr.get("repo", UPSTREAM), pr["number"])
            except GitHubError:
                continue
            if live.get("merged"):
                pr["state"], pr["merged"] = "merged", (live.get("merged_at") or "")[:10]
            elif live["state"] == "closed":
                pr["state"], pr["closed"] = "closed", (live.get("closed_at") or "")[:10]
            else:
                pr["state"] = "open"
            states[key] = pr["state"]
        return states

    def realize(self, found: set[str], night: datetime, workspaces: list[str]) -> list[str]:
        """The rows whose pull request was merged and whose key the night, over its workspaces, did not find
        again: the estimated saving is realized tonight. Returns their keys."""
        realized = []
        for key, row in self.findings.items():
            pr = row.get("pull_request") or {}
            if pr.get("state") != "merged" or row.get("realized_on") or row["workspace"] not in workspaces:
                continue
            if key in found:
                continue
            row["realized_monthly_saving"] = row.get("estimated_monthly_saving")
            row["realized_on"] = _day(night)
            realized.append(key)
        return realized

    def record_night(self, night: datetime, *, trace_id: str, duration_s: float, gateway_log: Path | None,
                     findings: list[Finding], results: list[WriteResult], spend: dict[str, float],
                     workspaces: list[str], trigger: dict[str, Any] | None = None, realized: list[str] | None = None) -> dict[str, Any]:
        """The night's own row: its cost from the gateway log, what it found and wrote, the spend it read."""
        actions = Counter(r.action for r in results)
        row = {
            "night": _day(night), "trace_id": trace_id, "trigger": trigger or {"kind": "schedule"}, "workspaces": list(workspaces),
            "duration_s": round(duration_s, 3), **cost_from_gateway_log(gateway_log, trace_id),
            "findings": len(findings), "by_kind": dict(Counter(f.kind for f in findings)),
            "pull_requests": {a: actions.get(a, 0) for a in ("opened", "updated", "skipped", "suppressed")},
            "body_sources": dict(Counter(r.body_source for r in results if r.body_source)),
            "refused_words": {r.key: list(r.refused_words) for r in results if r.refused_words},
            "realized": list(realized or []), "spend": {k: round(v, 4) for k, v in spend.items()},
        }
        # One row per run: a scheduled night under its day, an alarm's run under its day, its kind, and its
        # account, so an alarm that fires on a day a night already ran does not replace that night's row.
        kind = (trigger or {}).get("kind", "schedule")
        self.nights[_day(night) if kind == "schedule" else f"{_day(night)}:{kind}:{(trigger or {}).get('account')}"] = row
        return row

    # --- the month ------------------------------------------------------------------------------------------------

    def summary(self, month: str) -> dict[str, Any]:
        """Shares and counts for one month (YYYY-MM): never an amount."""
        nights = [n for d, n in sorted(self.nights.items()) if d.startswith(month)]
        rows = [r for r in self.findings.values() if (r.get("last_seen") or "").startswith(month)]
        with_pr = [r for r in rows if r.get("pull_request")]
        spend_by_account: dict[str, float] = {}
        for night in nights:  # the latest night's reading per account: every night reads the same billing month
            spend_by_account.update(night.get("spend", {}))
        spend = sum(spend_by_account.values())
        proposed = sum(r.get("estimated_monthly_saving") or 0.0 for r in with_pr)
        realized = sum(r.get("realized_monthly_saving") or 0.0 for r in self.findings.values()
                       if (r.get("realized_on") or "").startswith(month))

        def share(part: float, whole: float) -> float | None:
            return round(part / whole, 4) if whole else None

        return {
            "month": month,
            "nights": len(nights),
            "findings": {"seen": len(rows), "by_kind": dict(Counter(r["kind"] for r in rows)),
                         "suppressed": sum(1 for r in rows if r.get("suppressed_by")),
                         "with_estimate": sum(1 for r in with_pr if r.get("estimated_monthly_saving") is not None)},
            "pull_requests": {**{s: sum(1 for r in with_pr if r["pull_request"].get("state") == s) for s in STATES},
                              "opened": sum(n["pull_requests"].get("opened", 0) for n in nights),
                              "updated": sum(n["pull_requests"].get("updated", 0) for n in nights),
                              "skipped": sum(n["pull_requests"].get("skipped", 0) for n in nights)},
            "savings": {"proposed_share_of_spend": share(proposed, spend), "realized_share_of_spend": share(realized, spend),
                        "realized_share_of_proposed": share(realized, proposed),
                        "realized_findings": sum(1 for r in self.findings.values() if (r.get("realized_on") or "").startswith(month))},
            "agent": {"gateway_calls": sum(n.get("gateway_calls", 0) for n in nights),
                      "prompt_tokens": sum(n.get("prompt_tokens", 0) for n in nights),
                      "completion_tokens": sum(n.get("completion_tokens", 0) for n in nights),
                      "refused": sum(n.get("refused", 0) for n in nights), "failed": sum(n.get("failed", 0) for n in nights),
                      "seconds": round(sum(n.get("duration_s", 0.0) for n in nights), 3),
                      "accounts_read": sorted(spend_by_account)},
        }

    # --- the store ------------------------------------------------------------------------------------------------

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=self.path.name, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=1, sort_keys=True)
        os.replace(tmp, self.path)
