"""The retirement alert (chapter 16, step 8, O-D14): the 90-day rule of chapters 7 and 8, O-D15's 180-day review
window, and chapter 6's Legacy notice, computed from the register for a given date.

Each model of lifecycle/register.yaml gets one row for the date: the days left to its retirement, and a state,
`retired` (past the date), `alert` (within 90 days), `review` (within 180), `clear` (further off), or `unscheduled`
(no date published, with the earliest possible date where the provider gives one). The rules of
lifecycle/alerts.yaml then fire: a page for a pinned model past its date, a ticket for a pinned model within 90
days, a review row for any model within 180, a ticket for a pinned model in a provider's notice stage. Nothing here
reads a run or calls anything.

Run (from labs/ch16):  python lifecycle/retirement.py --on 2027-02-01          the rows and the alerts for that date
                       python lifecycle/retirement.py --on 2027-02-01 --json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import register as registry_file  # noqa: E402

ALERTS = HERE / "alerts.yaml"
STATES = ("retired", "alert", "review", "clear", "unscheduled")
NOTICE_STAGES = {"aws": ("Legacy",), "azure": ("Legacy", "Deprecated"), "google": (), "local": ()}


def load_rules(path: Path = ALERTS) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["retirement"]


def state_of(model: dict[str, Any], on: dt.date, alert_days: int, review_days: int) -> dict[str, Any]:
    """One model's row for the date."""
    retires = model.get("retires")
    earliest = model.get("retires_no_earlier_than")
    row: dict[str, Any] = {"model": model["id"], "name": model["name"], "cloud": model["cloud"],
                           "pinned": bool(model["pinned"]), "stage": model["stage"],
                           "retires": retires.isoformat() if retires else None,
                           "earliest": earliest.isoformat() if earliest else None, "days_left": None}
    if retires is None:
        row["state"] = "unscheduled"
        row["earliest_passed"] = bool(earliest and earliest <= on)
        return row
    days = (retires - on).days
    row["days_left"] = days
    if days < 0:
        row["state"] = "retired"
    elif days <= alert_days:
        row["state"] = "alert"
    elif days <= review_days:
        row["state"] = "review"
    else:
        row["state"] = "clear"
    return row


def evaluate(on: dt.date, register: dict[str, Any] | None = None, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """The rows and the alerts for the date, in the rules' order."""
    register = register or registry_file.load()
    rules = rules or load_rules()
    alert_days, review_days = rules["windows"]["alert_days"], rules["windows"]["review_days"]
    names = {r["name"]: r for r in rules["rules"]}
    rows = [state_of(m, on, alert_days, review_days) for m in registry_file.models(register)]
    alerts: list[dict[str, Any]] = []

    def fire(rule: str, row: dict[str, Any], detail: str) -> None:
        alerts.append({"rule": rule, "action": names[rule]["action"], "model": row["model"], "name": row["name"],
                       "cloud": row["cloud"], "pinned": row["pinned"], "retires": row["retires"],
                       "days_left": row["days_left"], "detail": detail})

    for row, model in zip(rows, registry_file.models(register)):
        if row["pinned"] and row["state"] == "retired":
            fire("retired-still-pinned", row, f"retired {-row['days_left']} days ago and still pinned")
        if row["pinned"] and row["state"] == "alert":
            fire("retirement-90d", row, f"retires in {row['days_left']} days; replacement: {model['replacement']}")
        if row["state"] in ("alert", "review"):
            fire("retirement-180d-review", row, f"retires in {row['days_left']} days"
                 + ("; Larkspur runs on it" if row["pinned"] else "; not behind a Larkspur alias"))
        if row["pinned"] and model["stage"] in NOTICE_STAGES.get(model["cloud"], ()):
            since = model.get("legacy_from")
            fire("legacy-notice", row, f"in {model['stage']}" + (f" since {since}" if since else
                                                                 ", with no start date on the provider's schedule"))
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in STATES}
    return {"on": on.isoformat(), "windows": {"alert_days": alert_days, "review_days": review_days},
            "counts": counts, "rows": rows, "alerts": alerts,
            "pages": sum(1 for a in alerts if a["action"] == "page"),
            "tickets": sum(1 for a in alerts if a["action"] == "ticket"),
            "review_rows": sum(1 for a in alerts if a["action"] == "review")}


def render(result: dict[str, Any]) -> str:
    lines = [f"Retirement on {result['on']}: " + ", ".join(f"{s} {n}" for s, n in result["counts"].items()), ""]
    lines += ["|Model |Cloud |Pinned |Stage |Retires |Days left |State |", "|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        lines.append(f"|{r['name']} |{r['cloud']} |{'yes' if r['pinned'] else 'no'} |{r['stage']} "
                     f"|{r['retires'] or ('no earlier than ' + r['earliest'] if r['earliest'] else 'none published')} "
                     f"|{'' if r['days_left'] is None else r['days_left']} |{r['state']} |")
    lines += ["", f"Alerts: {result['pages']} page, {result['tickets']} ticket, {result['review_rows']} review", ""]
    for a in result["alerts"]:
        lines.append(f"- {a['action']}: {a['rule']}, {a['name']} ({a['cloud']}): {a['detail']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--on", type=dt.date.fromisoformat, default=dt.date.today(), help="the date, YYYY-MM-DD")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = evaluate(args.on)
    print(json.dumps(result, indent=1) if args.json else render(result), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
