"""SIMULATED: the month the alerts and the error-budget policy run over, seeded and reproducible.

Chapter 16, step 6 (companion #14, O-D12). month.yaml says what the month is built from, and this module builds it:

- the volumes: each workflow's runs a month from the ledger's month (results/<date>/ledger.json, which reads
  ledger/volumes.yaml), at that rate an hour, every hour alike; W5 once a night at 02:00 ET and four alarm runs;
- the runs: each one a kept run of its workflow on the reference model, drawn with replacement from the pools
  month.yaml names, keeping the kept run's end, time, and calls by alias (slis.kept_events, costlines.collect);
- the decisions on W3's, W4's and W5's proposals: month.yaml's stated assumptions, since no kept run holds a
  person's decision;
- the five injected events, each changing the runs it touches, which then carry its id in `injected`;
- the hourly probe's runs for the workflows alerts.yaml names, which only the alerts count;
- the gateway's records the dashboard reads beside the runs: the 429s each workflow saw, the calls a fallback
  served, the calls that failed.

Each workflow draws from a random generator of its own, seeded with the month's seed and its name, so a change to
one workflow's draws leaves the others' as they were. Times are seconds from 00:00 ET on the month's first day; the
lead-in's are negative. The month's timezone is ET at UTC-5 throughout: it holds no change of clocks.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "ledger", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import costlines  # noqa: E402
import probe  # noqa: E402
import registry  # noqa: E402
import slis  # noqa: E402

MONTH = HERE / "month.yaml"
ALERTS = HERE / "alerts.yaml"
LEDGER_MONTH = LAB / "results" / "2026-11-03" / "ledger.json"
DRILLS = LAB / "results" / "2026-11-03" / "capacity" / "drills.json"
OUTAGE_CONFIG = LAB / "capacity" / "litellm.outage-canada.yaml"
ET = timezone(timedelta(hours=-5), "ET")
HOUR, DAY = 3600.0, 86400.0
MANAGED = "larkspur-chat"
NO_FALLBACK = ("w4", "w5")   # their manifests list larkspur-chat alone: no fallback hop to give (step 5b)
STUB_SEAMS = ("w4", "w5")    # a failed model call writes the stub sentence and the run goes on


@dataclass(frozen=True)
class Draw:
    """One kept run as the month draws it."""
    workflow: str
    kept_run: str
    case: str
    end: str
    seconds: float
    managed_calls: int
    restricted_calls: int
    first_call_seconds: float | None
    opened: int = 0
    trigger: str = "schedule"


@dataclass
class Month:
    config: dict[str, Any]
    events: list[slis.RunEvent] = field(default_factory=list)
    probes: list[slis.RunEvent] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    shapes: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, dict[str, float]] = field(default_factory=dict)

    def real(self, workflow: str | None = None) -> list[slis.RunEvent]:
        return [e for e in self.events if workflow is None or e.workflow == workflow]


def load(path: Path = MONTH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def start_of(config: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(config["start"]).astimezone(ET)


def clock(config: dict[str, Any], t: float) -> str:
    """A month time as ET wall time, for the summary: "Mon 11 Jan 10:00"."""
    return (start_of(config) + timedelta(seconds=t)).strftime("%a %d %b %H:%M")


def day_time(config: dict[str, Any], day: int, hhmm: str) -> float:
    hours, minutes = (int(x) for x in hhmm.split(":"))
    return day * DAY + hours * HOUR + minutes * 60.0


def windows(config: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """Each injected event's start and end, seconds from the month's start."""
    out = {}
    for item in config["injected"]:
        begin = day_time(config, item["start_day"], item["start"])
        end = config["days"] * DAY if "minutes" not in item else begin + item["minutes"] * 60.0
        out[item["id"]] = (begin, end)
    return out


def injected(config: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in config["injected"] if item["id"] == name)


# --- what the month is built from -------------------------------------------------------------------------

def runs_per_hour(path: Path = LEDGER_MONTH) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))["month"]
    hours = data["month_hours"]
    return {row["workflow"]: row["runs_per_month"] / hours for row in data["rows"]}


def throttle_shape(path: Path = DRILLS) -> dict[str, float]:
    """Step 5's retry drill through step 4's gateway with Retry-After honored: the shares of calls the provider
    took at once, served after a wait, and never served."""
    rows = json.loads(path.read_text(encoding="utf-8"))["client_retries"]
    row = next(r for r in rows if r["through"] == "step 4's gateway" and r["policy"] == "honour")
    requests = row["requests_in_the_minute"]
    refused_first = row["provider_refusals_in_the_minute"]
    never = requests - row["served"]
    return {"requests": requests, "refused_at_first_attempt": refused_first, "served": row["served"],
            "never": never, "p_never": never / requests, "p_waited": (refused_first - never) / requests,
            "p_at_once": (requests - refused_first) / requests}


def w3_time_budget_s() -> float:
    """W3's own time budget for waiting out a 429 (harness/loop.py, step 5b)."""
    with registry.isolated(("workflows/w3-incident/harness",)):
        import loop
        return float(loop.TIME_BUDGET_S)


def alarms_per_hour(path: Path = LAB / "ledger" / "volumes.yaml") -> float:
    volumes = yaml.safe_load(path.read_text(encoding="utf-8"))
    return volumes["workflows"]["w5"]["parts"]["alarms"]["runs"] / volumes["month_hours"]


def outage_timeout_s(path: Path = OUTAGE_CONFIG) -> float:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    primary = next(d for d in config["model_list"] if d["model_name"] == MANAGED)
    return float(primary["litellm_params"]["timeout"])


def outage_cooldown_s(path: Path = OUTAGE_CONFIG) -> float:
    """The router's cooldown in step 5b's outage config, which is the retry-after its 429 names while the primary is
    cooled down (step 5: "Try again in 30 seconds", retry-after 30)."""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    return float(config["router_settings"]["cooldown_time"])


def draws(config: dict[str, Any], kept: dict[str, list[slis.RunEvent]] | None = None) -> dict[str, dict[str, list[Draw]]]:
    """The pools of month.yaml as Draws: {workflow: {"<model> <label>": [Draw, ...]}}."""
    kept = kept if kept is not None else slis.kept_events()
    model = config["pools"]["reference_model"]
    by_id = {r.run_id: r for r in costlines.collect(slis.WORKFLOWS)}
    labels: dict[str, set[str]] = {w: set(config["pools"]["baseline"][w]) for w in slis.WORKFLOWS}
    for item in config["injected"]:
        for w, pool in (item.get("pools") or {}).items():
            labels[w] |= set(pool)
    out: dict[str, dict[str, list[Draw]]] = {w: {} for w in slis.WORKFLOWS}
    for key, events in kept.items():
        workflow, name = key.split(" ", 1)
        run_model, label = name.split(" ", 1)
        if run_model != model or label not in labels[workflow]:
            continue
        pool = []
        for e in events:
            if e.unit != "run":
                continue
            run = by_id[e.run_id]
            managed = sum(1 for line in run.lines if line.alias == MANAGED)
            restricted = sum(1 for line in run.lines if line.alias == costlines.RESTRICTED_ALIAS)
            first = run.lines[0].duration_ms / 1000 if run.lines and run.lines[0].duration_ms is not None else None
            opened, trigger = 0, "schedule"
            if workflow == "w5":
                trigger = "alarm" if run.case.startswith("alarm") else "schedule"
            pool.append(Draw(workflow, name, run.case, e.end, float(e.seconds or 0.0), managed, restricted, first,
                             opened, trigger))
        out[workflow][label] = pool
    for workflow, wanted in labels.items():
        missing = sorted(wanted - set(out[workflow]))
        if missing:
            raise ValueError(f"{workflow}: month.yaml names kept runs that aren't there: {missing}")
    return out


def w5_opened() -> int:
    """The pull requests W5's kept steady-state night opened: golden night-2, the same in every kept run."""
    seen = set()
    for kept in registry.kept_runs("w5"):
        night = registry.outputs(kept).get("night-2")
        if night:
            seen.add(night["record"]["counts"]["pull_requests"]["opened"])
    if len(seen) != 1:
        raise ValueError(f"W5's kept night-2 opened {sorted(seen)} pull requests across its kept runs")
    return seen.pop()


# --- the month --------------------------------------------------------------------------------------------

def _pool(pools: dict[str, list[Draw]], labels: list[str], trigger: str | None = None) -> list[Draw]:
    out = [d for label in labels for d in pools[label] if trigger is None or d.trigger == trigger]
    if not out:
        raise ValueError(f"no kept run to draw from in {labels} ({trigger})")
    return out


def _arrivals(rng: random.Random, per_hour: float, begin: float, end: float) -> list[float]:
    times, t = [], begin
    while True:
        t += rng.expovariate(per_hour / HOUR)
        if t >= end:
            return times
        times.append(t)


def next_board(config: dict[str, Any], t: float) -> float:
    """The next Thursday session at 14:00 ET after t (ch13:18)."""
    moment = start_of(config) + timedelta(seconds=t)
    days = (3 - moment.weekday()) % 7
    session = (moment + timedelta(days=days)).replace(hour=14, minute=0, second=0, microsecond=0)
    if session <= moment:
        session += timedelta(days=7)
    return (session - start_of(config)).total_seconds()


class Builder:
    """Applies the injections to one run at a time, in month.yaml's order, and keeps the gateway's records."""

    def __init__(self, config: dict[str, Any], month: Month, opened: int) -> None:
        self.config, self.month, self.opened = config, month, opened
        self.windows = windows(config)
        self.throttle = throttle_shape()
        self.timeout_s = outage_timeout_s()
        self.cooldown_s = outage_cooldown_s()
        regression = injected(config, "model-regression")
        self.regression_pools = regression.get("pools") or {}
        self.w3_regressed_accept = regression["w3_accept"]
        self.w3_time_budget_s = w3_time_budget_s()
        month.shapes = {"throttle": self.throttle, "outage_timeout_s": self.timeout_s,
                        "outage_cooldown_s": self.cooldown_s, "w5_opened": opened,
                        "windows": {k: list(v) for k, v in self.windows.items()}}

    def inside(self, name: str, t: float) -> bool:
        begin, end = self.windows[name]
        return begin <= t < end

    def record(self, t: float, workflow: str, kind: str, injected_by: str, probe: bool = False, **more: Any) -> None:
        self.month.records.append({"at": round(t, 3), "workflow": workflow, "kind": kind, "injected": injected_by,
                                   "probe": probe, **more})

    def run(self, rng: random.Random, draw: Draw, t: float, run_id: str, probe: bool = False) -> slis.RunEvent:
        """One run started at t: the kept run's end and time, changed by any injected event it falls in."""
        workflow, end, seconds, tag = draw.workflow, draw.end, draw.seconds, None
        managed = 1 if probe else draw.managed_calls
        restricted = 0 if probe else draw.restricted_calls
        if probe:
            seconds = draw.first_call_seconds or 0.0
        if managed and self.inside("provider-outage", t):
            tag = "provider-outage"
            seconds += self.timeout_s * managed  # every call waits the primary's timeout first, an upper bound
            if workflow in NO_FALLBACK and probe:
                end = "error"  # the probe sends one call and waits out no 429
                self.record(t, workflow, "failed", tag, probe, calls=managed, why="no fallback hop: the timeout")
            elif workflow in NO_FALLBACK:
                # the cooldown's 429 names its retry-after; step 5b's seams wait it out once, then write the stub
                seconds += self.cooldown_s * managed
                self.record(t, workflow, "failed", tag, probe, calls=managed,
                            why="no fallback hop: the timeout, one wait of the cooldown's retry-after, the stub")
            else:
                self.record(t, workflow, "fallback", tag, probe, calls=managed, served_by="larkspur-chat-restricted")
        if managed and self.inside("throttled-hour", t):
            refused, waited, throttled = 0, 0.0, 0
            for _ in range(managed):
                u = rng.random()
                if u < self.throttle["p_never"]:
                    refused, throttled, waited = refused + 1, throttled + 1, waited + 60.0
                elif u < self.throttle["p_never"] + self.throttle["p_waited"]:
                    throttled += 1
                    waited += rng.uniform(1.0, 60.0)
            if throttled:
                tag = "throttled-hour"
                seconds += waited
                self.record(t, workflow, "provider_429", tag, probe, calls=throttled, refused=refused,
                            waited_s=round(waited, 3))
                over_budget = workflow == "w3" and not probe and waited > self.w3_time_budget_s
                if (refused or over_budget) and (probe or workflow not in STUB_SEAMS):
                    end = "unavailable" if workflow == "w3" and not probe else "error"
        if restricted and self.inside("self-hosted-down", t):
            tag = "self-hosted-down"
            self.record(t, workflow, "failed", tag, probe, calls=restricted, why="the self-hosted alias is down")
            if end in slis.GOOD:
                end = "unavailable" if workflow == "w3" else "error"
        if workflow == "w4" and not probe and self.inside("w4-records-refused", t) and end in slis.GOOD:
            tag, end = "w4-records-refused", "error"
        if tag is not None and not probe and draw.end in slis.BAD and end == draw.end:
            tag = None  # the kept run it was drawn from had failed already; the injection only added time
        regressed = workflow in self.regression_pools or (workflow == "w3" and end == "proposal")
        if tag is None and not probe and regressed and self.inside("model-regression", t):
            tag = "model-regression"
        event = slis.RunEvent(workflow, run_id, end, round(seconds, 3), at=round(t + seconds, 3), probe=probe,
                              restricted=bool(restricted), injected=tag, source=f"{draw.kept_run} {draw.case}",
                              reason=draw.trigger if workflow == "w5" else "")
        return self.decide(rng, event)

    def decide(self, rng: random.Random, e: slis.RunEvent) -> slis.RunEvent:
        """A person's decision on a W3 or W4 proposal, by month.yaml's assumptions; W5's are events of their own."""
        if e.probe or e.end != "proposal" or e.workflow not in ("w3", "w4"):
            return e
        spec = self.config["decisions"][e.workflow]
        if rng.random() >= spec["decided"]:
            return e
        if e.workflow == "w3":
            accept = self.w3_regressed_accept if self.inside("model-regression", e.at) else spec["accept"]
            when = e.at + rng.uniform(*spec["delay_minutes"]) * 60.0
            if rng.random() < accept:
                decision = "reverted" if rng.random() < spec["revert_of_accepted"] else "accepted"
            else:
                decision = "rejected"
        else:
            when = next_board(self.config, e.at)
            decision = "accepted" if rng.random() < spec["accept"] else "rejected"
        return replace(e, decision=decision, decided_at=round(when, 3))

    def w5_decisions(self, rng: random.Random, night: slis.RunEvent) -> list[slis.RunEvent]:
        if night.end != "proposal" or night.reason != "schedule":
            return []
        spec, out = self.config["decisions"]["w5"], []
        for i in range(self.opened):
            if rng.random() >= spec["decided"]:
                continue
            when = night.at + rng.uniform(*spec["delay_hours"]) * HOUR
            decision = "accepted" if rng.random() < spec["accept"] else "rejected"
            out.append(slis.RunEvent("w5", f"{night.run_id}:pr{i + 1}", "proposal", None, at=night.at,
                                     decision=decision, decided_at=round(when, 3), injected=night.injected,
                                     source=night.source, reason="pull request", unit="decision"))
        return out


def build(config: dict[str, Any] | None = None, alerts: dict[str, Any] | None = None,
          kept: dict[str, list[slis.RunEvent]] | None = None) -> Month:
    config = config or load()
    alerts = alerts or yaml.safe_load(ALERTS.read_text(encoding="utf-8"))
    if not config.get("simulated"):
        raise ValueError("month.yaml must say simulated: true")
    pools = draws(config, kept)
    month = Month(config)
    builder = Builder(config, month, w5_opened())
    rates = runs_per_hour()
    begin, end = -config["lead_in_days"] * DAY, config["days"] * DAY
    regress_at = windows(config)["model-regression"][0]
    baseline = config["pools"]["baseline"]
    for workflow in slis.WORKFLOWS:
        rng = random.Random(f"{config['seed']}:{workflow}")
        regressed = builder.regression_pools.get(workflow)
        if workflow == "w5":
            nights = [d * DAY + 2 * HOUR for d in range(-config["lead_in_days"], config["days"])]
            alarms = _arrivals(rng, alarms_per_hour(), begin, end)
            starts = sorted([(t, "schedule") for t in nights] + [(t, "alarm") for t in alarms])
            for n, (t, trigger) in enumerate(starts):
                labels = regressed if regressed and t >= regress_at else baseline["w5"]
                draw = rng.choice(_pool(pools["w5"], labels, trigger))
                event = builder.run(rng, draw, t, f"w5:{n:04d}")
                month.events.append(event)
                month.events += builder.w5_decisions(rng, event)
            continue
        for n, t in enumerate(_arrivals(rng, rates[workflow], begin, end)):
            labels = regressed if regressed and t >= regress_at else baseline[workflow]
            draw = rng.choice(_pool(pools[workflow], labels))
            month.events.append(builder.run(rng, draw, t, f"{workflow}:{n:06d}"))
    for workflow, case in probe.cases(alerts).items():
        rng = random.Random(f"{config['seed']}:probe:{workflow}")
        draw = Draw(workflow, case.kept_run, case.case, "answer", case.seconds or 0.0, 1, 0, case.seconds)
        hour = int(begin // HOUR)
        while hour * HOUR < end:
            t = hour * HOUR + alerts["probe"]["minute"] * 60.0
            month.probes.append(builder.run(rng, draw, t, f"probe:{workflow}:{hour:+05d}", probe=True))
            hour += 1
    month.events.sort(key=lambda e: (e.at, e.run_id))
    month.records.sort(key=lambda r: (r["at"], r["workflow"], r["kind"]))
    month.expected = expected(config, pools, rates, builder.opened)
    return month


def expected(config: dict[str, Any], pools: dict[str, dict[str, list[Draw]]], rates: dict[str, float],
             opened: int) -> dict[str, dict[str, float]]:
    """The valid events each SLI expects in the month at baseline, the denominator of its error budget in events."""
    hours = config["days"] * 24
    out = {}
    for workflow in slis.WORKFLOWS:
        pool = [d for label in config["pools"]["baseline"][workflow] for d in pools[workflow][label]]
        if workflow == "w5":
            runs = config["days"] + alarms_per_hour() * hours
            nights = [d for d in pool if d.trigger == "schedule"]
            share = Counter(d.end for d in nights)
            good = sum(share[e] for e in slis.GOOD) / len(nights)
            decided = config["days"] * opened * config["decisions"]["w5"]["decided"]
            out[workflow] = {"success": runs, "latency": runs * good, "outcome": decided}
            continue
        runs = rates[workflow] * hours
        share = Counter(d.end for d in pool)
        good = sum(share[e] for e in slis.GOOD) / len(pool)
        proposals = share["proposal"] / len(pool)
        decided = config["decisions"].get(workflow, {}).get("decided", 0.0)
        out[workflow] = {"success": runs, "latency": runs * good, "outcome": runs * proposals * decided}
    return out


def main(argv: list[str] | None = None) -> int:
    month = build()
    counts = Counter((e.workflow, e.end) for e in month.events if e.unit == "run" and e.at >= 0)
    print(json.dumps({f"{w} {end}": n for (w, end), n in sorted(counts.items())}, indent=1))
    print(len(month.probes), "probe runs;", len(month.records), "gateway records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
