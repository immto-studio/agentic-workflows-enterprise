"""The monthly review (chapter 16, step 9, companion #14, O-D15): one month's review for Ingrid Holm, written from
the kept files alone.

Per workflow: the runs kept and the month's volume; cost per run, median and 95th percentile, against the manifest's
per_run_usd; the month against per_month_usd; the shared lines by O-D6 (the GPU hours split by tokens, the idle
remainder on the platform team's line, the fixed costs split by tokens); the error budget left and the incidents of
step 6's month; the budget events and the switches pulled in the month; the models within 180 days of retirement on
the review's date; and W5's proposed, merged, and realized savings with what finding them cost. Every section says
what its figures are (measured, priced, estimated, simulated, or recorded) and which file they come from, and where a
decision names a figure that no file holds, the page says so in its place. No model, no gateway, no network.

What the review reads, each from the newest results folder that holds it:
  results/<date>/ledger.json                           steps 2, 3b, and 9: cost per run, the month, the allocation,
                                                       chapter 15's judge against what it judged
  results/<date>/slo/{kept,month,policy,alerts}.json   step 6: the SLIs, the simulated month, its budgets and alerts
  results/<date>/budget/drills.json                    step 4: the budget alerts, the 422, the switches' change records
  results/<date>/lifecycle/changes.jsonl               step 8: the alias remap's change record
  lifecycle/register.yaml, lifecycle/alerts.yaml       step 8: the register and the 180-day review window
  workflows/w5-drift/eval/results/.../ledger.json      W5's ledger, read with W5's own Ledger.summary(month)
  ledger/volumes.yaml, ledger/prices.yaml, playbook/playbook.yaml, and the manifests

The month filters what carries a date: W5's ledger rows, the budget alerts, and the change records. The kept runs, the
estimated volumes, step 6's simulated month, and the register carry no month of their own, so another month changes
sections 6 and 8 and the page says so. A month in which W5 ran no night says that in its place; an input that does not
exist stops the run before anything is written, and the page and its JSON are written together or not at all.

Run (from labs/ch16):  python review/monthly_review.py --month 2026-11 --on 2026-11-09 --out results/2026-11-09/review
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "lifecycle", LAB / "capacity", LAB / "ledger", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import costlines  # noqa: E402  the ledger's reader, which puts chapter 15's registry on sys.path
import judge_lines  # noqa: E402  chapter 15's judge in the ledger, and the phrases for what it shows
import offline  # noqa: E402
import price  # noqa: E402
import register as register_file  # noqa: E402  step 8's register
import registry  # noqa: E402  chapter 15's: the manifests and the kept runs
import retirement  # noqa: E402  step 8's alert, evaluated for the review's date
from summary import num as _num  # noqa: E402  step 5's number format
from summary import table  # noqa: E402  step 5's table helper

FILES = ("review-{month}.md", "review-{month}.json")
GPU_READING = "manifests and chapter 10"   # the tenants of the self-hosted alias, as the plan settled them (step 2)
FIXED_BASIS = "tokens"                      # O-D6 as amended on 3 November 2026: the fixed costs split by tokens
ET = ZoneInfo("America/Toronto")            # step 6's wall clock (slo/simulate.py)
WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
# The playbook's symptom each injected event of the simulated month is read as, the lab's reading. A throttled
# provider has no symptom of its own in O-D13's list: it is the platform's page (ch05:498, slo/alerts.yaml). An event
# that is missing from this table stops the review: the reading is a decision, and a default would be a guess.
SYMPTOM_OF = {
    "provider-outage": "a provider outage",
    "throttled-hour": None,
    "model-regression": "a model that changed under its alias",
    "self-hosted-down": "a provider outage",
    "w4-records-refused": "a run of refusals or tool errors",
}
NO_SYMPTOM = "none in the playbook; the platform's page, provider-429-across-workflows (ch05:498)"
# Why the controls' breaches are not counted. slo/slis.py gives a run a `violation` field and lists the runs that
# carry one, and no kept run and no simulated run sets it, so an empty list is the length of a list nothing fills.
CONTROLS_WHY = ("nothing in the lab checks a run against a control: a run's `violation` field is set by no kept run and "
                "no simulated run (slo/slis.py), so the empty incident lists in kept.json and month.json say nothing about "
                "residency, the never-list, or the budgets. The controls hold by refusal, and the gateway's refusal "
                "counts, the `refused` and `failed` cost lines, could stand in for a check; no step reads them to check "
                "a control")
# The levers' names in a change record, as budget/oncall.py and lifecycle/remap.py write them, and how to count them.
LEVERS = {"kill switch, gateway half": ("kill-switch cycle", "kill-switch cycles"),
          "rung down": ("rung down", "rungs down"), "alias remap, back": ("alias remap", "alias remaps")}


# --- words and numbers ------------------------------------------------------------------------------------------

def words(n: int) -> str:
    """A count in prose: a word up to ten, digits above."""
    return WORDS[n] if 0 <= n <= 10 else f"{n:,}"


def plural(n: int, noun: str, many: str | None = None, lead: bool = False) -> str:
    """The count with its noun: 0 pages, 1 page, 5 review rows. At the start of a sentence (`lead`) a count up to ten
    is a word: Five budgets."""
    count = words(n).capitalize() if lead and n <= 10 else f"{n:,}"
    return f"{count} {noun if n == 1 else (many or noun + 's')}"


def join(items: list[str]) -> str:
    """A list in prose: A, B and C."""
    return judge_lines.join(items)


def num(value: Any, digits: int = 3) -> str:
    """Step 5's number format with thousands separators in every range: 2,560 where step 5's helper prints 2560."""
    return re.sub(r"^(-?\d+)(\.\d+)?$", lambda m: re.sub(r"\B(?=(\d{3})+(?!\d))", ",", m[1]) + (m[2] or ""), _num(value, digits))


def pct(value: float | None, digits: int = 3) -> str:
    return "" if value is None else f"{num(value, digits)}%"


def usd(value: float | None) -> str:
    """An amount in USD: cents from a dollar up, with a separator past a thousand; three significant digits below a
    dollar, trailing zeros kept, as the ledger's tables print them."""
    if value is None:
        return ""
    if value == 0:
        return "0"
    if abs(value) >= 1:
        return f"{value:,.2f}"
    places = 2 - int(math.floor(math.log10(abs(value))))
    return f"{round(value, places):.{places}f}"


def counts(mapping: dict[str, int] | None) -> str:
    """A tally in one format: model-regression 5,161, baseline 261."""
    return ", ".join(f"{k} {v:,}" for k, v in (mapping or {}).items())


def pair(d: dict[str, Any], key: str, fmt=num) -> str:
    return f"{fmt(d[key]['median'])} / {fmt(d[key]['p95'])}"


def day(value: str | dt.date) -> str:
    d = value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))
    return f"{d.day} {d.strftime('%B %Y')}"


def month_name(month: str) -> str:
    return dt.datetime.strptime(month, "%Y-%m").strftime("%B %Y")


def day_name(on: dt.date) -> str:
    return day(on)


def span(first: str, last: str) -> str:
    """Two dates as a range: 28 October to 3 November 2026."""
    a, b = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    if a == b:
        return day(a)
    if a.year != b.year:
        return f"{day(a)} to {day(b)}"
    return f"{a.day} to {day(b)}" if a.month == b.month else f"{a.day} {a.strftime('%B')} to {day(b)}"


def with_year(text: str | None, start: str, seconds: float | None) -> str | None:
    """Step 6's wall time ("Mon 11 Jan 10:00", ET) with the year of the moment it names, which month.json's start and
    the seconds from it give: the simulated month is January 2027, and a page dated November 2026 would otherwise
    read it as the January before."""
    if text is None or seconds is None:
        return text
    year = (dt.datetime.fromisoformat(start).astimezone(ET) + dt.timedelta(seconds=seconds)).year
    *date, clock = text.split(" ")
    return " ".join([*date, str(year), clock])


def table_dates(table_: dict[str, Any]) -> dict[str, Any]:
    """The dated price table's size and the span of its entries' dates."""
    entries = price.entries(table_)
    dates = sorted(dt.date.fromisoformat(str(e["date"])) for e in entries if e.get("date"))
    return {"entries": len(entries), "dated": len(dates), "first": dates[0].isoformat(), "last": dates[-1].isoformat()}


def legend(month: dict[str, Any], dates: dict[str, Any]) -> dict[str, str]:
    """The five words, with the simulated month's length and events and the price table's dates from the files that
    hold them."""
    return {
        "measured": "read or computed from a kept run, a drill, or a live run on this workstation or in the lab account",
        "priced": "measured tokens or calls times a price of the dated table, at chapter 6's design: what the same tokens "
                  "would cost on the managed alias, since the local models cost nothing",
        "estimated": "Larkspur's monthly volumes (ledger/volumes.yaml, each with its source) and anything multiplied by "
                     "them, and the guardrail's estimate, which no cost line carries",
        "simulated": f"step 6's month, {month['days']} days built from the kept runs with {words(len(month['injected']))} "
                     f"injected events, marked simulated wherever it appears",
        "recorded": "a date, a state, or a change record read from a register or a record file, not measured by the lab",
    }


# --- the inputs -------------------------------------------------------------------------------------------------

def newest(results: Path, relative: str) -> Path:
    """The file at `relative` in the newest dated results folder that holds it."""
    found = sorted(p / relative for p in results.iterdir() if p.is_dir() and (p / relative).exists())
    if not found:
        raise FileNotFoundError(f"no results folder under {results} holds {relative}")
    return found[-1]


def w5_ledgers(model: str) -> list[tuple[str, Path]]:
    """W5's kept runs on the model that kept a ledger: (chapter 15's label, the ledger's path)."""
    out = []
    for run in registry.kept_runs("w5"):
        if run.model != model:
            continue
        path = registry.path(run.folder) / f"nights-{run.model}" / "ledger.json"
        if path.exists():
            out.append((run.label, path))
    return out


@dataclass(frozen=True)
class Sources:
    ledger: Path
    slo: Path
    drills: Path
    changes: Path
    register: Path
    retirement_rules: Path
    playbook: Path
    volumes: Path
    prices: Path
    w5_ledger: Path
    w5_label: str
    w5_others: tuple[tuple[str, Path], ...]   # the other kept ledgers on the reference model, for the range

    @classmethod
    def committed(cls, results: Path = LAB / "results", w5_label: str = "2026-11-03/after-review") -> Sources:
        volumes = yaml.safe_load((LAB / "ledger" / "volumes.yaml").read_text(encoding="utf-8"))
        ledgers = w5_ledgers(volumes["reference_model"])
        mine = [p for label, p in ledgers if label == w5_label]
        if not mine:
            raise FileNotFoundError(f"W5 kept no ledger labeled {w5_label!r} on {volumes['reference_model']}")
        return cls(newest(results, "ledger.json"), newest(results, "slo/policy.json").parent,
                   newest(results, "budget/drills.json"), newest(results, "lifecycle/changes.jsonl"),
                   LAB / "lifecycle" / "register.yaml", LAB / "lifecycle" / "alerts.yaml",
                   LAB / "playbook" / "playbook.yaml", LAB / "ledger" / "volumes.yaml", LAB / "ledger" / "prices.yaml",
                   mine[0], w5_label, tuple((label, p) for label, p in ledgers if label != w5_label))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rel(path: Path) -> str:
    """Repository-relative where the file is in the repository, else the file's name: no path of this machine."""
    try:
        return registry.rel(path)
    except ValueError:
        return path.name


W5_LEDGER_MODULE = "workflows/w5-drift/writer/ledger.py"


def _companion_module(module: Any) -> bool:
    """A module loaded from the companion's folders outside chapter 15's lab: a workflow's, or one of this lab's."""
    file = getattr(module, "__file__", None)
    if not file:
        return False
    where = Path(file).resolve()
    return where.is_relative_to(registry.ROOT) and not where.is_relative_to(registry.LAB)


def w5_summary(path: Path, month: str) -> dict[str, Any]:
    """W5's own Ledger.summary(month), its module loaded from its file in isolation, as slis.py imports the harnesses;
    and the two amounts behind its shares, kept for one ratio and never printed (W5-D10).

    W5's writer imports its neighbors by bare name (render, common, validate, findings, github_fake, pull_requests),
    and this lab and the other workflows have modules of some of those names (ledger/render.py, W4's github_fake). So
    every companion module already imported is taken out of sys.modules for the load and put back after it, and the
    modules the load brought in are dropped by registry.isolated as usual."""
    parked = {name: sys.modules.pop(name) for name, module in list(sys.modules.items()) if _companion_module(module)}
    try:
        with registry.isolated(("workflows/w5-drift/writer", "workflows/w5-drift/detect")):
            spec = importlib.util.spec_from_file_location("w5_writer_ledger", registry.path(W5_LEDGER_MODULE))
            w5 = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(w5)
            book = w5.Ledger(path)
            summary = book.summary(month)
            rows = [r for r in book.findings.values() if (r.get("last_seen") or "").startswith(month)]
            proposed = sum(r.get("estimated_monthly_saving") or 0.0 for r in rows if r.get("pull_request"))
            realized = sum(r.get("realized_monthly_saving") or 0.0 for r in book.findings.values()
                           if (r.get("realized_on") or "").startswith(month))
            nights = [n for d, n in sorted(book.nights.items()) if d.startswith(month)]
    finally:
        for name, module in list(sys.modules.items()):  # W5's, if isolated left any
            if _companion_module(module):
                del sys.modules[name]
        sys.modules.update(parked)
    return {"summary": summary, "proposed_amount": proposed, "realized_amount": realized,
            "night_kinds": counts_of((n.get("trigger") or {}).get("kind", "schedule") for n in nights)}


def counts_of(items: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return dict(sorted(out.items()))


# --- the sections -----------------------------------------------------------------------------------------------

def runs_and_cost(ledger: dict[str, Any], workflows: list[str]) -> dict[str, Any]:
    model = ledger["month"]["reference_model"]
    lines = {r["workflow"]: r for r in ledger["lines"]}
    months = {r["workflow"]: r for r in ledger["month"]["rows"]}
    rows = []
    for w in workflows:
        mine = next(r for r in ledger["per_run"] if r["workflow"] == w and r["model"] == model)
        cost, pct_, calls = mine["cost_usd"], mine["cost_pct_of_run_budget"], mine["model_calls"]
        m = months[w]
        rows.append({
            "workflow": w, "kept_runs": lines[w]["kept_runs"], "runs_kept": lines[w]["runs"],
            "runs_on_the_model": mine["runs"], "runs_with_tokens": mine["runs_with_tokens"],
            "runs_a_month": m["runs_per_month"], "unit": m["volume"].get("unit"), "volume_sources": m["sources"],
            "model_calls_a_run": {"median": calls["median"], "p95": calls["p95"]},
            "cost_per_run_usd": {"median": cost["median"], "p95": cost["p95"]},
            "pct_of_per_run_usd": {"median": pct_["median"], "p95": pct_["p95"]},
            "per_run_usd": mine["per_run_usd"], "basis_of_the_per_run_figures": m["basis"],
        })
    by_model = [{"workflow": r["workflow"], "model": r["model"], "runs": r["runs"], "runs_with_tokens": r["runs_with_tokens"],
                 "cost_per_run_usd": {"median": r["cost_usd"]["median"], "p95": r["cost_usd"]["p95"]},
                 "pct_of_per_run_usd": {"median": r["cost_pct_of_run_budget"]["median"],
                                        "p95": r["cost_pct_of_run_budget"]["p95"]}}
                for r in ledger["per_run"] if r["workflow"] in workflows]
    highest = max(rows, key=lambda r: r["pct_of_per_run_usd"]["median"])
    tail = max(by_model, key=lambda r: r["pct_of_per_run_usd"]["p95"])
    judge = ledger["judge"]
    judge_rows = []
    for r in judge["by_workflow"]:
        if r["judge"] == "both":
            continue
        basis = "measured" if r["measured"]["judgments"] else "stand-in"
        b = r[basis]
        judge_rows.append({"workflow": r["workflow"], "judge": r["judge"], "judgments": r["judgments"],
                           "judge_tokens": r["judge_tokens"], "judged_tokens": b["judged_tokens"], "ratio": b["ratio"],
                           "basis": basis, "completion_over": b["completion_over"]})
    return {
        "basis": {"runs_kept": "measured", "model_calls_a_run": "measured", "runs_a_month": "estimated",
                  "cost_per_run": "priced", "judge_tokens": "measured",
                  "note": f"the per-run figures are the kept runs' on {model}, the ledger's reference model: their calls "
                          f"and tokens are measured, and the dollars are those tokens priced at chapter 6's design from "
                          f"ledger/prices.yaml; the volumes are ledger/volumes.yaml's, each with its source; the 95th "
                          f"percentile is the nearest rank, a value some run had; chapter 15's judge is in the ledger "
                          f"under the workflow it judged, and its ratio is its tokens over the judged outputs' own, with "
                          f"step 3b's run of the same case standing in where a judged output kept no tokens, as the "
                          f"basis column says"},
        "reference_model": model, "rows": rows, "by_model": by_model,
        "highest_median": {"workflow": highest["workflow"], "pct": highest["pct_of_per_run_usd"]["median"]},
        "highest_p95": {"workflow": tail["workflow"], "model": tail["model"], "pct": tail["pct_of_per_run_usd"]["p95"]},
        "judge": {"calls": judge["calls"], "runs": len(judge["layout"]), "prompt_tokens": judge["prompt_tokens"],
                  "completion_tokens": judge["completion_tokens"], "thinking": judge["thinking"],
                  "conclusion": judge["conclusion"], "rows": judge_rows},
    }


def month_against_budget(ledger: dict[str, Any], workflows: list[str]) -> dict[str, Any]:
    rows = []
    for r in ledger["month"]["rows"]:
        if r["workflow"] not in workflows:
            continue
        rows.append({"workflow": r["workflow"], "runs_a_month": r["runs_per_month"], "calls_a_month": r["calls_per_month"],
                     "tokens_a_month": r["tokens_per_month"], "mean_cost_per_run_usd": r["cost_per_run_usd"],
                     "direct_usd": r["direct_usd"],
                     "per_month_usd": r["per_month_usd"], "pct_of_per_month_usd": r["direct_pct_of_month"],
                     "kept_runs_in_profile": len(r["kept_runs"]), "pct_range_over_kept_runs": r["direct_pct_range_over_kept_runs"],
                     "recounted_as_nova_lite_pct": r["recounted_pct_of_month"],
                     "guardrail_pct": r["guardrail_pct_of_month"], "basis_of_the_per_run_figures": r["basis"],
                     "volume_sources": r["sources"]})
    largest = max(rows, key=lambda r: r["pct_of_per_month_usd"])
    return {"basis": {"month": "estimated", "mean_cost_per_run": "priced",
                      "note": "the month is the estimated volume times the mean cost per run, the mean over the runs "
                              "section 1's median and 95th percentile summarize; the guardrail column is an estimate "
                              "the cost lines don't carry (step 2); the recounted column multiplies the tokens by the "
                              "ratios Nova Lite's count showed on W1's cases"},
            "rows": rows, "largest": {"workflow": largest["workflow"], "pct": largest["pct_of_per_month_usd"]},
            "recount_ratios": ledger["month"]["recount_ratios"]}


def shared_lines(ledger: dict[str, Any], workflows: list[str]) -> dict[str, Any]:
    gpu = ledger["allocation"]["gpu"]
    reading = gpu["readings"][GPU_READING]
    fixed = ledger["allocation"]["fixed"]
    split = fixed["splits"][FIXED_BASIS]
    direct = {r["workflow"]: r["direct_usd"] for r in ledger["month"]["rows"]}
    rows = []
    for w in workflows:
        g = reading["split"].get(w)
        f = split[w]
        rows.append({"workflow": w, "tenant": w in reading["tenants"],
                     "restricted_tokens_a_month": g["tokens"] if g else 0, "token_share": g["token_share"] if g else None,
                     "gpu_usd": g["usd"] if g else 0.0, "gpu_pct_of_per_month_usd": g["pct_of_month"] if g else 0.0,
                     "fixed_share": f["share"], "fixed_usd": f["usd"], "fixed_pct_of_per_month_usd": f["pct_of_month"],
                     "direct_usd": direct[w]})
    return {"basis": {"shares": "estimated", "note": "O-D6: the GPUs' hours (two replicas, every hour of the month, at "
                                                    "the dated table's price) are split among the alias's tenants by "
                                                    "their share of its tokens, from the estimated volumes at the "
                                                    "measured tokens per run, and the idle remainder is the platform "
                                                    "team's line; the platform's fixed costs are split by tokens, as "
                                                    "O-D6 was amended on 3 November 2026 (ch02:144); the shared lines "
                                                    "are showback beside the direct costs and never count against a "
                                                    "workflow's budget"},
            "tenants": reading["tenants"], "tenants_from": GPU_READING, "rows": rows,
            "gpu": {"replicas": gpu["replicas"], "hours": gpu["hours"], "price": gpu["price"], "usd": gpu["usd"],
                    "used_usd": reading["used_usd"], "idle_usd": reading["idle_usd"], "idle_share": reading["idle_share"]},
            "fixed": {"priced_usd": fixed["priced_usd"], "stand_in_usd": fixed["stand_in_usd"],
                      "parameters": fixed["parameters"], "split_by": FIXED_BASIS}}


def error_budget(slo: Path, workflows: list[str]) -> dict[str, Any]:
    kept = read_json(slo / "kept.json")
    month = read_json(slo / "month.json")
    policy = read_json(slo / "policy.json")
    measured = []
    for w in workflows:
        pool = kept["pooled"][w]
        for sli in ("success", "latency", "outcome"):
            ratio = pool["slis"][sli]
            target = kept["targets"][w][sli]
            if target is None:
                continue
            measured.append({"workflow": w, "sli": sli, "target": target,
                             "threshold_s": kept["thresholds_s"][w] if sli == "latency" else None,
                             "good": ratio["good"], "valid": ratio["valid"], "value": ratio["value"]})
    simulated = []
    for w in workflows:
        for sli, a in policy["accounts"][w].items():
            left = None if not a["budget_events"] else round(1 - a["bad"] / a["budget_events"], 4)
            simulated.append({"workflow": w, "sli": sli, "budget_events": a["budget_events"], "bad": a["bad"],
                              "valid": a["valid"], "used": a["consumed"], "left": left,
                              "spent_at": with_year(a["spent_at_clock"], month["start"], a["spent_at"]),
                              "spent_at_s": a["spent_at"], "causes": a["causes"],
                              "value": month["workflows"][w]["slis"][sli]["value"]})
    return {"basis": {"slis_on_the_kept_runs": "measured", "budgets": "simulated",
                      "note": "the SLIs are measured on the kept runs; the error budgets are step 6's, 1 minus the "
                              "target times the valid events the simulated month expects, and what is left is what "
                              "that month left, every event of it drawn from the kept runs or injected"},
            "month": {"seed": month["seed"], "start": month["start"], "days": month["days"]},
            "measured": measured, "simulated": simulated,
            "spent": [a for a in simulated if a["spent_at"]]}


def incidents(slo: Path, playbook_path: Path, workflows: list[str]) -> dict[str, Any]:
    kept = read_json(slo / "kept.json")
    month = read_json(slo / "month.json")
    alerts = read_json(slo / "alerts.json")
    policy = read_json(slo / "policy.json")
    start = month["start"]
    playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))
    symptoms = {s["symptom"] for s in playbook["symptoms"]}
    for symptom in SYMPTOM_OF.values():
        if symptom is not None and symptom not in symptoms:
            raise ValueError(f"the playbook names no symptom {symptom!r}")
    proposed = alerts["proposed"]
    events = []
    for e in month["injected"]:
        if e["id"] not in SYMPTOM_OF:
            raise ValueError(f"injected event {e['id']!r} has no reading in SYMPTOM_OF (review/monthly_review.py): say which "
                             f"of the playbook's symptoms it is, or None if it has none")
        first = alerts["by_event"][e["id"]][proposed]
        actions = [a for a in policy["actions"] if e["id"] in (a.get("bad_when_spent") or {})]
        events.append({"id": e["id"], "what": e["what"], "start": with_year(e["start"], start, e["start_s"]),
                       "end": with_year(e["end"], start, e["end_s"]),
                       "symptom": SYMPTOM_OF[e["id"]] or NO_SYMPTOM,
                       "runs_changed": e["runs_changed"], "bad_events": e["bad_events"],
                       "first_alert": None if first["first"] is None else {
                           "action": first["action"], "scope": first["first"]["scope"], "sli": first["first"]["sli"],
                           "rule": first["first"]["rule"],
                           "start": with_year(first["first"]["start"], start, first["first"]["start_s"])},
                       # the actions whose budget the event helped spend, with its share of the bad events at that moment
                       "policy": [{"workflow": a["workflow"], "action": a["action"], "sli": a["sli"],
                                   "at": with_year(a["at"], start, a["at_s"]),
                                   "its_bad_events": a["bad_when_spent"][e["id"]],
                                   "bad_events_when_spent": sum(a["bad_when_spent"].values())} for a in actions]})
    by_scope: dict[str, dict[str, dict[str, int]]] = {}
    for design in (proposed, "platform"):
        for a in alerts["episodes"].get(design, []):
            scope = by_scope.setdefault(a["scope"], {"page": {}, "ticket": {}})
            scope[a["action"]][a["cause"]] = scope[a["action"]].get(a["cause"], 0) + 1
    scopes = [w for w in workflows if w in by_scope] + sorted(s for s in by_scope if s not in workflows)
    alert_rows = [{"scope": s, "pages": dict(sorted(by_scope[s]["page"].items())),
                   "tickets": dict(sorted(by_scope[s]["ticket"].items()))} for s in scopes]
    actions = [{"at": with_year(a["at"], start, a["at_s"]), "workflow": a["workflow"], "action": a["action"],
                "sli": a["sli"], "decided_by": a.get("decided_by", ""), "change": (a.get("change_record") or {}).get("change")}
               for a in policy["actions"]]
    listed = bool(kept["incidents"] or month["incidents"])
    breaches = {"status": "listed" if listed else "not evaluated", "kept_runs": kept["incidents"],
                "simulated_month": month["incidents"], "why": CONTROLS_WHY}
    return {"basis": {"events": "simulated", "control_breaches": breaches["status"],
                      # month.yaml's injected events each run their course: the month models no response
                      "note": f"the {words(len(month['injected']))} events were injected into step 6's month and each run "
                              f"its course, since the month models no response; the alerts are the proposed design's "
                              f"({proposed}) and the platform's; the symptom column is the lab's reading of the playbook"},
            "control_breaches": breaches,
            "events": events, "alerts_by_scope": alert_rows, "policy_actions": actions, "design": proposed}


def deployments(value: Any) -> str:
    """A change record's from or to: a state, a rung, or the alias's deployments with their weights."""
    if isinstance(value, list):
        return ", ".join(f"{d['id']}" + (f" (weight {d['weight']})" if "weight" in d else "") for d in value)
    return str(value)


def record_summary(grouped: dict[str, dict[str, Any]]) -> str:
    """The change records the month holds, by the run that left them and the lever: five kill-switch cycles and one
    rung down as drills, one alias remap in the upgrade path, run once."""
    by_run: dict[str, dict[str, int]] = {}
    for g in grouped.values():
        levers = by_run.setdefault(g["run"], {})
        levers[g["steps"][0]["lever"]] = levers.get(g["steps"][0]["lever"], 0) + 1
    parts = []
    for run, levers in by_run.items():
        what = join([f"{words(n)} {LEVERS.get(lever, (lever, lever))[0 if n == 1 else 1]}" for lever, n in levers.items()])
        parts.append(f"{what} {'as drills' if run == 'drill' else 'in ' + run}")
    return ", and ".join(parts)


def record_rule(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The rule each record line carries (ch02:163), read from the lines: the kind of change, who authorized it, the
    hours allowed to document it, and where it is reviewed."""
    hours = {round((dt.datetime.fromisoformat(c["document_by"]) - dt.datetime.fromisoformat(c["at"])).total_seconds() / 3600)
             for c in records}
    return {"kinds": sorted({c["kind"] for c in records}), "authority": sorted({c["authority"] for c in records}),
            "hours": sorted(hours), "review": sorted({c["review"] for c in records})}


def budget_events_and_switches(drills_path: Path, changes_path: Path, month: str) -> dict[str, Any]:
    drills = read_json(drills_path)
    drill_date = drills.get("date")
    alerts = [{"received_at": a["received_at"], "event": a["event"], "what": a["kind"], "workflow": a["key_alias"],
               "spend_usd": a["spend"], "max_budget_usd": a["max_budget"], "soft_budget_usd": a.get("soft_budget"),
               "projected_usd": a.get("projected_spend"), "forwarded_to": a["forwarded_to"]}
              for a in drills.get("alerts", []) if a["received_at"].startswith(month)]
    stop = drills.get("stop") or {}
    stop_row = None
    if stop and (drill_date or "").startswith(month):  # the stop belongs to the drills' day, not to every month
        stop_row = {"workflow": "w2-ops-assistant", "status": stop["stop_status"], "kind": stop["stop_kind"],
                    "first_stopped_run": stop["first_stopped_run"], "max_budget_usd": stop["max_budget"],
                    "month_before_usd": stop["month_before_the_first_stop_usd"],
                    "month_after_usd": stop["spend_in_database_after_usd"], "short_of_budget_usd": stop["short_of_the_budget_usd"],
                    "calls_by_stopped_runs": stop["calls_made_by_stopped_runs"]}
    records = [dict(c, source=rel(drills_path), run="drill") for c in drills.get("changes", [])]
    records += [dict(c, source=rel(changes_path), run="the upgrade path, run once") for c in read_jsonl(changes_path)]
    records = [c for c in records if c["at"].startswith(month)]
    grouped: dict[str, dict[str, Any]] = {}
    for c in records:
        g = grouped.setdefault(c["change"], {"change": c["change"], "kind": c["kind"], "steps": [], "workflow": None,
                                             "by": c["by"], "first_at": c["at"], "last_at": c["at"],
                                             "document_by": c["document_by"], "review": c["review"], "run": c["run"],
                                             "source": c["source"], "lines": 0})
        g["steps"].append({"lever": c["lever"], "from": deployments(c["from"]), "to": deployments(c["to"])})
        g["workflow"] = c.get("alias") or c["workflow"]
        g["last_at"], g["lines"] = c["at"], g["lines"] + 1
    held = (f"the change records are the lines the levers left in {month_name(month)}: {record_summary(grouped)}"
            if grouped else "the month holds no change record")
    return {"basis": {"records": "recorded", "timings": "measured",
                      "note": f"step 4's drills ran on {day(drill_date)} (UTC) and set the month's spend through "
                              f"LiteLLM's admin API, so the alerts and the stop are measured on a seeded month; {held}"
                      if drill_date else f"the drills' date is not recorded; {held}"},
            "month": month, "alerts": alerts, "stop": stop_row, "changes": list(grouped.values()),
            "rule": record_rule(records) if records else None, "drill_date": drill_date}


def within_180_days(on: dt.date, register_path: Path, rules_path: Path) -> dict[str, Any]:
    result = retirement.evaluate(on, register_file.load(register_path), retirement.load_rules(rules_path))
    fired: dict[str, list[str]] = {}
    for a in result["alerts"]:
        fired.setdefault(a["model"], []).append(a["action"] if a["rule"] != "legacy-notice" else "ticket (Legacy notice)")
    rows = [{"model": r["name"], "cloud": r["cloud"], "pinned": r["pinned"], "stage": r["stage"], "retires": r["retires"],
             "days_left": r["days_left"], "state": r["state"], "fires": fired.get(r["model"], [])}
            for r in result["rows"] if r["state"] in ("retired", "alert", "review")]
    rows.sort(key=lambda r: (r["days_left"], r["model"]))
    unscheduled = [{"model": r["name"], "cloud": r["cloud"], "pinned": r["pinned"], "earliest": r["earliest"],
                    "earliest_passed": r.get("earliest_passed", False)}
                   for r in result["rows"] if r["state"] == "unscheduled"]
    return {"basis": {"dates": "recorded", "note": "the register's dates are the providers' published ones, each "
                                                   "with its source and the date it was read (lifecycle/register.yaml); "
                                                   "the days left are counted to the review's date"},
            "on": on.isoformat(), "windows": result["windows"], "counts": result["counts"], "rows": rows,
            "unscheduled": unscheduled, "pages": result["pages"], "tickets": result["tickets"],
            "review_rows": result["review_rows"]}


def w5_savings(sources: Sources, month: str, table_: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    """W5's shares from its own ledger, and the cost of finding them as shares of its budgets. The page prints no
    amount for W5 (W5-D10), so the priced cost is kept as percentages and the amounts stay in this function."""
    mine = w5_summary(sources.w5_ledger, month)
    s = mine["summary"]
    agent = s["agent"]
    manifest = registry.manifest("w5")
    model = ledger["month"]["reference_model"]
    # W5's own gateway lines carry the manifest's class, confidential
    line = costlines.CostLine("w5-month", None, "w5", manifest["workflow"], sources.w5_label, "month", 1, model, model,
                              "larkspur-chat", "larkspur-chat", manifest["data_class_max"], agent["prompt_tokens"],
                              agent["completion_tokens"], None, False, rel(sources.w5_ledger))
    priced = price.line_cost(table_, line) or Decimal(0)
    budget = manifest["budget"]["per_month_usd"]
    realized = mine["realized_amount"]
    others = []
    for label, path in sources.w5_others:
        other = w5_summary(path, month)
        others.append({"kept_run": label, **{k: other["summary"]["agent"][k] for k in
                                             ("gateway_calls", "prompt_tokens", "completion_tokens", "seconds")},
                       "same_savings": other["summary"]["savings"] == s["savings"]})
    completion = [agent["completion_tokens"]] + [o["completion_tokens"] for o in others]
    seconds = [agent["seconds"]] + [o["seconds"] for o in others]
    night = next(r for r in ledger["per_run"] if r["workflow"] == "w5" and r["model"] == model)
    return {"basis": {"savings": "recorded", "calls_and_tokens": "measured", "cost_to_find": "priced",
                      "note": "the savings are W5's ledger's own shares (writer/ledger.py, summary(month)): the "
                              "estimates the detectors made for the findings that got a pull request, over the "
                              "accounts' spend the nights read, with a merged and applied finding credited when a later "
                              "night found its resource gone; the accounts are the lab's fixtures, and the ledger gives "
                              "shares and counts and never an amount (W5-D10), so the page does too. The cost to find "
                              "them is the gateway's calls and tokens for the month's runs, priced at the dated "
                              "table's price for larkspur-chat on the kept runs' token counts, which Nova Lite would "
                              "count differently (step 2's ratios), and shown as shares of W5's budgets"},
            "ledger": rel(sources.w5_ledger), "kept_run": sources.w5_label, "month": s["month"],
            "nights": s["nights"], "night_kinds": mine["night_kinds"],
            "findings": s["findings"], "pull_requests": s["pull_requests"], "savings": s["savings"],
            "agent": agent,
            "priced": {"deployment": price.deployment(table_, "larkspur-chat")["id"],
                       "pct_of_per_month_usd": float(round(priced / Decimal(budget) * 100, 6)),
                       "share_of_realized_saving": None if not realized else float(round(priced / Decimal(str(realized)), 8))},
            "per_night": {"model": night["model"], "pct_of_per_run_usd": {"median": night["cost_pct_of_run_budget"]["median"],
                                                                          "p95": night["cost_pct_of_run_budget"]["p95"]}},
            "other_kept_runs": others,
            "range_over_kept_runs": {"runs": 1 + len(others), "completion_tokens": [min(completion), max(completion)],
                                     "seconds": [min(seconds), max(seconds)]}}


def build(month: str, on: dt.date, sources: Sources) -> dict[str, Any]:
    ledger = read_json(sources.ledger)
    table_ = price.load(sources.prices)
    simulated = read_json(sources.slo / "month.json")
    dates = table_dates(table_)
    workflows = [r["workflow"] for r in ledger["month"]["rows"]]
    sections = {
        "runs_and_cost_per_run": runs_and_cost(ledger, workflows),
        "month_against_budget": month_against_budget(ledger, workflows),
        "shared_lines": shared_lines(ledger, workflows),
        "error_budget": error_budget(sources.slo, workflows),
        "incidents": incidents(sources.slo, sources.playbook, workflows),
        "budget_events_and_switches": budget_events_and_switches(sources.drills, sources.changes, month),
        "retirement": within_180_days(on, sources.register, sources.retirement_rules),
        "w5_savings": w5_savings(sources, month, table_, ledger),
    }
    return {"review": "monthly", "month": month, "on": on.isoformat(), "for": "Ingrid Holm's monthly review (O-D15)",
            "legend": legend(simulated, dates), "prices": {"file": rel(sources.prices), **dates},
            "workflows": workflows, "sections": sections,
            "sources": {"ledger": rel(sources.ledger), "slo": rel(sources.slo), "drills": rel(sources.drills),
                        "changes": rel(sources.changes), "register": rel(sources.register),
                        "retirement_rules": rel(sources.retirement_rules), "playbook": rel(sources.playbook),
                        "volumes": rel(sources.volumes), "prices": rel(sources.prices), "w5_ledger": rel(sources.w5_ledger),
                        "manifests": [registry.WORKFLOWS[w].manifest for w in workflows]}}


# --- the page -----------------------------------------------------------------------------------------------------

def left_cell(a: dict[str, Any]) -> str:
    if a["left"] is None:
        return ""
    if a["spent_at"]:
        return f"spent, {a['spent_at']} (used {pct(100 * a['used'], 4)})"
    return pct(100 * a["left"])


def basis_line(section: dict[str, Any], sources: list[str]) -> list[str]:
    b = section["basis"]
    marks = "; ".join(f"{k.replace('_', ' ').replace('slis', 'SLIs')} {v}" for k, v in b.items() if k != "note")
    note = b["note"][0].upper() + b["note"][1:]
    return [f"Basis: {marks}. {note}. Source: {', '.join(f'`{s}`' for s in sources)}.", ""]


def judge_paragraph(jd: dict[str, Any]) -> str:
    """Section 1's sentences on chapter 15's judge, from the ledger's `conclusion` and the phrases judge_lines shares
    with its own summary: the sentence of ch15:156 for completion tokens, in total, and the all-token ratios as token
    figures and not prices."""
    c = jd["conclusion"]
    names = {"gemma4-12b": "Gemma 4 12B", "gpt-oss-20b": "gpt-oss-20b"}
    thinking = {x: ("thinking at the model's default" if jd["thinking"][x] == "model default" else
                    "thinking off" if jd["thinking"][x] is False else "thinking varying across its files")
                for x in (*c["thinking_on"], *c["thinking_off"])}
    out = [f"Chapter 15's judge is in the ledger under the workflow it judged: {jd['calls']:,} judgments in {jd['runs']} runs, "
           f"{jd['prompt_tokens']:,} prompt and {jd['completion_tokens']:,} completion tokens (measured), each set against "
           f"the tokens of the output it read, the kept run's own cost lines; where a judged output kept no tokens, step "
           f"3b's run of the same case stands in and the basis column says so. Chapter 15 says (ch15:156) that a judge that "
           f"thinks before it answers writes more tokens than the answer it judges."]
    for x in c["thinking_on"]:
        rows, above = c["by_judge"].get(x, []), c["completion_in_total"][x]["above"]
        tail = []
        if rows and len(above) == len(rows):
            tail.append("the sentence holds as written, for completion tokens, wherever that judge judged")
        if c["not_judged_by"][x]:
            tail.append(judge_lines.alone_text(c["not_judged_by"][x]))
        out.append(f"In completion tokens, in total, {names[x]} ({thinking[x]}) wrote {judge_lines.more_or_fewer(rows, above)}: "
                   f"{judge_lines.ratios_text(rows, 'completion')}."
                   + (f" {tail[0][0].upper()}{tail[0][1:]}" + "".join(f"; {t}" for t in tail[1:]) + "." if tail else "")
                   + f" In all tokens, which count a prompt token like a completion token, its total is "
                     f"{judge_lines.sides_text(rows, c['all_tokens_in_total'][x]['above'])}; these are token figures and "
                     f"not prices.")
    for x in c["thinking_off"]:
        rows, above = c["by_judge"].get(x, []), c["completion_in_total"][x]["above"]
        out.append(f"{names[x]} ({thinking[x]}) wrote, in completion tokens and in total, "
                   f"{judge_lines.more_or_fewer(rows, above)}: {judge_lines.ratios_text(rows, 'completion')}; in all tokens "
                   f"its total is {judge_lines.sides_text(rows, c['all_tokens_in_total'][x]['above'])}.")
    return " ".join(out)


def render(data: dict[str, Any]) -> str:
    s = data["sections"]
    src = data["sources"]
    on = dt.date.fromisoformat(data["on"])
    name = month_name(data["month"])
    dates = data["prices"]
    out = [f"# Monthly review: {name}", "",
           f"Prepared on {day_name(on)} for {data['for']}, from the files chapter 16's lab kept, with no model and no "
           f"cloud call. The prices are the dated table's (`{src['prices']}`: {plural(dates['entries'], 'entry', 'entries')}, "
           f"each with its source and its date, {span(dates['first'], dates['last'])}), and every share of a budget is "
           f"of the manifest's `per_run_usd` or `per_month_usd`. Sections 1 to 5 and 7 read files that carry no month of "
           f"their own (the kept runs, the estimated volumes, step 6's simulated month, the register on the review's "
           f"date), and sections 6 and 8 read the records dated in {name}. Every table says what its figures are, in "
           f"{words(len(data['legend']))} words:", ""]
    out += [f"- {word}: {meaning}." for word, meaning in data["legend"].items()] + [""]

    r = s["runs_and_cost_per_run"]
    out += ["## 1. Runs and cost per run", ""] + basis_line(r, [src["ledger"], src["volumes"]])
    rows = [[w["workflow"].upper(), w["runs_kept"], num(w["runs_a_month"]), w["unit"] or "run",
             "; ".join(w["volume_sources"]), pair(w, "model_calls_a_run"), pair(w, "cost_per_run_usd", usd),
             pair(w, "pct_of_per_run_usd", pct), num(w["per_run_usd"])] for w in r["rows"]]
    out += table(["Workflow", "Runs kept (measured)", "Runs a month (estimated)", "Unit", "The volume's source",
                  f"Model calls a run, median / 95th ({r['reference_model']})",
                  f"Cost per run, median / 95th (USD, priced from the {r['reference_model']} tokens)",
                  "Of per_run_usd, median / 95th", "per_run_usd"], rows) + [""]
    partial = [w["workflow"].upper() for w in s["month_against_budget"]["rows"] if w["basis_of_the_per_run_figures"] != "measured"]
    out += [f"No median run costs more than {pct(r['highest_median']['pct'])} of its per-run budget "
            f"({r['highest_median']['workflow'].upper()}). The highest 95th percentile over every kept run and model is "
            f"{pct(r['highest_p95']['pct'])}, {r['highest_p95']['workflow'].upper()}'s on {r['highest_p95']['model']}."
            + (f" {join(partial)}'s per-run figures come from the runs that kept tokens, as the basis column of section 2 "
               f"says." if partial else ""), ""]
    rows = [[m["workflow"].upper(), m["model"], m["runs"], m["runs_with_tokens"], pair(m, "cost_per_run_usd", usd),
             pair(m, "pct_of_per_run_usd", pct)] for m in r["by_model"]]
    out += table(["Workflow", "Model", "Runs", "With tokens", "Cost per run, median / 95th (USD, priced)",
                  "Of per_run_usd, median / 95th"], rows) + [""]
    jd = r["judge"]
    out += [judge_paragraph(jd), ""]
    rows = [[w["workflow"].upper(), w["judge"], w["judgments"],
             f"{w['judge_tokens']['prompt']:,} / {w['judge_tokens']['completion']:,} / {w['judge_tokens']['total']:,}",
             f"{w['judged_tokens']['prompt']:,} / {w['judged_tokens']['completion']:,} / {w['judged_tokens']['total']:,}",
             " / ".join("none" if w["ratio"][k] is None else f"{w['ratio'][k]:.2f}" for k in ("prompt", "completion", "total")),
             f"{w['completion_over']:,}", w["basis"]] for w in jd["rows"]]
    out += table(["Workflow", "Judge", "Judgments (measured)", "Judge's tokens, prompt / completion / total",
                  "Judged outputs' tokens, prompt / completion / total", "Ratio, prompt / completion / total",
                  "Judgments with more completion tokens than the output", "Judged tokens' basis"], rows) + [""]

    m = s["month_against_budget"]
    out += ["## 2. The month against the monthly budget", ""] + basis_line(m, [src["ledger"], src["volumes"]])
    rows = [[w["workflow"].upper(), num(w["runs_a_month"]), f"{w['tokens_a_month']:,}", usd(w["mean_cost_per_run_usd"]),
             usd(w["direct_usd"]), num(w["per_month_usd"]), pct(w["pct_of_per_month_usd"]),
             "one kept run" if w["kept_runs_in_profile"] == 1
             else f"{pct(w['pct_range_over_kept_runs'][0])} to {pct(w['pct_range_over_kept_runs'][1])}",
             pct(w["recounted_as_nova_lite_pct"]), pct(w["guardrail_pct"]), w["basis_of_the_per_run_figures"]]
            for w in m["rows"]]
    out += table(["Workflow", "Runs a month (estimated)", "Tokens a month (estimated)", "Mean cost per run (USD, priced)",
                  "Direct cost (USD, estimated)", "per_month_usd", "Of per_month_usd", "Range over the kept runs",
                  "Recounted as Nova Lite", "Guardrail estimate, of per_month_usd", "Basis of the per-run figures"],
                 rows) + [""]
    out += [f"The largest month is {m['largest']['workflow'].upper()}'s, at {pct(m['largest']['pct'])} of its budget. The "
            f"guardrail column is the estimate step 2 made of chapter 6's Bedrock guardrail, which the cost lines don't "
            f"carry and which needs a line of its own in the ledger; it is shown so that the review doesn't read as if "
            f"the tokens were the whole bill.", ""]

    sh = s["shared_lines"]
    out += ["## 3. The shared lines", ""] + basis_line(sh, [src["ledger"], src["volumes"]])
    rows = [[w["workflow"].upper(), "yes" if w["tenant"] else "no", f"{w['restricted_tokens_a_month']:,}",
             pct(100 * w["token_share"]) if w["token_share"] is not None else "", usd(w["gpu_usd"]),
             pct(w["gpu_pct_of_per_month_usd"]), pct(100 * w["fixed_share"]), usd(w["fixed_usd"]),
             pct(w["fixed_pct_of_per_month_usd"]), usd(w["direct_usd"])] for w in sh["rows"]]
    rows.append(["idle, the platform team", "", "", "", usd(sh["gpu"]["idle_usd"]), "", "", "", "", ""])
    out += table(["Workflow", "Tenant of the self-hosted alias", "Tokens to it a month (estimated)", "Share of them",
                  "GPU hours (USD)", "Of per_month_usd", "Share of tokens, all aliases", "Fixed costs by tokens (USD)",
                  "Of per_month_usd", "Direct cost (USD), for comparison"], rows) + [""]
    # the stand-in lines are ledger/volumes.yaml's `stand_in` lines, EC2 and EBS priced in us-east-2
    n_parameters = len(sh["fixed"]["parameters"])
    out += [f"The GPUs are {sh['gpu']['replicas']} replicas for {sh['gpu']['hours']} hours at the table's price for "
            f"`{sh['gpu']['price']}`, {usd(sh['gpu']['usd'])} USD a month, of which the tenants used {usd(sh['gpu']['used_usd'])} "
            f"and {pct(100 * sh['gpu']['idle_share'], 5)} sat idle on the platform team's line; the tenants are "
            f"{', '.join(t.upper() for t in sh['tenants'])}, the workflows whose manifests list the alias. The platform's "
            f"fixed costs come to {usd(sh['fixed']['priced_usd'])} USD a month at the table's prices, "
            f"{usd(sh['fixed']['stand_in_usd'])} of them at us-east-2's EC2 prices standing in for ca-central-1's; "
            f"{words(n_parameters)} {'line has' if n_parameters == 1 else 'lines have'} no published price and "
            f"{'stays a parameter' if n_parameters == 1 else 'stay parameters'} outside the sum: "
            f"{', '.join(sh['fixed']['parameters'])}.", ""]

    e = s["error_budget"]
    out += ["## 4. The error budget left", ""] + basis_line(e, [f"{src['slo']}/kept.json", f"{src['slo']}/policy.json",
                                                                f"{src['slo']}/month.json"])
    rows = [[a["workflow"].upper(), a["sli"], pct(100 * a["target"], 4), "" if a["threshold_s"] is None else f"{num(a['threshold_s'])} s",
             f"{a['good']:,} / {a['valid']:,}" if a["valid"] else "no events",
             pct(100 * a["value"], 4) if a["value"] is not None else ""] for a in e["measured"]]
    out += table(["Workflow", "SLI", "Target", "Threshold", "Good / valid on the kept runs (measured)", "Measured"], rows) + [""]
    rows = [[a["workflow"].upper(), a["sli"], num(a["budget_events"]), a["bad"], pct(100 * a["used"], 4) if a["used"] is not None else "",
             left_cell(a), counts(a["causes"]) or "none"] for a in e["simulated"]]
    out += table(["Workflow", "SLI", "Error budget (events, simulated month)", "Bad events in the month", "Budget used",
                  "Budget left", "Bad events by cause"], rows) + [""]
    spent = e["spent"]
    out += [f"The simulated month starts on {e['month']['start'][:10]} (seed {e['month']['seed']}, {e['month']['days']} days). "
            f"{plural(len(spent), 'budget', lead=True)} {'was' if len(spent) == 1 else 'were'} spent in it: "
            + "; ".join(f"{a['workflow'].upper()} {a['sli']} on {a['spent_at']}" for a in spent)
            # slo/policy.yaml's rules, as the policy files record them
            + ". A spent budget freezes changes to the workflow's prompts and models, and a spent outcome budget also moves "
              "it down a rung (slo/policy.yaml); section 5 lists what followed.", ""]

    i = s["incidents"]
    out += ["## 5. Incidents", ""] + basis_line(i, [f"{src['slo']}/month.json", f"{src['slo']}/alerts.json",
                                                   f"{src['slo']}/policy.json", src["playbook"]])
    breaches = i["control_breaches"]
    if breaches["status"] == "listed":
        out += [f"Control breaches (residency, the never-list, the budgets) listed by `violation`: "
                f"{plural(len(breaches['kept_runs']), 'run')} of the kept runs and "
                f"{plural(len(breaches['simulated_month']), 'run')} of the simulated month. A breach is an incident "
                f"outside every error budget.", ""]
    else:
        out += [f"Control breaches (residency, the never-list, the budgets): not evaluated. {breaches['why'][0].upper()}"
                f"{breaches['why'][1:]}.", ""]
    rows = [[ev["id"], f"{ev['start']} to {ev['end']}", ev["symptom"],
             ", ".join(f"{w.upper()} {n:,}" for w, n in ev["runs_changed"].items()) or "none",
             ", ".join(f"{w.upper()} {n:,}" for w, n in ev["bad_events"].items()) or "none",
             "none" if ev["first_alert"] is None else
             f"{ev['first_alert']['action']}: {ev['first_alert']['scope'].upper()} {ev['first_alert']['sli']} "
             f"{ev['first_alert']['rule']}, {ev['first_alert']['start']}",
             "; ".join(f"{p['workflow'].upper()} {p['action']} ({p['sli']}, {p['at']}; {p['its_bad_events']} of the "
                       f"{p['bad_events_when_spent']} bad events when spent)" for p in ev["policy"]) or "none"]
            for ev in i["events"]]
    out += table(["Injected event (simulated)", "When (ET)", "The playbook's symptom", "Runs it changed", "Bad events",
                  f"First alert ({i['design']})", "Policy action it helped cause"], rows) + [""]
    rows = [[a["scope"].upper() if a["scope"] in data["workflows"] else a["scope"], counts(a["pages"]) or "none",
             counts(a["tickets"]) or "none"] for a in i["alerts_by_scope"]]
    out += table(["Scope", "Pages by cause (simulated)", "Tickets by cause (simulated)"], rows) + [""]
    rows = [[a["at"], a["workflow"].upper(), a["action"], a["sli"], a["decided_by"], a["change"] or ""] for a in i["policy_actions"]]
    out += table(["When (ET, simulated)", "Workflow", "Action", "SLI", "Decided by", "Change record"], rows) + [""]

    b = s["budget_events_and_switches"]
    out += [f"## 6. Budget events and switches pulled in {name}", ""] + basis_line(b, [src["drills"], src["changes"]])
    if b["alerts"]:
        rows = [[a["received_at"][:19], a["workflow"], a["event"], a["what"], num(a["spend_usd"], 7),
                 num(a["soft_budget_usd"]), num(a["max_budget_usd"]), usd(a["projected_usd"]),
                 ", ".join(a["forwarded_to"])] for a in b["alerts"]]
        out += table(["Received (UTC)", "Workflow", "Event", "What it is", "Spend (USD)", "Soft budget", "max_budget",
                      "Projected", "Forwarded to"], rows) + [""]
        blank = [a for a in b["alerts"] if a["soft_budget_usd"] is None]
        soft = {a["soft_budget_usd"] for a in b["alerts"] if a["soft_budget_usd"] is not None}
        one = len(blank) == 1
        if blank and all(a["projected_usd"] is not None for a in blank) and {a["max_budget_usd"] for a in blank} <= soft:
            out += [f"{words(len(blank)).capitalize()} of the {words(len(b['alerts']))} alerts {'shows' if one else 'show'} no "
                    f"soft budget: {'it is' if one else 'they are'} LiteLLM's projection {'alert' if one else 'alerts'}, which "
                    f"{'passes' if one else 'pass'} the soft budget as {'its' if one else 'their'} max_budget "
                    f"({join([num(v) for v in sorted({a['max_budget_usd'] for a in blank})])} here) and "
                    f"{'adds' if one else 'add'} a projected spend.", ""]
        elif blank:
            out += [f"{words(len(blank)).capitalize()} of the {words(len(b['alerts']))} alerts "
                    f"{'carries' if one else 'carry'} no soft budget.", ""]
    else:
        out += [f"No budget alert was received in {name}.", ""]
    if b["stop"]:
        st = b["stop"]
        out += [f"The stop: run {st['first_stopped_run']} of the drill got LiteLLM's {st['status']} ({st['kind']}) at its "
                f"second call, with the month at {num(st['month_before_usd'], 7)} of {num(st['max_budget_usd'])} USD before it; the "
                f"month stood at {num(st['month_after_usd'], 7)} when the drill ended, {usd(st['short_of_budget_usd'])} USD short "
                f"of its budget, since each stopped run's first call went through on a reservation cut to fit.", ""]
    else:
        out += [f"No budget stop is recorded for {name}.", ""]
    if b["changes"]:
        rows = [[c["change"], "; ".join(f"{st['lever']} ({st['from']} to {st['to']})" for st in c["steps"]), c["workflow"],
                 c["by"], c["first_at"][:19], c["document_by"][:19], c["run"]] for c in b["changes"]]
        out += table(["Change", "Lever (from, to)", "Workflow or alias", "By", "At (UTC)", "Document by (UTC)", "Run as"],
                     rows) + [""]
        rule = b["rule"]
        article = "an" if rule["kinds"][0][0] in "aeiou" else "a"
        out += [f"{plural(len(b['changes']), 'change', lead=True)} left {plural(sum(c['lines'] for c in b['changes']), 'record line')} "
                f"in the month, each {article} {' or '.join(rule['kinds'])} change by the {' or '.join(rule['authority'])}, to "
                f"be documented within {' or '.join(str(h) for h in rule['hours'])} hours and reviewed at "
                f"{' or '.join(rule['review'])} (ch02:163).", ""]
    else:
        out += [f"No change record is dated in {name}.", ""]

    t = s["retirement"]
    out += [f"## 7. Models within {t['windows']['review_days']} days of retirement on {day_name(on)}", ""]
    out += basis_line(t, [src["register"], src["retirement_rules"]])
    rows = [[r["model"], r["cloud"], "yes" if r["pinned"] else "no", r["stage"], r["retires"], r["days_left"],
             ", ".join(r["fires"]) or "none"] for r in t["rows"]]
    out += table(["Model", "Cloud", "Larkspur runs on it", "Stage", "Retires (recorded)", "Days left", "What fires"], rows) + [""]
    pinned = [r for r in t["rows"] if r["pinned"]]
    passed = [u for u in t["unscheduled"] if u["earliest_passed"]]
    n_unscheduled = len(t["unscheduled"])
    if not passed:
        passed_text = ""
    elif n_unscheduled == 1:
        passed_text = (f", and the provider's earliest possible date for it has passed ({passed[0]['model']}), so a notice "
                       f"can come any day")
    else:
        every = "both" if n_unscheduled == 2 else "all"
        passed_text = (f", and for {every if len(passed) == n_unscheduled else words(len(passed))} of them the provider's "
                       f"earliest possible date has passed ({', '.join(u['model'] for u in passed)}), so a notice can come "
                       f"any day")
    out += [f"{plural(len(t['rows']), 'model', lead=True)} {'is' if len(t['rows']) == 1 else 'are'} inside the window, "
            f"{words(len(pinned))} of them behind a Larkspur alias"
            + (f" ({', '.join(r['model'] for r in pinned)})" if pinned else "")
            + f". The rules fired {plural(t['pages'], 'page')}, {plural(t['tickets'], 'ticket')}, and "
              f"{plural(t['review_rows'], 'review row')}. {plural(n_unscheduled, 'model', lead=True)} "
              f"{'has' if n_unscheduled == 1 else 'have'} no published retirement date{passed_text}.", ""]

    v = s["w5_savings"]
    out += ["## 8. W5's savings, and what finding them cost", ""] + basis_line(v, [v["ledger"], src["ledger"], src["prices"]])
    sv, pr, f = v["savings"], v["pull_requests"], v["findings"]
    if not v["nights"]:
        out += [f"W5 ran no night and no alarm in {name}: its ledger holds no row for the month, so there are no savings, "
                f"pull requests, or cost of finding them to read.", ""]
    else:
        rows = [[pct(100 * sv["proposed_share_of_spend"]), f"open {pr['open']}, merged {pr['merged']}, closed {pr['closed']}",
                 pct(100 * sv["realized_share_of_spend"]), pct(100 * sv["realized_share_of_proposed"], 4), sv["realized_findings"],
                 f"{f['seen']} seen, {f['with_estimate']} with an estimate, {f['suppressed']} suppressed",
                 f"{v['nights']}: " + ", ".join(f"{n} {'scheduled night' if kind == 'schedule' else 'alarm run'}"
                                                 f"{'' if n == 1 else 's'}" for kind, n in v["night_kinds"].items())]]
        out += table(["Proposed, share of the accounts' spend", "Pull requests by state", "Realized, share of spend",
                      "Realized, share of proposed", "Findings realized", "Findings", "Runs in the month"], rows) + [""]
        a, p = v["agent"], v["priced"]
        rows = [[a["gateway_calls"], f"{a['prompt_tokens']:,}", f"{a['completion_tokens']:,}", num(a["seconds"]),
                 pct(p["pct_of_per_month_usd"]),
                 pct(100 * p["share_of_realized_saving"]) if p["share_of_realized_saving"] is not None else "",
                 f"{v['range_over_kept_runs']['completion_tokens'][0]:,} to {v['range_over_kept_runs']['completion_tokens'][1]:,} "
                 f"completion tokens, {num(v['range_over_kept_runs']['seconds'][0])} to {num(v['range_over_kept_runs']['seconds'][1])} s, "
                 f"over {v['range_over_kept_runs']['runs']} kept runs"]]
        out += table(["Gateway calls (measured)", "Prompt tokens", "Completion tokens", "Seconds",
                      f"Cost to find, of per_month_usd (priced at {p['deployment']})", "Cost to find, of the saving realized",
                      "Range over W5's kept runs on the same model"], rows) + [""]
        pn, others = v["per_night"], v["other_kept_runs"]
        out += [f"W5 proposed savings worth {pct(100 * sv['proposed_share_of_spend'])} of the {words(len(a['accounts_read']))} "
                f"accounts' month. People merged {pr['merged']} of its {pr['open'] + pr['merged'] + pr['closed']} pull "
                f"requests, and the ledger realized {sv['realized_findings']} finding"
                f"{'' if sv['realized_findings'] == 1 else 's'}: {pct(100 * sv['realized_share_of_proposed'], 4)} of what was "
                f"proposed and {pct(100 * sv['realized_share_of_spend'])} of the spend, when a later night found the resource "
                f"gone. Finding them cost {a['gateway_calls']} gateway calls and {a['prompt_tokens'] + a['completion_tokens']:,} "
                f"tokens over {v['nights']} runs, {pct(p['pct_of_per_month_usd'])} of W5's monthly budget"
                + (f" and {pct(100 * p['share_of_realized_saving'])} of the saving it realized"
                   if p["share_of_realized_saving"] is not None else "")
                + f". A night costs {pct(pn['pct_of_per_run_usd']['median'])} of its per-run budget at the median and "
                  f"{pct(pn['pct_of_per_run_usd']['p95'])} at the 95th percentile on {pn['model']} (section 1)."
                + (f" The savings are the same in each of the other {words(len(others))} kept runs on {pn['model']}, since the "
                   f"ledger computes them from the detectors' estimates and the merge and never from the prose; the agent's "
                   f"cost differs by run, hence the range." if others and all(o["same_savings"] for o in others) else ""), ""]

    out += ["## Sources", ""]
    out += [f"- {k.replace('_', ' ')}: " + (", ".join(f"`{x}`" for x in val) if isinstance(val, list) else f"`{val}`")
            for k, val in src.items()] + [""]
    return "\n".join(out)


def write(out: Path, month: str, on: dt.date, sources: Sources | None = None) -> dict[str, Any]:
    """The page and its JSON, written together or not at all: both are made before either is written, and each goes to
    a temporary file in the folder before it is renamed into place."""
    sources = sources or Sources.committed()
    data = build(month, on, sources)
    page = render(data)
    out.mkdir(parents=True, exist_ok=True)
    pending = [(out / FILES[1].format(month=month), json.dumps(data, indent=1, ensure_ascii=False) + "\n"),
               (out / FILES[0].format(month=month), page)]
    temps = []
    try:
        for path, text in pending:
            temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            temp.write_text(text, encoding="utf-8", newline="\n")
            temps.append((temp, path))
        for temp, path in temps:
            os.replace(temp, path)
    finally:
        for temp, _ in temps:
            temp.unlink(missing_ok=True)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--month", default="2026-11", help="the month, YYYY-MM")
    parser.add_argument("--on", type=dt.date.fromisoformat, default=dt.date(2026, 11, 9), help="the review's date")
    parser.add_argument("--out", type=Path, required=True, help="the folder for review-<month>.md and its JSON")
    args = parser.parse_args(argv)
    dt.datetime.strptime(args.month, "%Y-%m")
    offline.block_network()
    write(args.out, args.month, args.on)
    print(f"wrote {', '.join(f.format(month=args.month) for f in FILES)} to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
