"""The alerts over a stream of runs: multiwindow burn rates, W5's failed nights, and the platform's 429s.

Chapter 16, step 6 (companion #14, O-D12, O-D17). No paging service runs (O-D17): `evaluate` says what would page
and what would open a ticket, and when. alerts.yaml holds the rules:

- burn rate: "how fast, relative to the SLO, the service consumes the error budget" (fact sheet 6), the bad share
  of a window's valid events over 1 minus the target. The workbook's table pages at 14.4 over one hour and at 6 over
  six hours and opens a ticket at 1 over three days. A rule with a short window fires only while both windows burn
  that fast; the table pairs the three long windows with 5 minutes, 30 minutes and 6 hours (fact sheet 9.4), a twelfth
  of each, and alerts.yaml sets them. A window with no valid event has no burn, so a short window can be empty.
- W5's nights: each failed or late night opens a ticket, and so does the month's budget of failed nights spent.
- the platform: a provider's 429s reaching two or more workflows within five minutes page (ch05:498).

A stream places each event at the time it becomes known (slis.placed): a run when it ends, an outcome when a
person decides, which is how the month's tables and the budgets count them too. The lead-in's runs and decisions
are in the streams, so the windows are full from the month's first day.

An alert is an episode: the evaluations in a row at which its condition held, from the first to the first that
didn't. A condition that holds again within the rule's long window of the episode's end continues the same alert,
so one burst that dips and returns is one page; one that returns a long window or more after the end is a new page.
It is put down to an injected event when more than half of the bad events in its (long) window at the first
evaluation carry that event's id, and to the baseline otherwise.
"""

from __future__ import annotations

import bisect
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import slis

ACTIONS = ("page", "ticket")


@dataclass(frozen=True)
class Stream:
    """One SLI's valid events in time order: when each was known, whether it was bad, and what injected it."""
    scope: str            # a workflow, or "group:w1+w3+w4"
    sli: str
    target: float
    times: tuple[float, ...]
    bad: tuple[bool, ...]
    tags: tuple[str | None, ...]
    prefix: tuple[int, ...] = field(default=())

    @classmethod
    def of(cls, scope: str, sli: str, target: float, events: list[slis.RunEvent],
           threshold_s: float | None = None) -> Stream:
        rows = []
        for e in events:
            verdict = slis.classify(e, sli, threshold_s)
            when = slis.placed(e, sli)
            if verdict is None or when is None:
                continue
            rows.append((when, not verdict, e.injected, e.run_id))
        rows.sort(key=lambda r: (r[0], r[3]))
        prefix = [0]
        for _, is_bad, _, _ in rows:
            prefix.append(prefix[-1] + int(is_bad))
        return cls(scope, sli, target, tuple(r[0] for r in rows), tuple(r[1] for r in rows),
                   tuple(r[2] for r in rows), tuple(prefix))

    def window(self, end: float, hours: float) -> tuple[int, int, int, int]:
        """(first index, last index + 1, valid, bad) of the events in (end - hours, end]."""
        lo = bisect.bisect_right(self.times, end - hours * 3600.0)
        hi = bisect.bisect_right(self.times, end)
        return lo, hi, hi - lo, self.prefix[hi] - self.prefix[lo]

    def burn(self, end: float, hours: float) -> float:
        _, _, valid, bad = self.window(end, hours)
        return 0.0 if not valid else (bad / valid) / (1.0 - self.target)

    def attribution(self, end: float, hours: float) -> tuple[str, dict[str, int]]:
        lo, hi, _, bad = self.window(end, hours)
        counts = Counter(self.tags[i] or "baseline" for i in range(lo, hi) if self.bad[i])
        top, n = (counts.most_common(1)[0] if counts else ("baseline", 0))
        return (top if top != "baseline" and n * 2 > bad else "baseline"), dict(sorted(counts.items()))


@dataclass(frozen=True)
class Alert:
    design: str
    scope: str
    sli: str
    rule: str
    action: str
    start: float
    end: float | None      # None: still firing at the month's end
    peak: float            # the highest burn rate over the episode, or the count for a night's rule
    cause: str             # an injected event's id, or "baseline"
    bad_by_cause: dict[str, int]

    def as_json(self) -> dict[str, Any]:
        return {"design": self.design, "scope": self.scope, "sli": self.sli, "rule": self.rule, "action": self.action,
                "start_s": round(self.start, 1), "end_s": None if self.end is None else round(self.end, 1),
                "peak": round(self.peak, 3), "cause": self.cause, "bad_by_cause": self.bad_by_cause}


def episodes(stream: Stream, rule: dict[str, Any], design: str, begin: float, end: float,
             step_s: float) -> list[Alert]:
    """The episodes of one burn-rate rule over one stream, evaluated every step_s seconds in [begin, end)."""
    out: list[Alert] = []
    long_h, short_h, rate = rule["long_window_hours"], rule.get("short_window_hours"), rule["burn_rate"]
    current: dict[str, Any] | None = None
    t = begin
    while t < end:
        burn = stream.burn(t, long_h)
        firing = burn >= rate and (short_h is None or stream.burn(t, short_h) >= rate)
        if firing and current is None:
            last = out[-1] if out else None
            if last is not None and last.end is not None and t - last.end < long_h * 3600.0:
                out.pop()  # the same alert, firing again inside its window: it continues
                current = {"start": last.start, "peak": max(last.peak, burn), "cause": last.cause,
                           "counts": last.bad_by_cause}
            else:
                cause, counts = stream.attribution(t, long_h)
                current = {"start": t, "peak": burn, "cause": cause, "counts": counts}
        elif firing:
            current["peak"] = max(current["peak"], burn)
        elif current is not None:
            out.append(Alert(design, stream.scope, stream.sli, rule["name"], rule["action"], current["start"], t,
                             current["peak"], current["cause"], current["counts"]))
            current = None
        t += step_s
    if current is not None:
        out.append(Alert(design, stream.scope, stream.sli, rule["name"], rule["action"], current["start"], None,
                         current["peak"], current["cause"], current["counts"]))
    return out


def night_alerts(events: list[slis.RunEvent], spec: dict[str, Any], target: float, threshold_s: float,
                 budget_nights: float, design: str) -> list[Alert]:
    """W5: a ticket for each failed night and each late one, and one when the month's failed runs reach the budget,
    at the failed run that brings their count to the budget or past it, as budget_policy.spent counts a budget spent
    (3.4 at 90 percent of about 34 runs: three failed runs fit inside it and the fourth spends it)."""
    out: list[Alert] = []
    failed, budget_spent = 0, False
    runs = sorted((e for e in events if e.unit == "run" and e.at is not None and e.at >= 0), key=lambda e: e.at)
    for e in runs:
        cause = e.injected or "baseline"
        if slis.success_valid(e) and not slis.success_good(e):
            failed += 1
            out.append(Alert(design, "w5", "success", "failed-night", "ticket", e.at, None, 1, cause, {cause: 1}))
            if not budget_spent and failed >= budget_nights:
                budget_spent = True
                out.append(Alert(design, "w5", "success", "nights-budget-spent", "ticket", e.at, None, failed, cause,
                                 {cause: failed}))
        elif slis.latency_valid(e) and not slis.latency_good(e, threshold_s):
            out.append(Alert(design, "w5", "latency", "late-night", "ticket", e.at, None, 1, cause, {cause: 1}))
    return out


def platform_alerts(records: list[dict[str, Any]], window_s: float = 300.0, keep_open_s: float = 3600.0) -> list[Alert]:
    """ch05:498: the platform's on-call is paged when a provider's 429s reach two or more workflows in 5 minutes. A
    page stays open for an hour after the last 429 that held the condition, so one throttled hour is one page."""
    hits = sorted((r["at"], r["workflow"], r["injected"]) for r in records if r["kind"] == "provider_429")
    out: list[Alert] = []
    current: dict[str, Any] | None = None
    for i, (t, _, _) in enumerate(hits):
        recent = [(w, c) for (u, w, c) in hits[: i + 1] if t - window_s < u <= t]
        workflows = {w for w, _ in recent}
        if len(workflows) >= 2:
            causes = Counter(c or "baseline" for _, c in recent)
            if current is None or t - current["last"] > keep_open_s:
                if current is not None:
                    out.append(_platform(current, keep_open_s))
                current = {"start": t, "last": t, "peak": len(workflows), "causes": causes}
            else:
                current["last"], current["peak"] = t, max(current["peak"], len(workflows))
                current["causes"].update(causes)
    if current is not None:
        out.append(_platform(current, keep_open_s))
    return out


def _platform(c: dict[str, Any], keep_open_s: float) -> Alert:
    top, n = c["causes"].most_common(1)[0]
    cause = top if n * 2 > sum(c["causes"].values()) else "baseline"
    return Alert("all", "platform", "provider 429s", "provider-429-across-workflows", "page", c["start"],
                 c["last"] + keep_open_s, c["peak"], cause, dict(sorted(c["causes"].items())))


def streams(design: str, spec: dict[str, Any], events: list[slis.RunEvent], probes: list[slis.RunEvent],
            slos: dict[str, Any]) -> list[Stream]:
    """The burn-rate streams one design evaluates: a workflow's own runs, its own with the probe's, or the group's."""
    out: list[Stream] = []
    group = spec.get("group") or []
    for workflow, how in spec["workflows"].items():
        if how == "nights" or how == "group":
            continue
        mine = [e for e in events if e.workflow == workflow]
        targets = slos["workflows"][workflow]["slis"]
        for sli in ("success", "latency", "outcome"):
            target = targets[sli].get("target")
            if target is None:
                continue
            extra = [p for p in probes if p.workflow == workflow] if how == "probe" and sli == "success" else []
            out.append(Stream.of(workflow, sli, float(target), mine + extra,
                                 slis.threshold(slos, workflow) if sli == "latency" else None))
    if group:
        members = [e for e in events if e.workflow in group]
        target = min(float(slos["workflows"][w]["slis"]["success"]["target"]) for w in group)
        out.append(Stream.of("group:" + "+".join(group), "success", target, members))
    return out


def evaluate(month: Any, alerts: dict[str, Any], slos: dict[str, Any], budgets: dict[str, dict[str, float]],
             begin: float | None = None) -> dict[str, list[Alert]]:
    """Every design's alerts over the month, keyed by design, and the platform's under "platform"."""
    days = month.config["days"]
    begin = 0.0 if begin is None else begin
    end = days * 86400.0
    step = alerts["burn_rate"]["evaluate_every_minutes"] * 60.0
    rules = alerts["burn_rate"]["rules"]
    out: dict[str, list[Alert]] = {}
    for design, spec in alerts["designs"].items():
        found: list[Alert] = []
        for stream in streams(design, spec, month.events, month.probes, slos):
            for rule in rules:
                if rule["action"] == "page" and stream.sli not in alerts["burn_rate"]["page_slis"]:
                    continue
                found += episodes(stream, rule, design, begin, end, step)
        if spec["workflows"].get("w5") == "nights":
            w5 = slos["workflows"]["w5"]["slis"]
            found += night_alerts([e for e in month.events if e.workflow == "w5"], alerts["w5_failed_nights"],
                                  float(w5["success"]["target"]), slis.threshold(slos, "w5"),
                                  budgets["w5"]["success"], design)
        out[design] = sorted(found, key=lambda a: (a.start, a.scope, a.sli, a.rule))
    out["platform"] = platform_alerts(month.records)
    return out


def by_event(found: dict[str, list[Alert]], events: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """For each injected event and design: the strongest action an alert put down to it took, the first such alert,
    and every scope and SLI it reached."""
    table: dict[str, dict[str, dict[str, Any]]] = {}
    for name in events:
        row = {}
        for design, alerts_ in found.items():
            mine = [a for a in alerts_ if a.cause == name]
            pages = [a for a in mine if a.action == "page"]
            best = pages or [a for a in mine if a.action == "ticket"]
            first = min(best, key=lambda a: a.start) if best else None
            row[design] = {"action": first.action if first else "none",
                           "first": None if first is None else first.as_json(),
                           "reached": sorted({f"{a.scope} {a.sli} {a.rule}" for a in mine})}
        table[name] = row
    return table
