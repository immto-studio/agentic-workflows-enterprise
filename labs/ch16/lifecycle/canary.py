"""The canary (chapter 16, step 8, O-D14): W2's golden set through chapter 5's gateway with the weighted alias,
the two arms told apart by the gateway's cost lines, and the SLIs of slo/slis.py over each arm's runs.

lifecycle/litellm.canary.yaml puts two deployments behind larkspur-chat, the current model at weight 3 and the
candidate at weight 1, so LiteLLM's simple-shuffle sends about a quarter of the alias's calls to the candidate.
The run starts that gateway once (chapter 15's `live.start_gateway`, W2's hooks and manifest) and sends W2's 25
golden questions through W2's own harness and servers (`run_redteam.run_w2`, with nothing placed) as many times as
`passes` says, each pass a run of its own. A question is one run; its calls are the gateway's `call` lines with
its trace id, and each line's `deployment` says which arm served it.

A weight routes calls, and a W2 run makes two calls at the median, so a run can be served by one arm or by both.
The SLIs are computed three ways, and the file says which is which: over the runs each arm served alone (pure), over
the runs each arm served at all (touched: a run both arms served counts for both), and per call (the gateway's own
view: did the call come back, and how fast). The decision (lifecycle/decision.py) reads the touched runs, where the
candidate has the most events and carries its share of a mixed run's failure.

Both deployments sit on one Ollama, because the two models don't fit the card together, so the server swaps them
when the weight alternates. The run watches `/api/ps` while it runs and marks each call that followed a swap, so
the latency SLI's cost on this workstation is measured and not guessed.

Run (from labs/ch16, the portable Ollama up on 11435):
  python lifecycle/canary.py --passes 4 --out results/<date>/lifecycle
  python lifecycle/canary.py --passes 1 --limit 3 --out <scratch>     a smoke run, marked partial
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
ROOT = LAB.parents[1]
for folder in (LAB / "capacity", LAB / "budget", LAB / "slo", LAB / "ledger", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
import slis  # noqa: E402  (puts chapter 15's layers on the path through costlines)
from load import percentile  # noqa: E402  step 5's nearest rank, as the ledger's tables use it

CH15_CI = ROOT / "labs" / "ch15" / "ci"
if str(CH15_CI) not in sys.path:
    sys.path.insert(0, str(CH15_CI))
import live  # noqa: E402  (imports measure, which puts chapter 15's folders first)
import registry  # noqa: E402
import run_redteam  # noqa: E402
from record import scrub  # noqa: E402  step 4's scrub: no path or key of this machine in a result

CANARY = HERE / "litellm.canary.yaml"
ALIAS = "larkspur-chat"
WORKFLOW = "w2"
ARMS = {"local-gpt-oss-20b-chat": "control", "candidate-gemma4-12b-chat": "candidate"}
SCRATCH = HERE / "_lab"
Progress = Callable[[str], None]


def arms_of(config: Path = CANARY) -> dict[str, dict[str, Any]]:
    """The alias's deployments: id -> {arm, model, weight, share, api_base}."""
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    mine = [e for e in data["model_list"] if e["model_name"] == ALIAS]
    total = sum(float(e["litellm_params"].get("weight", 1)) for e in mine)
    out = {}
    for e in mine:
        info, params = e["model_info"], e["litellm_params"]
        out[info["id"]] = {"arm": ARMS.get(info["id"], info["id"]), "model": params["model"],
                           "weight": float(params.get("weight", 1)), "share": float(params.get("weight", 1)) / total,
                           "api_base": params.get("api_base"), "think": params.get("think", "model default"),
                           "num_ctx": params.get("num_ctx")}
    return out


# --- watching the server ------------------------------------------------------------------------------------------

class Loaded:
    """What the Ollama has loaded, sampled every half second: the swaps between the two models, and when."""

    def __init__(self, base: str, every_s: float = 0.5) -> None:
        self.base, self.every_s = base.rstrip("/"), every_s
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        with httpx.Client(timeout=5.0) as client:
            while not self._stop.is_set():
                try:
                    models = client.get(self.base + "/api/ps").json().get("models") or []
                    names = sorted(m.get("name") for m in models)
                    vram = sum(int(m.get("size_vram") or 0) for m in models)
                except (httpx.HTTPError, ValueError):
                    names, vram = ["unreachable"], 0
                if not self.samples or self.samples[-1]["loaded"] != names:
                    self.samples.append({"at": time.time(), "loaded": names, "size_vram": vram})
                self._stop.wait(self.every_s)

    def __enter__(self) -> "Loaded":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def summary(self) -> dict[str, Any]:
        changes = self.samples
        loads: dict[str, int] = {}
        for before, after in zip(changes, changes[1:]):
            for name in set(after["loaded"]) - set(before["loaded"]):
                loads[name] = loads.get(name, 0) + 1
        resident: dict[str, float] = {}
        for sample, following in zip(changes, changes[1:]):
            for name in sample["loaded"]:
                resident[name] = resident.get(name, 0.0) + following["at"] - sample["at"]
        return {"changes": len(changes), "loads": loads, "resident_s": {k: round(v, 1) for k, v in resident.items()},
                "both_at_once": any(len(s["loaded"]) > 1 and "unreachable" not in s["loaded"] for s in changes),
                "max_size_vram": max((s["size_vram"] for s in changes), default=0)}


# --- the run ------------------------------------------------------------------------------------------------------

def run(passes: int, out: Path, scratch: Path | None = None, limit: int | None = None, config: Path = CANARY,
        progress: Progress = print) -> Path:
    """The canary: the gateway once, W2's set `passes` times, the arms and the SLIs; written to `out`."""
    arms = arms_of(config)
    base = next(iter(arms.values()))["api_base"]
    if any(a["api_base"] != base for a in arms.values()):
        raise SystemExit("the canary's two arms sit on one server here; the configuration names two")
    try:
        version = httpx.get(base + "/api/version", timeout=10.0).json().get("version")
        tags = {t["name"]: t["digest"] for t in httpx.get(base + "/api/tags", timeout=10.0).json().get("models") or []}
    except (httpx.HTTPError, ValueError) as exc:
        raise SystemExit(f"no Ollama answers at {base} ({type(exc).__name__}); start the portable 0.40.13 on 11435")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scratch = scratch or SCRATCH / f"canary-{stamp}"
    scratch.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    manifests = registry.path(run_redteam.MANIFESTS[WORKFLOW])
    hooks = registry.path(run_redteam.HOOKS[WORKFLOW])
    items = live.golden_items(WORKFLOW, limit)
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started = time.perf_counter()
    url, log, stop = live.start_gateway("canary", config, manifests, hooks, scratch)
    progress(f"canary: gateway up at {url}, {len(items)} cases a pass, {passes} passes")
    pass_times = []
    try:
        with Loaded(base) as loaded:
            for n in range(1, passes + 1):
                t0 = time.perf_counter()
                run_ = run_redteam.Run("canary", scratch / f"pass-{n}", None)
                run_redteam.run_w2(run_, items, url, lambda line, n=n: progress(f"pass {n} {line}"))
                pass_times.append(round(time.perf_counter() - t0, 1))
                progress(f"pass {n} done in {pass_times[-1]} s; loaded now: {loaded.samples[-1]['loaded'] if loaded.samples else '?'}")
            live.settle(log)
            swaps = loaded.summary()
            samples = loaded.samples
    finally:
        stop()
    seconds = round(time.perf_counter() - started, 1)
    calls, runs = collect(scratch, passes, log, arms, samples)
    result = analyze(calls, runs, arms, limit is None)
    result |= {"started": started_at, "seconds": seconds, "pass_seconds": pass_times, "passes": passes,
               "cases_a_pass": len(items), "config": {"source": registry.rel(config), "sha256": registry.sha256_of(config)},
               "server": {"ollama": version, "digests": {a["model"].split("/", 1)[-1]: tags.get(a["model"].split("/", 1)[-1])
                                                          for a in arms.values()}, "swaps": swaps},
               "gateway_log_lines": sum(1 for _ in log.open(encoding="utf-8"))}
    write(out, result, calls, runs)
    return out / "canary.json"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return registry.read_jsonl(path) if path.exists() else []


def collect(scratch: Path, passes: int, log: Path, arms: dict[str, dict[str, Any]],
            samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The gateway's lines joined to the runs by trace id, each call with its arm and whether a swap came before
    it; each run with its arms, its end as slis reads a W2 result, and its seconds."""
    lines = sorted(_jsonl(log), key=lambda e: e.get("ts", ""))
    by_trace: dict[str, list[dict[str, Any]]] = {}
    for e in lines:
        if e.get("event") in ("call", "failed", "refused") and e.get("trace_id"):
            by_trace.setdefault(e["trace_id"], []).append(e)
    sentences = slis.sentences()
    runs: list[dict[str, Any]] = []
    for n in range(1, passes + 1):
        for record in _jsonl(scratch / f"pass-{n}" / "outputs.jsonl"):
            o = record["output"]
            mine = by_trace.get(record["trace_id"], [])
            served = [ARMS.get(e.get("deployment"), e.get("deployment")) for e in mine if e.get("event") == "call"]
            group = ("none" if not served else "mixed" if len(set(served)) > 1 else served[0])
            if record.get("error"):
                end, why = "error", record["error"][:120]
            else:
                end, why = slis._answer_end(o["answer"], sentences.w2_budget, sentences.w2_read_failed,
                                            sentences.w2_refusal_words)
                if end == "refusal" and slis.w2_budget_stop(o, sentences):
                    end, why = "budget_stop", "the harness's refusal after the read budget's last read and one more call"
            runs.append({"pass": n, "case": o["id"], "trace_id": record["trace_id"], "seconds": record["seconds"],
                         "end": end, "reason": why, "arms": sorted(set(served)), "group": group,
                         "calls": len(served), "by_arm": {a: served.count(a) for a in sorted(set(served))},
                         "reads": len(o.get("read_events") or []), "refused_lines": sum(1 for e in mine if e["event"] == "refused"),
                         "failed_lines": sum(1 for e in mine if e["event"] == "failed")})
    where = {r["trace_id"]: (r["pass"], r["case"]) for r in runs}
    previous_model = None
    calls: list[dict[str, Any]] = []
    loads_by_trace: dict[str, float] = {}
    for e in lines:
        if e.get("event") not in ("call", "failed"):
            continue
        at = datetime.fromisoformat(e["ts"]).timestamp()
        latency_ms = e.get("latency_ms")
        began = at - (latency_ms or 0) / 1000.0
        model = e.get("served_model")
        pass_, case = where.get(e.get("trace_id"), (None, None))
        swapped = any(began < s["at"] <= at for s in samples[1:]) if samples else None
        # The load the call paid for: from its start to the watcher's first sample that shows its model loaded.
        # The watcher samples every half second, so the figure is within about half a second.
        load_s = 0.0
        if swapped and model:
            loaded_at = next((s["at"] for s in samples if s["at"] > began and model in s["loaded"]), None)
            if loaded_at is not None:
                load_s = round(min(max(0.0, loaded_at - began), (latency_ms or 0) / 1000.0), 2)
        if e.get("trace_id"):
            loads_by_trace[e["trace_id"]] = loads_by_trace.get(e["trace_id"], 0.0) + load_s
        calls.append({"ts": e["ts"], "pass": pass_, "case": case, "trace_id": e.get("trace_id"), "event": e["event"],
                      "arm": ARMS.get(e.get("deployment"), e.get("deployment")), "deployment": e.get("deployment"),
                      "served_model": model, "requested_alias": e.get("requested_alias"),
                      "served_alias": e.get("served_alias"), "region": e.get("region"), "fallback": e.get("fallback"),
                      "prompt_tokens": e.get("prompt_tokens"), "completion_tokens": e.get("completion_tokens"),
                      "latency_ms": latency_ms, "error": e.get("error"),
                      "after_model_change": previous_model is not None and model != previous_model,
                      "swap_during": swapped, "load_s": load_s,
                      "latency_ms_without_load": None if latency_ms is None else round(latency_ms - 1000 * load_s)})
        previous_model = model
    for r in runs:
        r["loads_s"] = round(loads_by_trace.get(r["trace_id"], 0.0), 2)
        r["seconds_without_loads"] = None if r["seconds"] is None else round(max(0.0, r["seconds"] - r["loads_s"]), 2)
    return calls, runs


def _ratio(r: slis.Ratio | None) -> dict[str, Any] | None:
    return None if r is None else {"good": r.good, "valid": r.valid, "value": None if r.value is None else round(r.value, 6)}


def _events(runs: list[dict[str, Any]], seconds_key: str = "seconds") -> list[slis.RunEvent]:
    return [slis.RunEvent(WORKFLOW, f"{r['pass']}:{r['case']}", r["end"], r.get(seconds_key), reason=r["reason"],
                          source="canary") for r in runs]


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _p95(values: list[float]) -> float | None:
    found = percentile(values, 0.95)
    return None if found is None else round(found, 1)


def analyze(calls: list[dict[str, Any]], runs: list[dict[str, Any]], arms: dict[str, dict[str, Any]],
            complete: bool) -> dict[str, Any]:
    """The arms' shares, the runs by group, the SLIs three ways, and the per-call latencies with the swap cost."""
    slos = slis.load()
    threshold = slis.threshold(slos, WORKFLOW)
    names = sorted({a["arm"] for a in arms.values()})

    def slis_over(rows: list[dict[str, Any]]) -> dict[str, Any]:
        events = _events(rows)
        steady = _events(rows, "seconds_without_loads")
        return {"runs": len(rows), "ends": {end: sum(1 for r in rows if r["end"] == end) for end in slis.ENDS
                                            if any(r["end"] == end for r in rows)},
                "success": _ratio(slis.ratio(events, "success")),
                "latency": _ratio(slis.ratio(events, "latency", threshold)),
                "latency_without_loads": _ratio(slis.ratio(steady, "latency", threshold)),
                "seconds_median": _median([r["seconds"] for r in rows if r["seconds"] is not None]),
                "seconds_max": max((r["seconds"] for r in rows if r["seconds"] is not None), default=None),
                "seconds_without_loads_median": _median([r["seconds_without_loads"] for r in rows
                                                         if r.get("seconds_without_loads") is not None]),
                "loads_s_total": round(sum(r.get("loads_s") or 0.0 for r in rows), 1),
                "runs_with_a_load": sum(1 for r in rows if (r.get("loads_s") or 0) > 0)}

    call_lines = [c for c in calls if c["event"] == "call"]
    by_arm: dict[str, Any] = {}
    for arm in names:
        mine = [c for c in call_lines if c["arm"] == arm]
        failed = [c for c in calls if c["event"] == "failed" and c["arm"] == arm]
        lat = [c["latency_ms"] for c in mine if c["latency_ms"] is not None]
        swapped = [c["latency_ms"] for c in mine if c["latency_ms"] is not None and c["swap_during"]]
        steady = [c["latency_ms"] for c in mine if c["latency_ms"] is not None and c["swap_during"] is False]
        loads = [c["load_s"] for c in mine if c["swap_during"] and c["load_s"] > 0]
        by_arm[arm] = {"calls": len(mine), "failed_calls": len(failed),
                       "share_of_calls": round(len(mine) / len(call_lines), 4) if call_lines else None,
                       "prompt_tokens": sum(c["prompt_tokens"] or 0 for c in mine),
                       "completion_tokens": sum(c["completion_tokens"] or 0 for c in mine),
                       "latency_ms_median": _median(lat), "latency_ms_p95": _p95(lat),
                       "calls_after_a_swap": len(swapped), "latency_ms_median_after_a_swap": _median(swapped),
                       "latency_ms_median_steady": _median(steady),
                       "load_s_median": _median(loads), "load_s_max": max(loads, default=None),
                       "load_s_total": round(sum(loads), 1),
                       "latency_ms_median_without_load": _median([c["latency_ms_without_load"] for c in mine
                                                                  if c["latency_ms_without_load"] is not None]),
                       "runs_touched": slis_over([r for r in runs if arm in r["arms"]]),
                       "runs_pure": slis_over([r for r in runs if r["group"] == arm])}
    groups = {g: slis_over([r for r in runs if r["group"] == g]) for g in names + ["mixed", "none"]}
    return {"measured": True, "simulated": False, "complete": complete, "workflow": WORKFLOW, "alias": ALIAS,
            "threshold_s": threshold, "targets": {s: slos["workflows"][WORKFLOW]["slis"][s].get("target") for s in ("success", "latency")},
            "arms": {d: {k: v for k, v in a.items() if k != "api_base"} for d, a in arms.items()},
            "calls": {"total": len(call_lines), "failed": sum(1 for c in calls if c["event"] == "failed"),
                      "after_a_model_change": sum(1 for c in call_lines if c["after_model_change"]),
                      "with_a_swap_during": sum(1 for c in call_lines if c["swap_during"])},
            "runs": {"total": len(runs), "by_group": {g: sum(1 for r in runs if r["group"] == g) for g in names + ["mixed", "none"]},
                     "calls_median": statistics.median([r["calls"] for r in runs]) if runs else None},
            "by_arm": by_arm, "by_group": groups,
            "how_the_slis_are_counted": {
                "pure": "the runs one arm served alone",
                "touched": "the runs an arm served at all; a run both arms served counts for both, as does its failure",
                "per_call": "the gateway's call lines: a call that came back, and its latency; a swap during the call is marked",
                "latency_without_loads": "the run's seconds less the time its calls spent loading a model the server had "
                                         "to swap in, measured from the watcher's samples of /api/ps (every half second); "
                                         "what the latency SLI reads where each model has replicas of its own"}}


def write(out: Path, result: dict[str, Any], calls: list[dict[str, Any]], runs: list[dict[str, Any]]) -> None:
    (out / "canary.json").write_text(json.dumps(scrub(result), indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                                     newline="\n")
    for name, rows in (("canary-calls.jsonl", calls), ("canary-runs.jsonl", runs)):
        (out / name).write_text("".join(json.dumps(scrub(r), ensure_ascii=False) + "\n" for r in rows), encoding="utf-8",
                                newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--passes", type=int, default=4)
    parser.add_argument("--limit", type=int, help="the first N cases of the set each pass: a smoke run")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scratch", type=Path)
    args = parser.parse_args(argv)
    path = run(args.passes, args.out, args.scratch, args.limit, progress=lambda line: print(line, flush=True))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
