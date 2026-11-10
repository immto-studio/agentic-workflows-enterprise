"""Step 5's summary: every table the README's step 5 section prints, written from the committed files.

Chapter 16, step 5. `run_drills.py` writes `drills.json`, `calculator.json`, `limiter-cache.json` and the
requests and calls behind them to `results/<date>/capacity/`; this writes `summary.md` beside them from those files
and from `continuity.yaml`, the same bytes each time.

Run (from labs/ch16):  python capacity/run_drills.py --summarize results/<date>/capacity
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
CONTINUITY = HERE / "continuity.yaml"


def num(value: Any, digits: int = 3) -> str:
    """A number for a table: up to `digits` significant digits, thousands separated, no trailing zeros."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value == 0:
            return "0"
        if abs(value) >= 10 ** digits:
            return f"{round(value):,}"
        text = f"{value:.{digits}g}"
        if "e" in text:
            text = f"{value:.{digits + 6}f}".rstrip("0").rstrip(".")
        return text
    return str(value)


def share(value: float | None, digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{num(value * 100, digits)}%"


def table(header: list[str], rows: list[list[Any]]) -> list[str]:
    def cell(value: Any) -> str:
        return (value if isinstance(value, str) else num(value)).replace("|", "\\|")
    lines = ["|" + "|".join(header) + "|", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["|" + "|".join(cell(v) for v in row) + "|" for row in rows]
    return lines


def counts(mapping: dict[str, int] | None) -> str:
    if not mapping:
        return ""
    return ", ".join(f"{k} {v}" for k, v in mapping.items())


# --- the sections ------------------------------------------------------------------------------------------

def by_limit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The contention rounds grouped by limit, in the order the drill first ran the limits."""
    order = list(dict.fromkeys(r["name"] for r in rows))
    return sorted(rows, key=lambda r: (order.index(r["name"]), r.get("round", 1)))


def contention(d: dict[str, Any]) -> list[str]:
    rows = by_limit(d["contention"])
    out = ["## Contention", "",
           f"A provider quota of {d['quota_tpm']:,} tokens a minute; W3 every 6 s and W2 every 3 s for "
           f"{num(d['duration_s'])} s, and W2's burst from {num(d['burst'][0])} to {num(d['burst'][1])} s; each "
           "limit three times. W3's requests made during the burst:", ""]
    out += table(["Limit", "Round", "Requests", "Served", "On the first attempt", "Attempts a request",
                  "Median wait (s)", "Longest wait (s)", "What refused W3's attempts"],
                 [[c["name"], c.get("round", 1), c["w3_in_the_burst"]["requests"], c["w3_in_the_burst"]["served"],
                   c["w3_in_the_burst"]["first_attempt"], c["w3_in_the_burst"]["attempts_per_request"],
                   c["w3_in_the_burst"]["wait_median_s"], c["w3_in_the_burst"]["wait_max_s"],
                   counts(c["w3_in_the_burst"]["refused_by"])] for c in rows])
    out += ["", "W2 during the burst, and the provider over the whole run:", ""]

    def provider_refusals(c: dict[str, Any], workflow: str) -> int:
        return c["provider"]["by_workflow"].get(workflow, {}).get("refused", 0)

    out += table(["Limit", "Round", "W2's burst requests", "Served", "W2's questions served", "W3 served, whole run",
                  "Provider refusals, W2", "Provider refusals, W3", "What refused W2's burst"],
                 [[c["name"], c.get("round", 1), c["w2_burst"]["requests"], c["w2_burst"]["served"],
                   f"{c['w2_steady_in_the_burst']['served']} of {c['w2_steady_in_the_burst']['requests']}",
                   f"{c['w3_whole_run']['served']} of {c['w3_whole_run']['requests']}",
                   provider_refusals(c, "w2-ops-assistant"), provider_refusals(c, "w3-incident"),
                   counts(c["w2_burst"]["refused_by"])] for c in rows])
    return out


def limiter_cache(cache: dict[str, Any] | None) -> list[str]:
    """The limiter-cache drill: one round of each per-key limit with the census callback, with and without alerts."""
    if not cache:
        return []
    w2, w3 = "w2-ops-assistant", "w3-incident"
    out = ["", "## The limiter's cache", "",
           "Each per-key limit once more, with a callback that reads the in-memory cache LiteLLM's rate limiter counts "
           "in without Redis, on step 4's gateway and on the same gateway without its budget alerts; times in "
           "seconds from the start of the round.", ""]

    def key(c: dict[str, Any], workflow: str) -> dict[str, Any]:
        return c["cache"]["keys"][workflow]

    out += table(["Gateway", "Limit", "Most entries", "Full at (s)", "What it held then", "W2's window evicted at (s)",
                  "The key's refusals of W2, the last at (s)", "W2's burst tokens served from 60 to 120 s",
                  "W3 in the burst, served and on the first attempt", "Provider refusals, W3"],
                 [[c["gateway"], c["name"], f"{c['cache']['largest']} of {c['cache']['entries_max']}",
                   c["cache"]["full_at_s"], counts(c["cache"]["kinds_when_largest"]),
                   key(c, w2)["window_evicted_s"],
                   f"{key(c, w2)['key_refusals']}, {num(key(c, w2)['last_key_refusal_s'])}"
                   if key(c, w2)["key_refusals"] else "0",
                   c["cache"]["w2_burst_tokens_served_60_to_120_s"],
                   f"{c['w3_in_the_burst']['served']} of {c['w3_in_the_burst']['requests']}, "
                   f"{c['w3_in_the_burst']['first_attempt']}",
                   c["provider"]["by_workflow"].get(w3, {}).get("refused", 0)] for c in cache["rounds"]])
    return out


def retries(d: dict[str, Any]) -> list[str]:
    out = ["", "## Retries", "",
           "A minute of W2's requests, one every 0.75 s with 1,500 tokens reserved each, against a fresh quota of "
           "60,000 a minute: the quota admits the first forty, and the rest of the minute is throttled.", ""]
    out += table(["Through", "Policy", "Requests", "Served", "Calls", "Calls a success", "Calls in the minute",
                  "Calls over requests, in the minute", "Refused by"],
                 [[r["through"], r["policy"], r["requests"], r["served"], r["calls"], r["calls_per_success"],
                   r["calls_in_the_minute"], r["load_over_offered"], counts(r["refused_by"])]
                  for r in d["client_retries"]])
    out += ["", "LiteLLM's router on its own, `num_retries: 2`, the first deployment throttled:", ""]
    out += table(["Case", "Attempts", "Gaps between attempts (s)", "Served by", "Status"],
                 [[r["case"], ", ".join(f"{a['deployment']} {a['status']}" for a in r["attempts"]),
                   ", ".join(num(g) for g in r["gaps_s"]), r["served_by"], r["status"]] for r in d["router_retries"]])
    return out


def latency(d: dict[str, Any]) -> list[str]:
    out = ["", "## The gateway's own latency", "",
           "Each call's time at the client less the provider's own time for it, matched by its id, both on the "
           "performance counter; the provider answers 152 output tokens at 1 ms each after 50 ms, unless the setup "
           "says otherwise. The first row has no gateway, so its figure is the client's and the provider's own "
           "overhead, which every other row includes.", ""]
    out += table(["Setup", "Calls", "At once", "Client, median (ms)", "Provider, median (ms)",
                  "Client less provider, median (ms)", "Client less provider, 95th percentile (ms)",
                  "LiteLLM's own figure, median (ms)"],
                 [[r["setup"], r["calls"], r["concurrency"], r["client_ms"]["median"], r["provider_ms"]["median"],
                   r["gateway_ms"]["median"], r["gateway_ms"]["p95"], r["litellm_reports_ms"]["median"]]
                  for r in d["latency"]])
    return out


def outage(d: dict[str, Any]) -> list[str]:
    rows = d["outage"]
    out = ["", "## The outage drill", "",
           f"`allowed_fails: {rows[0]['allowed_fails']}` and `cooldown_time: {num(rows[0]['cooldown_time_s'])}`; "
           "times in seconds from the moment the primary began to fail.", ""]

    def cycle(row: dict[str, Any], i: int) -> str:
        if len(row["cycles"]) <= i:
            return ""
        c = row["cycles"][i]
        return f"{c['failures']} failures, {num(c['first_failure_s'])} to {num(c['last_failure_s'])}"

    out += table(["Mode", "First cycle", "Cooldown first answered (s)", "Second cycle", "Healed at (s)",
                  "Primary serving again after the heal (s)"],
                 [[r["mode"], cycle(r, 0), r["first_cooldown_answer_s"], cycle(r, 1), r["healed_at_s"],
                   r["primary_served_again_after_heal_s"]] for r in rows])
    out += ["", "What the workflows' calls got, those sent after the failure took effect and answered before the primary "
                "healed:", ""]
    out += table(["Mode", "W2's calls", "W2's answers", "Served by", "W2's latency, median / longest (s)",
                  "W3's calls", "W3's answers", "W3's refusals"],
                 [[r["mode"], r["w2"]["calls"], counts(r["w2"]["statuses"]), counts(r["w2"]["served_by"]),
                   f"{num(r['w2']['latency_median_s'])} / {num(r['w2']['latency_max_s'])}", r["w3"]["calls"],
                   counts(r["w3"]["statuses"]), counts(r["w3"]["kinds"])] for r in rows])
    out += ["", "Runs in flight when the primary began to fail, and a W3 run started during the cooldown:", ""]

    def w2_run(r: dict[str, Any]) -> str:
        run, lines = r["runs"]["w2_in_flight"], r["run_lines"]["w2_in_flight"]
        served = [f"{line['deployment']} in {line['region']}" for line in lines if line["event"] == "call"]
        return f"{'answered' if run['answered'] else 'no answer'}; calls served by {', then '.join(served)}"

    def w3_run(run: dict[str, Any]) -> str:
        if run.get("raised"):
            return f"raised {run['raised']} after {run['model_calls']} model call{'s' if run['model_calls'] != 1 else ''}"
        return f"{run['outcome']} ({run['reason'] or 'no reason'}) after {run['model_calls']} model calls"

    out += table(["Mode", "W2's run", "W3's run", "W3's run during the cooldown"],
                 [[r["mode"], w2_run(r), w3_run(r["runs"]["w3_in_flight"]), w3_run(r["runs"]["w3_during_cooldown"])]
                  for r in rows])
    out += ["", "Where each workflow's calls were served, from chapter 5's cost lines:", ""]
    out += table(["Mode", "W2's calls by Region", "W3's calls by Region", "W3's failed lines with fallback disabled",
                  "W2's cooldown failures logged as the fallback"],
                 [[r["mode"], counts(r["w2_regions"]), counts(r["w3_regions"]),
                   f"{r['w3_failed_lines_with_fallback_disabled']} of {r['w3_failed_lines']}",
                   r["w2_cooldown_failures_logged_as_the_fallback"]] for r in rows])
    return out


def database(d: dict[str, Any]) -> list[str]:
    db = d["database"]
    out = ["", "## The database stopped", "",
           "One W2 call a second, each sent whatever happened to the last; times in seconds from the moment "
           "PostgreSQL stopped, and from the moment it started again for the calls after it.", ""]
    out += table(["Stopped for (s)", "Calls sent while down", "Answered from the key cache", "The cache answered until (s)",
                  "Refused", "A refusal held its caller, median / longest (s)", "Answered after waiting for it",
                  "First answered call after the restart, sent at (s)", "After the restart",
                  "Spend counted over the answered calls' cost"],
                 [[db["stopped_for_s"], db["calls_while_down"], db["answered_from_the_key_cache"],
                   db["the_cache_answered_until_s"], counts({k: v for k, v in db["while_down"].items() if k != "200"}),
                   f"{num(db['refusal_held_its_caller_s']['median'])} / {num(db['refusal_held_its_caller_s']['max'])}",
                   db["answered_after_waiting_for_the_database"], db["first_call_answered_after_restart_sent_s"],
                   counts(db["after_restart"]), db["spend_counted_over_answered"]]])
    out += ["", "What the refusals said: " + "; ".join(f"\"{m}\" ({n})" for m, n in db["messages_while_down"].items())
            + "."]
    return out


def repeat(d: dict[str, Any]) -> list[str]:
    r = d["repeat"]
    out = ["", "## The repeated write", ""]
    out += table(["Case", "Presented", "Write ran", "Generation", "Stopped by", "Reason"],
                 [[row["case"], row["presented"], row["write_ran"],
                   f"{row['generation_before']} to {row['generation_after']}", row["stopped_by"] or "", row["reason"]]
                  for row in r["rows"]])
    out += ["", f"Restarts in all: {r['restarts']}; run A's approval {r['approvals']['run A']}, run B's "
                f"{r['approvals']['run B']}."]
    return out


def calculator(c: dict[str, Any]) -> list[str]:
    out = ["", "## The provisioned calculator", ""]
    out += table(["Workflow", "Busy hour (runs)", "Runs a month", "Input tokens a minute", "Output tokens a minute",
                  "Duty cycle"],
                 [[p["workflow"], p["busy_hour_runs"], p["runs_per_month"], p["busy_input_tpm"], p["busy_output_tpm"],
                   p["duty_cycle"]] for p in c["profiles"].values()])
    out += ["", "Ratios only, as the chapter prints them; the prices are in `calculator.json`:", ""]
    out += table(["Workflow", "Product", "Term", "Units the busy hour needs", "Units bought", "Busy hour fills",
                  "Utilization u", "Discount needed (1 - u)", "Break-even u*", "Busy hours to break even",
                  "Month over per_month_usd"],
                 [[line["workflow"], line["product"],
                   line["term"] + (f", {line['endpoint']}" if line.get("endpoint") else ""),
                   line["units_the_busy_hour_needs"], line["units_bought"], share(line["busy_hour_fills"]),
                   share(line["utilization"]), share(line["discount_needed"]), share(line["break_even_utilization"]),
                   line["busy_hours_to_break_even"], line["month_over_per_month_usd"]] for line in c["lines"]])
    out += ["", "What each product lacked for u*:", ""]
    seen: dict[str, str] = {}
    for line in c["lines"]:
        if line["lacks"]:
            seen.setdefault(line["product"], line["lacks"])
    out += table(["Product", "Lacks"], [[k, v] for k, v in seen.items()])
    out += ["", "The busy hour's Restricted calls on the self-hosted path, against chapter 9's measured speeds:", ""]
    out += table(["Workflow", "Input tokens", "Output tokens", "Replica-seconds", "Share of one replica-hour",
                  "Share of the two-replica floor"],
                 [[s["workflow"], s["input_tokens"], s["output_tokens"], s["replica_seconds"],
                   share(s["share_of_one_replica_hour"]), share(s["share_of_the_floor"])] for s in c["self_hosted"]])
    return out


def continuity(rows: list[dict[str, Any]]) -> list[str]:
    out = ["", "## Continuity", ""]
    out += table(["Component", "Failure mode", "Recovery objective", "Evidence", "Gap"],
                 [[r["component"], r["failure_mode"], r["recovery_objective"], r["evidence"], r.get("gap") or ""]
                  for r in rows])
    return out


def render(d: dict[str, Any], c: dict[str, Any], rows: list[dict[str, Any]],
           cache: dict[str, Any] | None = None) -> str:
    out = [f"# Step 5: capacity and continuity, {d['date']}", ""]
    out += contention(d) + limiter_cache(cache) + retries(d) + latency(d) + outage(d) + database(d) + repeat(d)
    out += calculator(c)
    out += continuity(rows)
    v = d["versions"]
    out += ["", f"LiteLLM {v['litellm']}, Python {v['python']}, PostgreSQL {d['postgres']}, prisma {v['prisma']}.", ""]
    return "\n".join(out)


def load_continuity(path: Path = CONTINUITY) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["components"]


def load_cache(folder: Path) -> dict[str, Any] | None:
    """The limiter-cache drill's file, when the folder has one."""
    path = folder / "limiter-cache.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write(folder: Path) -> Path:
    d = json.loads((folder / "drills.json").read_text(encoding="utf-8"))
    c = json.loads((folder / "calculator.json").read_text(encoding="utf-8"))
    path = folder / "summary.md"
    path.write_text(render(d, c, load_continuity(), load_cache(folder)), encoding="utf-8", newline="\n")
    return path
