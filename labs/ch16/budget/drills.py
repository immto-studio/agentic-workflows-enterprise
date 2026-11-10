"""Step 4's drills on LiteLLM's database: the keys and their month, the kill switch timed both ways, the 80
percent alert, the stop and the harness's count of it, a restart, the monthly reset, the key bound to its
workflow, and the rung down.

Chapter 16, step 4 (companion #14, O-D7). Everything runs on 127.0.0.1: PostgreSQL 16.15 from
`postgres.py`, the webhook receiver, chapter 5's fake backends, and the LiteLLM proxy with this step's
config (`litellm.config.yaml`), its key-binding callback and chapter 5's callback unchanged. Each workflow
gets a virtual key from its manifest (`keys.py`), W2 and W3 from chapter 5's manifests. The harness runs are
chapter 1's loop with chapter 5's `GatewayModel`, through the workflow's key, and the fake backend answers
with chapter 5's rule model: two model calls a run, a tool call and an answer. Two things are set for the
drills alone:

- The month is brought to its edge by the admin API, `/key/update` with `spend`, as if the month's earlier
  calls had been made: one call's reservation and about three runs short of 80 percent of W2's 200 US dollars
  for the alert, and as far short of 100 for the stop. The thresholds stay the manifest's. Before each seed the
  drill waits for LiteLLM's batch writer to drain, or a queued increment would land on the seeded value.
- The budget reset job runs every 5 to 10 seconds (`PROXY_BUDGET_RESCHEDULER_MIN_TIME` and `_MAX_TIME`)
  instead of about every ten minutes, and the reset drill moves the key's `budget_reset_at` into the past in
  the database, standing in for the 1st of the month.

Run, in the smoke test's scratch environment (`prisma generate` done), from labs/ch16:
    python budget/drills.py --out results/<date>/budget
    python budget/drills.py --summarize results/<date>/budget     # the summary again from drills.json
Raw records (the cluster, the proxy's log, the gateway's cost lines, the alerts, the change log) stay in
`budget/_lab/drills-<stamp>/`.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import statistics
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
CH05 = LAB.parent / "ch05"
CH01 = LAB.parent / "ch01"
for folder in (HERE, CH01, CH05 / "harness", CH05 / "manifest", CH05 / "mcp-server"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import httpx  # noqa: E402

import keys  # noqa: E402
import oncall  # noqa: E402
import record  # noqa: E402
import rung_harness  # noqa: E402
import stops  # noqa: E402

W2, W3 = "w2-ops-assistant", "w3-incident"
LEAD = "oncall.lead@larkspur.example"
QUESTION = "Is claims-api healthy?"
MANIFESTS = CH05 / "manifest"
CONFIG = HERE / "litellm.config.yaml"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load_manifests() -> dict[str, dict]:
    import manifest as ch05_manifest

    return ch05_manifest.load_manifests(MANIFESTS)


# --- the gateway and what it needs ----------------------------------------------------------------

class Gateway:
    """PostgreSQL, the receiver, two fake backends and the proxy, on 127.0.0.1, in one run folder."""

    def __init__(self, work: Path) -> None:
        import postgres

        self.work = work
        self.state = work / "state"
        self.cluster = postgres.Cluster(data=work / "pgdata")
        self.master_key = "sk-" + secrets.token_hex(16)
        self.ports = {name: postgres.free_port() for name in ("receiver", "primary", "self-hosted", "proxy")}
        self.procs: dict[str, subprocess.Popen] = {}
        self.client = httpx.Client(timeout=30)
        self.proxy_starts: list[float] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.ports['proxy']}"

    def env(self) -> dict[str, str]:
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
                   LITELLM_LOCAL_MODEL_COST_MAP="True", LITELLM_MASTER_KEY=self.master_key,
                   DATABASE_URL=self.cluster.url("litellm"),
                   WEBHOOK_URL=f"http://127.0.0.1:{self.ports['receiver']}/budget-alert",
                   BUDGET_PRIMARY_URL=f"http://127.0.0.1:{self.ports['primary']}/v1",
                   BUDGET_SELF_HOSTED_URL=f"http://127.0.0.1:{self.ports['self-hosted']}/v1",
                   GATEWAY_CONFIG=str(CONFIG), GATEWAY_LOG_FILE=str(self.work / "gateway.log"),
                   TRACE_FILE=str(self.work / "traces.jsonl"), MANIFEST_DIR=str(MANIFESTS),
                   BUDGET_STATE_DIR=str(self.state),
                   PROXY_BUDGET_RESCHEDULER_MIN_TIME="5", PROXY_BUDGET_RESCHEDULER_MAX_TIME="10")
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        return env

    def _wait(self, url: str, seconds: float) -> float:
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            try:
                if httpx.get(url, timeout=2).status_code < 500:
                    return round(time.monotonic() - started, 2)
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        raise RuntimeError(f"{url} did not come up in {seconds} s")

    def start(self) -> None:
        import postgres

        postgres.verified()
        self.cluster.init()
        self.cluster.start()
        self.cluster.wait()
        self.cluster.create_database("litellm")
        self.procs["receiver"] = subprocess.Popen(
            [sys.executable, str(HERE / "receiver.py"), "--port", str(self.ports["receiver"]),
             "--outbox", str(self.work / "alerts.jsonl"), "--manifest-dir", str(MANIFESTS)],
            env=self.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for name in ("primary", "self-hosted"):
            self.procs[name] = subprocess.Popen(
                [sys.executable, str(CH05 / "gateway" / "fake_backend.py"), "--name", name, "--port",
                 str(self.ports[name])], env=self.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._wait(f"http://127.0.0.1:{self.ports['receiver']}/health", 30)
        for name in ("primary", "self-hosted"):
            self._wait(f"http://127.0.0.1:{self.ports[name]}/health", 30)
        self.start_proxy()

    def start_proxy(self) -> float:
        from procs import new_console

        litellm = shutil.which("litellm", path=str(Path(sys.executable).parent)) or "litellm"
        log = (self.work / "proxy.log").open("a", encoding="utf-8")
        self.procs["proxy"] = subprocess.Popen(
            [litellm, "--config", str(CONFIG), "--host", "127.0.0.1", "--port", str(self.ports["proxy"])],
            cwd=str(HERE), env=self.env(), stdout=log, stderr=subprocess.STDOUT, **new_console())
        seconds = self._wait(f"{self.url}/health/liveliness", 300)
        self.proxy_starts.append(seconds)
        return seconds

    def stop_proxy(self) -> None:
        from procs import stop_tree

        stop_tree(self.procs.pop("proxy"))

    def stop(self) -> None:
        from procs import stop_tree

        for proc in reversed(list(self.procs.values())):
            stop_tree(proc)
        self.procs.clear()
        try:
            self.cluster.stop()
        except RuntimeError as exc:
            print(f"stopping PostgreSQL: {exc}", file=sys.stderr)

    def alerts(self) -> list[dict]:
        return httpx.get(f"http://127.0.0.1:{self.ports['receiver']}/alerts", timeout=10).json()

    def sql(self, query: str, params: tuple = ()) -> list[tuple]:
        import psycopg

        with psycopg.connect(self.cluster.url("litellm"), autocommit=True, connect_timeout=5) as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchall() if cursor.description else []

    def key_row(self, token: str) -> dict[str, Any]:
        """The key as the database holds it, its soft budget from the budget row LiteLLM links to it."""
        row = self.sql('SELECT t.key_alias, t.spend, t.max_budget, b.soft_budget, t.budget_duration, '
                       't.budget_reset_at, t.blocked FROM "LiteLLM_VerificationToken" t LEFT JOIN '
                       '"LiteLLM_BudgetTable" b ON b.budget_id = t.budget_id WHERE t.token = %s', (token,))[0]
        reset_at = row[5].replace(tzinfo=timezone.utc) if row[5] is not None and row[5].tzinfo is None else row[5]
        return {"key_alias": row[0], "spend": row[1], "max_budget": row[2], "soft_budget": row[3],
                "budget_duration": row[4], "budget_reset_at": reset_at, "blocked": row[6]}

    def settle(self, token: str, quiet_s: float = 12.0, max_s: float = 60.0) -> dict[str, float]:
        """Wait until the key's spend in the database stops changing.

        LiteLLM writes spend to the database in batches, about every ten seconds, as an increment. An increment
        still queued when a drill sets the spend lands on top of the value the drill set, so each drill waits
        for the queue to drain first.
        """
        started = time.monotonic()
        last, since = self.key_row(token)["spend"], time.monotonic()
        while time.monotonic() - started < max_s:
            time.sleep(0.5)
            spend = self.key_row(token)["spend"]
            if spend != last:
                last, since = spend, time.monotonic()
            elif time.monotonic() - since >= quiet_s:
                break
        return {"waited_s": round(time.monotonic() - started, 2), "spend": round(last, 6)}

    def cost_lines(self) -> list[dict]:
        path = self.work / "gateway.log"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        return [json.loads(line) for line in lines if line.strip()]


# --- the harness ---------------------------------------------------------------------------------

def model_for(gw: Gateway, key: str, workflow: str, data_class: str = "internal", client: httpx.Client | None = None):
    from gateway_model import GatewayModel, pinned_tool_specs

    specs = pinned_tool_specs(CH05 / "mcp-server" / "tools.lock.json", {"get_pod_status"})
    return GatewayModel(gateway_url=gw.url, alias="larkspur-chat", tools=specs, trace_id=uuid.uuid4().hex,
                        workflow=workflow, data_class=data_class, api_key=key, timeout_s=30,
                        client=client or gw.client)


def harness_run(gw: Gateway, key: str, workflow: str) -> dict[str, Any]:
    """One run of chapter 1's loop through the gateway; a stop ends it and is counted, never retried.

    The tool is chapter 5's fake platform, the data its MCP server serves, so the rule model behind the
    fake backend can write its answer from the result.
    """
    from agent_loop import run_agent
    from fake_platform import pod_status

    model = model_for(gw, key, workflow)
    started = time.perf_counter()
    outcome = stops.run(run_agent, QUESTION, model, tools={"get_pod_status": pod_status},
                        allowed={"get_pod_status": {"service"}})
    return {"trace_id": model.trace_id, "answered": outcome.stop is None, "stop": outcome.stop,
            "status": outcome.status, "message": outcome.message, "calls": len(model.calls),
            "t_start": started, "t_end": time.perf_counter()}


def one_call(gw: Gateway, key: str, workflow: str, data_class: str = "internal",
             client: httpx.Client | None = None) -> dict[str, Any]:
    """One model call; its status and, when refused, which stop."""
    guarded = stops.Guarded(model_for(gw, key, workflow, data_class, client))
    started = time.perf_counter()
    try:
        guarded([{"role": "user", "content": QUESTION}])
        status, kind, message = 200, "answered", ""
    except stops.GatewayStop as stop:
        status, kind, message = stop.status, stop.kind, stop.message
    except httpx.HTTPError as exc:
        status, kind, message = None, type(exc).__name__, str(exc)[:200]
    return {"status": status, "kind": kind, "message": message[:240], "t_start": started,
            "t_end": time.perf_counter()}


def reservation_estimate(input_tokens: int = 200) -> dict[str, Any]:
    """What LiteLLM 1.106.6 reserves before one of these calls, which set no max_tokens.

    Its estimate is the counted input tokens plus the request's max_tokens, or DEFAULT_MAX_OUTPUT_TOKENS_FALLBACK
    output tokens when there is none, at the deployment's prices (spend_tracking/budget_reservation.py). The
    harness's prompts come to about 200 tokens with the tool definition.
    """
    import yaml
    from litellm.proxy.spend_tracking.budget_reservation import DEFAULT_MAX_OUTPUT_TOKENS_FALLBACK

    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    params = next(e["litellm_params"] for e in config["model_list"] if e["model_name"] == "larkspur-chat")
    estimate = input_tokens * params["input_cost_per_token"] + \
        DEFAULT_MAX_OUTPUT_TOKENS_FALLBACK * params["output_cost_per_token"]
    return {"output_tokens_reserved": DEFAULT_MAX_OUTPUT_TOKENS_FALLBACK, "input_tokens_assumed": input_tokens,
            "input_cost_per_token": params["input_cost_per_token"],
            "output_cost_per_token": params["output_cost_per_token"], "estimate_usd": round(estimate, 6)}


def run_cost(gw: Gateway, trace_id: str) -> float:
    return round(sum(line.get("cost_usd") or 0.0 for line in gw.cost_lines()
                     if line.get("event") == "call" and line.get("trace_id") == trace_id), 8)


# --- the drills ------------------------------------------------------------------------------------

def drill_keys(gw: Gateway, admin: keys.Admin, made: dict[str, dict], started: datetime) -> dict[str, Any]:
    rows = {}
    for workflow, key in made.items():
        info = admin.info(key["token"])
        row = gw.key_row(key["token"])
        reset_at = row["budget_reset_at"]  # LiteLLM keeps UTC in a column without a zone
        expected = keys.next_reset(started)
        rows[workflow] = {"key_alias": info.get("key_alias"), "models": info.get("models"),
                          "max_budget": row["max_budget"], "soft_budget": row["soft_budget"],
                          "soft_share": round(row["soft_budget"] / row["max_budget"], 6),
                          "budget_duration": row["budget_duration"], "metadata": info.get("metadata"),
                          "budget_reset_at": reset_at.astimezone(timezone.utc).isoformat(),
                          "expected_reset_at": expected.isoformat(),
                          "reset_matches_toronto": abs((reset_at - expected).total_seconds()) < 1,
                          "reset_in_toronto": reset_at.astimezone(keys.ZoneInfo(keys.ZONE)).isoformat()}
    return rows


def drill_kill_switch(gw: Gateway, admin: keys.Admin, made: dict, cycles: int, open_s: float, closed_s: float,
                      interval: float) -> dict[str, Any]:
    """A workflow loops on calls; the on-call lead blocks its key, then unblocks it, `cycles` times."""
    key = made[W2]["key"]
    events: list[dict] = []
    done = threading.Event()

    def loop() -> None:
        client = httpx.Client(timeout=10)
        while not done.is_set():
            events.append(one_call(gw, key, W2, client=client))
            time.sleep(max(0.0, interval - (events[-1]["t_end"] - events[-1]["t_start"])))

    worker = threading.Thread(target=loop, daemon=True)
    worker.start()
    time.sleep(open_s)
    rows = []
    for cycle in range(1, cycles + 1):
        t_pull = time.perf_counter()
        pulled = oncall.kill(admin, W2, by=LEAD, change=f"EC-DRILL-{cycle:02d}", folder=gw.state,
                             reason="drill: the kill switch timed at the gateway")
        t_pulled = time.perf_counter()
        probe_after_pull = one_call(gw, key, W2)
        time.sleep(closed_s)
        t_open = time.perf_counter()
        opened = oncall.reopen(admin, W2, by=LEAD, change=f"EC-DRILL-{cycle:02d}", folder=gw.state,
                               reason="drill: released")
        t_opened = time.perf_counter()
        unblock_answer = opened["answer"].get("blocked")
        probe_after_open = one_call(gw, key, W2)
        time.sleep(open_s)
        snapshot = list(events)
        refused = [e for e in snapshot if e["kind"] == "kill_switch" and t_pull <= e["t_end"] <= t_open]
        late_ok = [e for e in snapshot if e["status"] == 200 and e["t_start"] < t_pull < e["t_end"]]
        reopened = [e for e in snapshot if e["status"] == 200 and e["t_end"] >= t_open]
        rows.append({
            "cycle": cycle,
            "block_call_s": round(t_pulled - t_pull, 3),
            "block_answer": pulled["answer"].get("blocked"),
            "first_loop_refusal_s": round(min(e["t_end"] for e in refused) - t_pull, 3) if refused else None,
            "loop_calls_in_flight_that_succeeded": len(late_ok),
            "call_right_after_block": probe_after_pull["status"],
            "call_right_after_block_kind": probe_after_pull["kind"],
            "unblock_call_s": round(t_opened - t_open, 3),
            "unblock_answer": unblock_answer,
            "first_loop_success_after_unblock_s": (round(min(e["t_end"] for e in reopened) - t_open, 3)
                                                   if reopened else None),
            "call_right_after_unblock": probe_after_open["status"],
            "refused_message": refused[0]["message"] if refused else None,
        })
    done.set()
    worker.join(timeout=15)
    kinds: dict[str, int] = {}
    for e in events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1

    def spread(name: str) -> dict[str, float | None]:
        values = [r[name] for r in rows if r[name] is not None]
        return {"median": round(statistics.median(values), 3) if values else None,
                "max": max(values) if values else None, "min": min(values) if values else None}

    return {"cycles": rows, "loop_interval_s": interval, "loop_calls": len(events), "loop_outcomes": kinds,
            "first_refusal_s": spread("first_loop_refusal_s"),
            "first_success_after_unblock_s": spread("first_loop_success_after_unblock_s"),
            "block_call_s": spread("block_call_s"), "unblock_call_s": spread("unblock_call_s")}


def drill_alert(gw: Gateway, admin: keys.Admin, made: dict, margin: float, max_runs: int) -> dict[str, Any]:
    token, key = made[W2]["token"], made[W2]["key"]
    row = gw.key_row(token)
    soft, cap = float(row["soft_budget"]), float(row["max_budget"])
    seed = round(soft - margin, 6)
    settled = gw.settle(token)
    admin.update(token, spend=seed)
    runs, total, crossed_at = [], seed, None
    alert = None
    for index in range(1, max_runs + 1):
        run = harness_run(gw, key, W2)
        time.sleep(0.3)  # the alert is sent from a task the request starts
        run["cost_usd"] = run_cost(gw, run["trace_id"])
        total = round(total + run["cost_usd"], 8)
        run["month_after_usd"] = total
        if crossed_at is None and total >= soft:
            crossed_at = index
        runs.append(run)
        found = [a for a in gw.alerts() if a.get("key_alias") == W2 and a.get("event") == "soft_budget_crossed"]
        if found:
            alert = found[0]
            break
    month_before_alert_run = runs[-2]["month_after_usd"] if alert and len(runs) > 1 else seed
    return {"soft_budget": soft, "max_budget": cap, "settled_before_seed": settled, "seeded_spend": seed,
            "seeded_share": round(seed / cap, 6), "runs": [_run_row(r) for r in runs],
            "month_crossed_in_run": crossed_at, "alert_during_run": len(runs) if alert else None,
            "month_before_the_alerting_run_usd": month_before_alert_run, "alert": alert,
            # what LiteLLM counted beyond the month's priced calls when it sent the alert: the call's reservation
            "alert_spend_beyond_the_month_usd": round(alert["spend"] - month_before_alert_run, 6) if alert else None}


def drill_stop(gw: Gateway, admin: keys.Admin, made: dict, margin: float, max_runs: int, extra: int) -> dict:
    token, key = made[W2]["token"], made[W2]["key"]
    cap = float(gw.key_row(token)["max_budget"])
    seed = round(cap - margin, 6)
    settled = gw.settle(token)
    admin.update(token, spend=seed)
    runs, tally, total = [], stops.Tally(), seed
    stopped_on = None
    for index in range(1, max_runs + 1):
        run = harness_run(gw, key, W2)
        run["cost_usd"] = run_cost(gw, run["trace_id"])
        total = round(total + run["cost_usd"], 8)
        run["month_after_usd"] = total
        runs.append(run)
        tally.add(stops.Outcome(answer="" if run["answered"] else None, stop=run["stop"]))
        if run["stop"] and stopped_on is None:
            stopped_on = index
        if stopped_on is not None and index >= stopped_on + extra:
            break
    after = gw.settle(token)
    alerts = [{"event": a.get("event"), "spend": a.get("spend"), "forwarded_to": a.get("forwarded_to")}
              for a in gw.alerts() if a.get("key_alias") == W2]
    stopped = [r for r in runs if r["stop"]]
    return {"max_budget": cap, "settled_before_seed": settled, "seeded_spend": seed,
            "runs": [_run_row(r) for r in runs], "first_stopped_run": stopped_on, "tally": tally.as_dict(),
            "stop_status": stopped[0]["status"] if stopped else None,
            "stop_kind": stopped[0]["stop"] if stopped else None,
            "stop_message": stopped[0]["message"] if stopped else None,
            "calls_made_by_stopped_runs": sum(r["calls"] for r in stopped),
            "month_before_the_first_stop_usd": (runs[stopped_on - 2]["month_after_usd"]
                                                if stopped_on and stopped_on > 1 else seed),
            "spend_in_database_after_usd": after["spend"],
            "short_of_the_budget_usd": round(cap - after["spend"], 6), "alerts_so_far": alerts}


def drill_restart(gw: Gateway, admin: keys.Admin, made: dict) -> dict[str, Any]:
    """The month spent to the last cent, a run refused, the proxy stopped and started, the next run refused too.

    The stop drill leaves the month a reservation short of its budget, where whether a run's second call is
    refused depends on whether LiteLLM has priced its first. So this drill sets the month to the budget itself,
    as if the month's last calls had been made, and the refusal no longer depends on timing.
    """
    token, key = made[W2]["token"], made[W2]["key"]
    cap = float(gw.key_row(token)["max_budget"])
    gw.settle(token)
    admin.update(token, spend=cap)
    settled = gw.settle(token)
    before = harness_run(gw, key, W2)
    gw.stop_proxy()
    back = gw.start_proxy()
    after = harness_run(gw, key, W2)
    return {"month_set_to_usd": cap, "spend_in_database_before_restart": settled["spend"],
            "run_before_restart": _run_row(before), "proxy_back_in_s": back,
            "spend_litellm_reports_after_restart": admin.info(token).get("spend"),
            "run_after_restart": _run_row(after)}


def drill_reset(gw: Gateway, admin: keys.Admin, made: dict, wait_s: float) -> dict[str, Any]:
    token, key = made[W2]["token"], made[W2]["key"]
    moved = now_utc()
    gw.sql('UPDATE "LiteLLM_VerificationToken" SET budget_reset_at = now() - interval \'1 minute\' '
           'WHERE token = %s', (token,))
    started, reset_after = time.monotonic(), None
    while time.monotonic() - started < wait_s:
        spend, reset_at = gw.sql('SELECT spend, budget_reset_at FROM "LiteLLM_VerificationToken" WHERE token = %s',
                                 (token,))[0]
        if spend == 0:
            reset_after = round(time.monotonic() - started, 2)
            break
        time.sleep(0.5)
    spend, reset_at = gw.sql('SELECT spend, budget_reset_at FROM "LiteLLM_VerificationToken" WHERE token = %s',
                             (token,))[0]
    reset_at = reset_at if reset_at.tzinfo else reset_at.replace(tzinfo=timezone.utc)
    runs, answered_after = [], None
    started = time.monotonic()
    while time.monotonic() - started < wait_s:
        run = harness_run(gw, key, W2)
        runs.append(_run_row(run))
        if run["answered"]:
            answered_after = round(time.monotonic() - started, 2)
            break
        time.sleep(2.0)
    expected = keys.next_reset(moved)
    return {"reset_in_s": reset_after, "spend_after_reset": spend,
            "new_budget_reset_at": reset_at.astimezone(timezone.utc).isoformat(),
            "expected_reset_at": expected.isoformat(),
            "new_reset_matches_toronto": abs((reset_at - expected).total_seconds()) < 1,
            "runs_until_answered": runs, "answered_after_s": answered_after}


def drill_binding(gw: Gateway, made: dict) -> list[dict[str, Any]]:
    cases = [("W2's key, its own tags", made[W2]["key"], W2, "internal"),
             ("W2's key, W3's workflow tag", made[W2]["key"], W3, "confidential"),
             ("W2's key, data class above its maximum", made[W2]["key"], W2, "confidential"),
             ("the master key, which names no workflow", gw.master_key, W2, "internal"),
             ("W3's key, its own tags", made[W3]["key"], W3, "confidential")]
    rows = []
    for name, key, workflow, data_class in cases:
        call = one_call(gw, key, workflow, data_class)
        rows.append({"case": name, "status": call["status"], "kind": call["kind"], "message": call["message"]})
    return rows


def drill_rung(state: Path) -> list[dict[str, Any]]:
    import yaml

    w3 = load_manifests()[W3]
    overrides = state / "rungs"
    path = overrides / f"{W3}.yaml"
    rows = [{"case": "no override; the model asks to restart", **rung_harness.run(
        "Restart claims-api", w3, overrides, rung_harness.RESTART)}]
    oncall.lower_rung(W3, 1, manifest_rung=int(w3["rung"]), by=LEAD, change="EC-DRILL-RUNG", folder=state,
                      reason="drill: a planted line restated; reads only until the review")
    rows.append({"case": "lowered to rung 1; the model asks to restart", **rung_harness.run(
        "Restart claims-api", w3, overrides, rung_harness.RESTART)})
    rows.append({"case": "lowered to rung 1; the model asks to read", **rung_harness.run(
        "Is claims-api healthy?", w3, overrides, rung_harness.READ)})
    path.write_text(yaml.safe_dump({"workflow": W3, "rung": 4, "by": LEAD, "change": "EC-DRILL-RAISE",
                                    "reason": "an edit that tries to raise the rung"}, sort_keys=False),
                    encoding="utf-8", newline="\n")
    rows.append({"case": "an override of rung 4, above the manifest's 3", **rung_harness.run(
        "Restart claims-api", w3, overrides, rung_harness.RESTART)})
    path.write_text(f"workflow: {W3}\nrung: one\n", encoding="utf-8", newline="\n")
    rows.append({"case": "a malformed override (rung: one)", **rung_harness.run(
        "Restart claims-api", w3, overrides, rung_harness.RESTART)})
    path.write_text(f"workflow: {W3}\nrung: 1\n  by: [\n", encoding="utf-8", newline="\n")
    rows.append({"case": "an override that isn't YAML", **rung_harness.run(
        "Is claims-api healthy?", w3, overrides, rung_harness.READ)})
    oncall.lower_rung(W3, None, manifest_rung=int(w3["rung"]), by=LEAD, change="EC-DRILL-RUNG", folder=state,
                      reason="drill: back to the manifest's rung")
    rows.append({"case": "override removed; the model asks to restart", **rung_harness.run(
        "Restart claims-api", w3, overrides, rung_harness.RESTART)})
    return rows


# --- helpers for the record -------------------------------------------------------------------------

_WALL0 = (time.time(), time.perf_counter())


def _wall(perf: float) -> float:
    return _WALL0[0] + (perf - _WALL0[1])


def _received(alert: dict) -> float:
    return datetime.fromisoformat(alert["received_at"]).timestamp()


def _run_row(run: dict) -> dict[str, Any]:
    return {k: run.get(k) for k in ("answered", "stop", "status", "calls", "cost_usd", "month_after_usd",
                                    "message") if k in run}


def versions() -> dict[str, Any]:
    import platform
    from importlib import metadata

    found = {}
    for name in ("litellm", "litellm-proxy-extras", "prisma", "psycopg", "httpx"):
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = None
    found["python"] = platform.python_version()
    return found


def run_all(out: Path, args: argparse.Namespace) -> dict[str, Any]:
    import postgres

    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    work = HERE / "_lab" / f"drills-{stamp}"
    work.mkdir(parents=True)
    gw = Gateway(work)
    started = now_utc()
    result: dict[str, Any] = {"date": started.date().isoformat(), "versions": versions(),
                              "postgres": postgres.VERSION}
    try:
        gw.start()
        admin = keys.Admin(gw.url, gw.master_key)
        manifests = {w: m for w, m in load_manifests().items() if w in (W2, W3)}
        made = keys.provision(admin, manifests)
        result["proxy_start_s"] = gw.proxy_starts[0]
        result["keys"] = drill_keys(gw, admin, made, started)
        print("keys", json.dumps(result["keys"])[:300], flush=True)
        result["kill_switch"] = drill_kill_switch(gw, admin, made, args.cycles, args.open_s, args.closed_s,
                                                  args.interval)
        print("kill switch", json.dumps(result["kill_switch"]["first_refusal_s"]), flush=True)
        # Each month is seeded one reservation and about three runs below its threshold, so that runs are
        # answered first and the alert, then the stop, come from the harness's own calls.
        result["reservation"] = reservation_estimate()
        margin = round(result["reservation"]["estimate_usd"] + 0.003, 6)
        result["alert"] = drill_alert(gw, admin, made, margin=margin, max_runs=12)
        print("alert", json.dumps(result["alert"].get("alert"))[:300], flush=True)
        result["stop"] = drill_stop(gw, admin, made, margin=margin, max_runs=12, extra=3)
        print("stop", json.dumps(result["stop"]["tally"]), flush=True)
        result["restart"] = drill_restart(gw, admin, made)
        print("restart", json.dumps(result["restart"])[:300], flush=True)
        result["reset"] = drill_reset(gw, admin, made, wait_s=90)
        print("reset", json.dumps(result["reset"])[:300], flush=True)
        result["binding"] = drill_binding(gw, made)
        result["alerts"] = [{k: a.get(k) for k in ("received_at", "event", "kind", "key_alias", "spend",
                                                   "soft_budget", "max_budget", "projected_spend", "event_message",
                                                   "forwarded_to")} for a in gw.alerts()]
        result["gateway_log"] = summarize_log(gw.cost_lines())
    finally:
        gw.stop()
    result["rung"] = drill_rung(gw.state)
    changes = gw.state / "changes.jsonl"
    result["changes"] = [json.loads(line) for line in changes.read_text(encoding="utf-8").splitlines()] \
        if changes.exists() else []
    record.write_json(out / "drills.json", result, secrets=(gw.master_key, gw.cluster.password))
    (out / "summary.md").write_text(summarize(json.loads((out / "drills.json").read_text(encoding="utf-8")),
                                              _smoke(out)), encoding="utf-8", newline="\n")
    print(f"raw records in {work}; results in {out}")
    return result


def summarize_log(lines: list[dict]) -> dict[str, Any]:
    events: dict[str, int] = {}
    for line in lines:
        events[line.get("event", "?")] = events.get(line.get("event", "?"), 0) + 1
    calls = [line for line in lines if line.get("event") == "call"]
    failed = [line for line in lines if line.get("event") == "failed"]
    reasons: dict[str, int] = {}
    for line in failed:
        message = str(line.get("message") or "")
        reason = ("key blocked" if "Key is blocked" in message else "budget exceeded" if "Budget has been" in message
                  else "other")
        reasons[reason] = reasons.get(reason, 0) + 1
    return {"lines": len(lines), "by_event": dict(sorted(events.items())),
            "calls_by_workflow": {w: sum(1 for c in calls if c.get("workflow") == w) for w in (W2, W3)},
            "calls_with_cost": sum(1 for c in calls if isinstance(c.get("cost_usd"), (int, float))),
            "failed_by_reason": dict(sorted(reasons.items())),
            "failed_without_trace_id": sum(1 for line in failed if not line.get("trace_id"))}


def _smoke(out: Path) -> dict | None:
    path = out / "smoke.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# --- the summary ----------------------------------------------------------------------------------

def _table(header: list[str], rows: list[list[Any]]) -> list[str]:
    def cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value).replace("|", "\\|")
    lines = ["|" + "|".join(header) + "|", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["|" + "|".join(cell(v) for v in row) + "|" for row in rows]
    return lines


def summarize(d: dict[str, Any], smoke: dict | None) -> str:
    out = [f"# Step 4: budgets and switches, {d['date']}", ""]
    if smoke:
        out += ["## The smoke test", ""]
        out += _table(["Step", "t (s)", "Status", "What it said", "Engines alive"],
                      [[s["step"], s["t"], s.get("status", s.get("exit", s.get("db", ""))),
                        (s.get("error") or s.get("answer") or "")[:80], s["engines_alive"]] for s in smoke["steps"]])
        out += [""]
        out += _table(["Python", "Prober", "Processes on its console", "os.kill(child, 0)", "Child afterwards"],
                      [[p.get("python"), p["mode"], p.get("processes_on_prober_console"),
                        p["attempts"][0]["call"] if p.get("attempts") else p.get("error"),
                        ("alive" if p["attempts"][-1]["child_alive"] else
                         f"ended, exit code {p['attempts'][-1]['child_exit_code']}") if p.get("attempts") else ""]
                       for p in smoke["os_kill_probe"]])
        out += [""]
    out += ["## The keys", ""]
    out += _table(["Workflow", "max_budget", "soft_budget", "budget_duration", "Reset at (UTC)",
                   "Reset in Toronto", "Midnight on the 1st in Toronto"],
                  [[w, k["max_budget"], k["soft_budget"], k["budget_duration"], k["budget_reset_at"],
                    k["reset_in_toronto"], k["reset_matches_toronto"]] for w, k in d["keys"].items()])
    ks = d["kill_switch"]
    out += ["", "## The kill switch, gateway half", ""]
    out += _table(["Cycle", "/key/block (s)", "First refusal in the loop (s)", "In-flight calls that succeeded",
                   "Call right after the block", "/key/unblock (s)", "First success after the unblock (s)",
                   "Call right after the unblock"],
                  [[r["cycle"], r["block_call_s"], r["first_loop_refusal_s"], r["loop_calls_in_flight_that_succeeded"],
                    r["call_right_after_block"], r["unblock_call_s"], r["first_loop_success_after_unblock_s"],
                    r["call_right_after_unblock"]] for r in ks["cycles"]])
    out += ["", f"Loop: one call every {ks['loop_interval_s']} s, {ks['loop_calls']} calls, outcomes "
                f"{json.dumps(ks['loop_outcomes'], sort_keys=True)}. First refusal: median "
                f"{ks['first_refusal_s']['median']} s, max {ks['first_refusal_s']['max']} s. First success after "
                f"the unblock: median {ks['first_success_after_unblock_s']['median']} s, max "
                f"{ks['first_success_after_unblock_s']['max']} s."]
    rv = d["reservation"]
    out += ["", "## The reservation", "",
            f"Before each call LiteLLM reserves the input tokens and {rv['output_tokens_reserved']} output tokens, "
            f"since these requests set no max_tokens: about {rv['estimate_usd']} US dollars at the stand-in prices "
            f"({rv['input_cost_per_token']} and {rv['output_cost_per_token']} a token). Each month below starts one "
            f"reservation and about three runs short of its threshold."]
    al = d["alert"]
    out += ["", "## The 80 percent alert", ""]
    out += _table(["Run", "Answered", "Cost (USD)", "Month after (USD)"],
                  [[i + 1, r["answered"], r.get("cost_usd"), r.get("month_after_usd")] for i, r in enumerate(al["runs"])])
    alert = al.get("alert") or {}
    crossed = (f"the priced calls alone crossed it in run {al['month_crossed_in_run']}"
               if al["month_crossed_in_run"] else "the priced calls alone never reached it")
    out += ["", f"Seeded at {al['seeded_spend']} of {al['max_budget']} ({al['seeded_share']:.6f}) after the spend "
                f"settled at {al['settled_before_seed']['spend']}; soft budget {al['soft_budget']}. The alert arrived "
                f"during run {al['alert_during_run']}, with the month's priced calls at "
                f"{al['month_before_the_alerting_run_usd']} before that run ({crossed}): event "
                f"`{alert.get('event')}`, spend {alert.get('spend')}, {al['alert_spend_beyond_the_month_usd']} beyond "
                f"the month's priced calls, forwarded to {', '.join(alert.get('forwarded_to') or [])}."]
    st = d["stop"]
    out += ["", "## The stop", ""]
    out += _table(["Run", "Answered", "Stop", "Status", "Calls", "Month after (USD)"],
                  [[i + 1, r["answered"], r.get("stop"), r.get("status"), r.get("calls"), r.get("month_after_usd")]
                   for i, r in enumerate(st["runs"])])
    out += ["", f"Seeded at {st['seeded_spend']} of {st['max_budget']} after the spend settled at "
                f"{st['settled_before_seed']['spend']}. First stopped run: {st['first_stopped_run']}, status "
                f"{st['stop_status']}, counted by the harness as `{st['stop_kind']}`. Tally "
                f"{json.dumps(st['tally'], sort_keys=True)}; the stopped runs made {st['calls_made_by_stopped_runs']} "
                f"model calls between them. Spend in the database afterwards: {st['spend_in_database_after_usd']}, "
                f"{st['short_of_the_budget_usd']} short of the budget. The gateway said: {st['stop_message']}"]
    out += ["", "## Every alert the receiver got", ""]
    out += _table(["Received (UTC)", "Event", "What it is", "Spend", "max_budget", "soft_budget", "Projected spend",
                   "Forwarded to"],
                  [[a["received_at"][11:23], a["event"], a["kind"], a["spend"], a["max_budget"], a["soft_budget"],
                    a["projected_spend"], ", ".join(a["forwarded_to"] or [])] for a in d["alerts"]])
    rs = d["restart"]
    out += ["", "## A restart", "",
            f"With the month set to {rs['month_set_to_usd']}, the database held {rs['spend_in_database_before_restart']} "
            f"and the run before the restart got status {rs['run_before_restart'].get('status')} "
            f"(`{rs['run_before_restart'].get('stop')}`). The proxy came back in {rs['proxy_back_in_s']} s, reported "
            f"the key's spend as {rs['spend_litellm_reports_after_restart']}, and the next run got status "
            f"{rs['run_after_restart'].get('status')} (`{rs['run_after_restart'].get('stop')}`) after "
            f"{rs['run_after_restart'].get('calls')} model calls."]
    rz = d["reset"]
    out += ["", "## The monthly reset", "",
            f"With `budget_reset_at` moved into the past, the reset job set the spend to {rz['spend_after_reset']} in "
            f"{rz['reset_in_s']} s and the next reset to {rz['new_budget_reset_at']} (midnight on the 1st in Toronto: "
            f"{'yes' if rz['new_reset_matches_toronto'] else 'no'}). Runs until one was answered: "
            f"{len(rz['runs_until_answered'])}, the first answered {rz['answered_after_s']} s after the reset."]
    out += ["", "## The key bound to its workflow", ""]
    out += _table(["Case", "Status", "Kind", "Message"],
                  [[b["case"], b["status"], b["kind"], b["message"][:110]] for b in d["binding"]])
    out += ["", "## The rung down", ""]
    out += _table(["Case", "Started", "Rung", "Write tools dropped", "Model calls", "Tool calls", "Answer or why"],
                  [[r["case"], r["started"], r.get("rung"), ", ".join(r.get("dropped") or []), r["model_calls"],
                    json.dumps(r["tool_calls"], sort_keys=True), (r.get("answer") or r.get("why") or "")[:90]]
                   for r in d["rung"]])
    out += ["", "## The change log", ""]
    out += _table(["Change", "Lever", "Workflow", "From", "To", "By", "Document by", "Review"],
                  [[c["change"], c["lever"], c["workflow"], c["from"], c["to"], c["by"], c["document_by"], c["review"]]
                   for c in d["changes"]])
    gl = d["gateway_log"]
    out += ["", f"Gateway log (chapter 5's callback and the key binding): {gl['lines']} lines, "
                f"{json.dumps(gl['by_event'], sort_keys=True)}; served calls with a cost: {gl['calls_with_cost']}; "
                f"failed lines by reason {json.dumps(gl['failed_by_reason'], sort_keys=True)}, "
                f"{gl['failed_without_trace_id']} of them with no trace id.", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=LAB / "results" / "drills")
    parser.add_argument("--summarize", type=Path, default=None, help="write summary.md again from drills.json")
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--open-s", type=float, default=2.0)
    parser.add_argument("--closed-s", type=float, default=2.0)
    parser.add_argument("--interval", type=float, default=0.25)
    args = parser.parse_args(argv)
    if args.summarize:
        folder = args.summarize
        data = json.loads((folder / "drills.json").read_text(encoding="utf-8"))
        (folder / "summary.md").write_text(summarize(data, _smoke(folder)), encoding="utf-8", newline="\n")
        return 0
    run_all(args.out, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
