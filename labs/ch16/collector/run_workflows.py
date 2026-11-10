"""Step 3b: W2, W3, W4 and W5 on the local models, every process sending its spans to the pinned Collector.

Chapter 16, step 3b (companion #14, O-D3, O-D5, O-D18). Step 3 ran chapter 5's skeleton with its rule model.
This runs the workflows themselves, on the local models, through their gateways, with chapter 16's Collector
between their processes and the span file. The Collector runs config.yaml with CloudWatch and Langfuse off
(`otelcol.local_config`; step 7 turns them on) and an overlay for the run: its ports, a tap that records what
arrived before any processor and when, and a sink beside the span file that records when each kept span left.

Every process of a run gets OTEL_EXPORTER_OTLP_ENDPOINT. The workflows' harnesses run inside their eval
scripts, which install no tracer provider, so this process installs chapter 5's for the harness, as chapter
5's client.py and W4's scribe.py do in their own main(). Three of the processes the lab scripts start are
kept off any collector there: W4's gateway and W5's gateway and readers ("the lab never talks to a
collector", harness/launch.py). Here they start the same way with the endpoint kept. Nothing else about a
run changes: the harness, the gateway's config and callbacks, the servers and the scoring are the
workflow's own.

- w2: W2's golden set (eval/answer_eval.py) on gpt-oss-20b, with its three servers and its gateway started
  here as W2's README starts them. answer_eval keeps the harness's log in memory, so the log is copied to a
  file on its way: its lines hold each case's trace id.
- w3: W3's 24 incidents (eval/lab.py's run_all, which starts its servers and gateway) on gpt-oss-20b. W3's
  record keeps no trace id, so each incident's is read from lab.TRACE once the incident ends.
- w4: W4's 8 changes (eval/lab.py's run_all) on gpt-oss-20b, or on Gemma 4 12B through the portable Ollama
  on 11435 with its thinking off. The results are written as W4's write_results writes them, to the run's
  folder, with the gateway's cost lines added to logs-<model>/.
- w5: one W5 night (harness/night.py's run_night: night-1 of eval/nights.yaml, the three workspaces) on
  gpt-oss-20b, with config.yaml's decision_wait (`--wait step3`) or decided 10 seconds after its root
  arrives, with decision_wait raised to 300 seconds as the cap (`--wait root`).

A run waits 7 seconds after its last case is timed and scored, before any process stops. The OpenTelemetry SDK
exports a batch every 5 seconds, and on Windows terminate() ends a process without its exit handlers, so whatever
is still waiting is lost: the first smoke run stopped W2's gateway 3 seconds after its last call and lost both
its spans, and W3's and W4's lab scripts stop their processes right after the last case.

W2, W3 and W4 run with the share of the rest at 100 percent, so the span file holds every span the processes
sent, and what config.yaml's 10 percent would keep is computed again by policies.py, which step 3 showed
agrees with the Collector. W5's two runs keep config.yaml's 10 percent, since the sampler is what they
measure. This process refuses every connection that would leave the machine, and the gateways read LiteLLM's
price map from the wheel (LITELLM_LOCAL_MODEL_COST_MAP).

Raw records go to collector/_lab/<stamp>-<run>/ (git-ignored). analyze_workflows.py copies each run's results
and cost lines to its workflow's eval/traced/<date>/ and writes results/<date>/workflows/. Run from labs/ch16
in chapter 5's environment, one run a process, with Ollama serving the model:
    python collector/run_workflows.py w2
    python collector/run_workflows.py w3
    python collector/run_workflows.py w4 --model gpt-oss-20b
    python collector/run_workflows.py w4 --model gemma4-12b      # the portable Ollama on 11435
    python collector/run_workflows.py w5 --wait step3
    python collector/run_workflows.py w5 --wait root
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import httpx

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
COMPANION = LAB.parents[1]
CH05 = LAB.parent / "ch05"
WORKFLOWS = COMPANION / "workflows"
W1 = WORKFLOWS / "w1-knowledge-assistant"
W2 = WORKFLOWS / "w2-ops-assistant"
W3 = WORKFLOWS / "w3-incident"
W4 = WORKFLOWS / "w4-change"
W5 = WORKFLOWS / "w5-drift"
for folder in (HERE, LAB / "ledger", CH05 / "tracing"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import fake_otlp  # noqa: E402
import fetch  # noqa: E402
import offline  # noqa: E402  the ledger's: only loopback connections from this process
import otelcol  # noqa: E402
import policies  # noqa: E402
import trace_setup as tracing  # noqa: E402  chapter 5's

GATEWAY_KEY = "sk-larkspur-lab-ch16-3b"  # the proxies' master key for these runs, a local value, not a secret
W2_SECRET = "w2-lab-secret-ch16-step-3b-at-least-32-bytes"  # the token secret W2's servers and harness share here
OLLAMA_PORTS = {"gpt-oss-20b": 11434, "gemma4-12b": 11435}
GATEWAY_CONFIGS = {"gpt-oss-20b": W2 / "gateway" / "litellm.config.yaml", "gemma4-12b": W2 / "gateway" / "litellm.gemma.yaml"}
THINK = {"gemma4-12b": False}  # the brief's setting for Gemma 4 12B, as W5's lab has it; gpt-oss-20b keeps its default
EVERY_RUN = 100.0  # the share of the rest for W2, W3 and W4: every trace kept
QUIET_S = 7.0  # longer than the OpenTelemetry SDK's 5-second export delay in every process
ROOT_TRIGGER = "10s"  # decision_wait_after_root_received in W5's second run: the SDK's delay, and room
ROOT_CAP = "300s"  # decision_wait in that run: over four times the 69-second night the lab recorded on gpt-oss-20b
WAITS = {"step3": (None, None), "root": (ROOT_CAP, ROOT_TRIGGER)}
LITELLM = Path(sys.executable).parent / ("litellm.exe" if os.name == "nt" else "litellm")


# --- the machine around a run -----------------------------------------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port: int, seconds: float, proc: subprocess.Popen | None = None) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"127.0.0.1:{port} did not open: the process exited with {proc.returncode}")
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise RuntimeError(f"127.0.0.1:{port} did not open in {seconds:.0f} s")


def gpu() -> dict[str, Any]:
    """What nvidia-smi says the GPU holds, and what each Ollama has loaded: checked before and after a run."""
    out: dict[str, Any] = {}
    try:
        text = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                               "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=30).stdout.strip()
        name, used, total, util = [part.strip() for part in text.split(",")]
        out["gpu"] = {"name": name, "memory_used_mib": int(used), "memory_total_mib": int(total), "utilization_pct": int(util)}
    except Exception as exc:  # recorded, not fatal: the run says what it could see
        out["gpu"] = {"error": type(exc).__name__}
    for model, port in OLLAMA_PORTS.items():
        try:
            base = f"http://127.0.0.1:{port}"
            loaded = httpx.get(f"{base}/api/ps", timeout=5).json().get("models") or []
            version = httpx.get(f"{base}/api/version", timeout=5).json().get("version")
            out[f"ollama_{port}"] = {"version": version, "loaded": [{"name": m.get("name"), "size_vram": m.get("size_vram"),
                                                                     "context_length": m.get("context_length")} for m in loaded]}
        except httpx.HTTPError:
            out[f"ollama_{port}"] = None
    return out


def one_model_on_the_gpu(model: str) -> None:
    """Refuse to start while the other Ollama holds a model: one model on the GPU at a time."""
    seen = gpu()
    for other, port in OLLAMA_PORTS.items():
        state = seen.get(f"ollama_{port}")
        if other != model and state and state["loaded"]:
            raise RuntimeError(f"Ollama on {port} still holds {[m['name'] for m in state['loaded']]}; unload it before "
                               f"running {model}")
    if seen.get(f"ollama_{OLLAMA_PORTS[model]}") is None:
        raise RuntimeError(f"no Ollama answers on {OLLAMA_PORTS[model]} for {model}")


class Tee(io.TextIOBase):
    """A log that also goes to a file: answer_eval keeps W2's harness log in memory."""

    def __init__(self, stream: TextIO, copy: TextIO) -> None:
        self.stream, self.copy = stream, copy

    def write(self, text: str) -> int:
        self.stream.write(text)
        self.copy.write(text)
        return len(text)

    def flush(self) -> None:
        self.stream.flush()
        self.copy.flush()


@dataclass
class Processes:
    """What a run started here, each with its log of stdout and stderr; stopped together at the end."""

    folder: Path
    started: list[tuple[str, subprocess.Popen]] = field(default_factory=list)
    files: list[Any] = field(default_factory=list)

    def start(self, name: str, args: list[str], env: dict[str, str], cwd: Path | None = None) -> subprocess.Popen:
        out = (self.folder / f"{name}.out.log").open("ab")
        self.files.append(out)
        proc = subprocess.Popen(args, env=env, cwd=str(cwd) if cwd else None, stdout=out, stderr=subprocess.STDOUT)
        self.started.append((name, proc))
        return proc

    def stop(self, grace: float = QUIET_S) -> None:
        """Stop them all, after `grace` seconds: on Windows terminate() ends a process without its exit handlers,
        so a process's last spans leave only if its batch processor's 5-second delay has passed."""
        time.sleep(grace)
        for _, proc in self.started:
            proc.terminate()
        for _, proc in self.started:
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        for out in self.files:
            out.close()


def gateway_env(log: Path, manifest_dir: Path | None = None, config: Path | None = None,
                key: str = GATEWAY_KEY) -> dict[str, str]:
    """A gateway's environment as the lab scripts build it, with the Collector's endpoint kept. `key` is the
    master key its callers send (W4's risk scorer sends W4's lab key)."""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "LITELLM_MASTER_KEY": key,
           "LITELLM_LOCAL_MODEL_COST_MAP": "True", "GATEWAY_LOG_FILE": str(log)}
    env.pop("MANIFEST_DIR", None)
    env.pop("GATEWAY_CONFIG", None)
    if manifest_dir is not None:
        env["MANIFEST_DIR"] = str(manifest_dir)
    if config is not None:
        env["GATEWAY_CONFIG"] = str(config.resolve())
    return env


def start_gateway(procs: Processes, config: Path, env: dict[str, str], cwd: Path) -> str:
    port = free_port()
    proc = procs.start("gateway", [str(LITELLM), "--config", str(config), "--host", "127.0.0.1", "--port", str(port)],
                       env, cwd)
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"the gateway exited with {proc.returncode}; see {procs.folder / 'gateway.out.log'}")
        try:
            if httpx.get(f"{url}/health/liveliness", timeout=2).status_code < 500:
                return url
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("the gateway did not come up in 180 s")


def with_ollama(config: Path, out_dir: Path, port: int | None, think: bool | None) -> Path:
    """The config copied beside the run with its api_base on another Ollama's port and Ollama's think flag set
    in each deployment, as W4's and W5's lab scripts rewrite it. Unchanged settings keep the original file."""
    if port in (None, 11434) and think is None:
        return config
    lines = []
    for line in config.read_text(encoding="utf-8").splitlines():
        if think is not None and re.match(r"^\s*think:", line):
            continue
        if port not in (None, 11434):
            line = line.replace("http://127.0.0.1:11434", f"http://127.0.0.1:{port}")
        lines.append(line)
        indent = re.match(r"^(\s*)num_ctx:", line)
        if indent and think is not None:
            lines.append(f"{indent.group(1)}think: {'true' if think else 'false'}")
    copy = out_dir / config.name
    copy.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return copy


# --- the Collector, with its tap and its sink --------------------------------------------------------------------

@dataclass
class Session:
    work: Path
    collector: otelcol.Collector
    tap: fake_otlp.Receiver
    sink: fake_otlp.Receiver
    metrics_port: int
    endpoint: str
    decision_wait_s: float
    after_root: str | None
    share: float | None


@contextmanager
def collector(work: Path, *, share: float | None, decision_wait: str | None = None,
              after_root: str | None = None) -> Iterator[Session]:
    exe = fetch.verified()  # refuses a tarball or a binary that isn't the pinned one
    with fake_otlp.Receiver("tap", "/v1/traces") as tap, fake_otlp.Receiver("sink", "/v1/traces") as sink:
        port, metrics_port = free_port(), free_port()
        config = otelcol.write_local_config(work)
        env = otelcol.local_environment(span_file=work / "spans.jsonl", share_percent=share)
        extra = otelcol.local_overlay(otlp_port=port, metrics_port=metrics_port, tap_url=tap.url, sink_url=sink.url,
                                      decision_wait=decision_wait, after_root=after_root)
        running = otelcol.Collector(exe, work, env, extra, config=config).start()
        wait = float((decision_wait or policies.config()["processors"]["tail_sampling"]["decision_wait"]).rstrip("s"))
        try:
            yield Session(work, running, tap, sink, metrics_port, f"http://127.0.0.1:{port}", wait, after_root, share)
        finally:
            if running.proc is not None and running.proc.poll() is None:
                running.stop()


def settle(tap: fake_otlp.Receiver, seconds: float = QUIET_S, limit: float = 90.0) -> None:
    """Until the tap has seen nothing new for `seconds`: every process has exported its last spans."""
    deadline, seen, quiet_since = time.time() + limit, -1, time.time()
    while time.time() < deadline:
        count = len(tap.records)
        if count != seen:
            seen, quiet_since = count, time.time()
        elif time.time() - quiet_since >= seconds:
            return
        time.sleep(0.25)


def finish(session: Session, setup: tracing.TracingSetup, meta: dict[str, Any]) -> None:
    """Flush this process's spans, wait until every trace the policies keep has all its spans at the sink, then
    stop the Collector and write what the tap, the sink and its own metrics recorded."""
    setup.provider.force_flush()
    settle(session.tap)
    quiet = time.time()
    tapped = fake_otlp.by_trace(session.tap.spans())
    cfg = policies.settings(percent=session.share)
    budgets = policies.budgets()
    expected = {t: len(spans) for t, spans in tapped.items()
                if policies.decide(t, policies.features(spans), per_run=budgets, threshold_ms=cfg["threshold_ms"],
                                   salt=cfg["salt"], percent=cfg["percent"])["kept"]}
    deadline = quiet + session.decision_wait_s + 40
    complete = False
    while time.time() < deadline:
        at_sink = fake_otlp.by_trace(session.sink.spans())
        if all(len(at_sink.get(t, [])) >= n for t, n in expected.items()):
            complete = True
            break
        time.sleep(0.5)
    time.sleep(3)  # anything that shouldn't have come
    metrics = httpx.get(f"http://127.0.0.1:{session.metrics_port}/metrics", timeout=10).text
    meta["collector_exit"] = session.collector.stop()
    meta |= {"collector_started": session.collector.started_at, "decision_wait_s": session.decision_wait_s,
             "decision_wait_after_root_received": session.after_root,
             "share_percent": session.share if session.share is not None else cfg["percent"],
             "feature_gates": list(otelcol.FEATURE_GATES), "traces_expected_kept": len(expected),
             "all_kept_spans_at_the_sink": complete, "waited_after_quiet_s": round(time.time() - quiet, 1)}
    (session.work / "metrics.txt").write_text(metrics, encoding="utf-8", newline="\n")
    session.tap.write(session.work / "tap.jsonl")
    session.sink.write(session.work / "sink.jsonl")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")


def wait_after_the_last_case(scoring: Any, last: str) -> None:
    """W3's and W4's run_all time a case, score it, and stop their processes right after the last one. Waiting
    QUIET_S once, after the last case is timed and scored, lets the processes' last spans leave first and keeps
    the wait out of every case's recorded seconds."""
    original, waited = scoring.score, []

    def score(case: dict[str, Any], record: dict[str, Any]) -> Any:
        verdict = original(case, record)
        if case["id"] == last and not waited:
            waited.append(True)
            time.sleep(QUIET_S)
        return verdict

    scoring.score = score


def isolate(*folders: Path) -> None:
    for folder in reversed(folders):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))


# --- W2 ----------------------------------------------------------------------------------------------------------

W2_SERVERS = ("kubernetes", "metrics", "logs")


def run_w2(work: Path, model: str, session: Session, only: str | None) -> tuple[tracing.TracingSetup, dict[str, Any]]:
    if model != "gpt-oss-20b":
        raise SystemExit("W2's run for fig-16-01 is on gpt-oss-20b")
    isolate(W2 / "eval", W2 / "tests", W1 / "knowledge-server" / "membership")
    import answer_eval  # W2's: it puts W2's harness and servers and W1's access code on the path
    import conftest as w2_tests  # W2's tests' fresh_table, as W3's lab uses it
    import sync  # W1's

    logs, results = work / "logs", work / "results"
    table = work / "table.json"
    sync.write_table(w2_tests.fresh_table(), table)  # W1's rule: a table older than 36 hours grants broad groups only
    procs = Processes(logs)
    urls: dict[str, str] = {}
    processes = [{"process": "the harness, in this process (eval/answer_eval.py)", "service": "w2-harness"}]
    setup = tracing.configure("w2-harness")
    try:
        for name in W2_SERVERS:
            port = free_port()
            env = {**os.environ, "PYTHONUTF8": "1", "TOOL_IDENTITY": f"larkspur-ops-{name}-reader", "W2_TOKEN_SECRET": W2_SECRET,
                   "TOOL_LOG_FILE": str(logs / f"{name}-server.jsonl"), "MEMBERSHIP_TABLE": str(table)}
            env.pop("TRACE_FILE", None)
            proc = procs.start(f"{name}-server", [sys.executable, str(W2 / "servers" / f"{name}_server.py"), "--port", str(port)],
                               env, W2 / "servers")
            wait_port(port, 60, proc)
            urls[f"{name}-mcp"] = f"http://127.0.0.1:{port}/mcp"
            processes.append({"process": f"the {name} MCP server (servers/{name}_server.py)", "service": f"larkspur-ops-{name}"})
        gateway = start_gateway(procs, GATEWAY_CONFIGS[model], gateway_env(logs / "gateway.jsonl"), W2 / "gateway")
        processes.append({"process": "the gateway (LiteLLM with chapter 5's callback, gateway/litellm.config.yaml)",
                          "service": "gateway"})

        original = answer_eval.ask
        harness_log = (logs / "harness.jsonl").open("a", encoding="utf-8", newline="\n")

        async def ask(question: str, token: str, servers: dict[str, str], gateway_url: str, key: str, *,
                      trace_id: str | None = None, log: TextIO = sys.stderr, audit: dict[str, Any] | None = None) -> Any:
            return await original(question, token, servers, gateway_url, key, trace_id=trace_id, log=Tee(log, harness_log),
                                  audit=audit)

        answer_eval.ask = ask
        os.environ.update(W2_TOKEN_SECRET=W2_SECRET, GATEWAY_KEY=GATEWAY_KEY, MEMBERSHIP_TABLE=str(table))
        argv = ["--gateway", gateway, "--json", str(results / f"answers-{model}.json")]
        for server, url in urls.items():
            argv += [f"--{server}", url]
        if only:
            argv += ["--only", only]
        started = time.time()
        code = answer_eval.main(argv)
        harness_log.close()
    finally:
        procs.stop()
    return setup, {"processes": processes, "exit": code, "seconds": round(time.time() - started, 1)}


# --- W3 ----------------------------------------------------------------------------------------------------------

def run_w3(work: Path, model: str, session: Session, only: str | None) -> tuple[tracing.TracingSetup, dict[str, Any]]:
    if model != "gpt-oss-20b":
        raise SystemExit("W3's run is on gpt-oss-20b")
    os.environ["W3_LAB_SCRATCH"] = str(work / "w3-scratch")  # read when lab.py is imported
    isolate(W3 / "eval")
    import lab  # W3's eval/lab.py

    setup = tracing.configure("w3-harness")
    incidents = lab.scoring.load_incidents(W3 / "eval" / "incidents.yaml")
    if only:
        incidents = [c for c in incidents if c["id"] in set(only.split(","))]
    traces: dict[str, str | None] = {}
    original = lab.run_incident

    async def run_incident(incident: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await original(incident, *args, **kwargs)
        finally:
            traces[incident["id"]] = lab.TRACE.get("id")  # set by run_incident before anything else

    lab.run_incident = run_incident
    wait_after_the_last_case(lab.scoring, incidents[-1]["id"])
    started = time.time()
    records, summary = lab.run_all(incidents, model_tag=model, config=GATEWAY_CONFIGS[model])
    seconds = round(time.time() - started, 1)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = work / "results"
    write_json(results / f"runs-{model}.json", {"model": model, "run_at": stamp, "summary": summary, "records": records})
    write_json(results / f"trace-ids-{model}.json", traces)
    scratch = work / "w3-scratch" / "run"
    for source in sorted(scratch.glob("*.log")) + [scratch / "gateway.jsonl"]:
        if source.exists():
            shutil.copyfile(source, work / "logs" / (source.stem + ".jsonl" if source.suffix == ".log" else source.name))
    processes = [{"process": "the harness and the approval service, in this process (eval/lab.py)", "service": "w3-harness"},
                 *({"process": f"the {s} MCP server", "service": n} for s, n in (
                     ("kubernetes", "larkspur-ops-kubernetes"), ("metrics", "larkspur-ops-metrics"), ("logs", "larkspur-ops-logs"),
                     ("writer", "larkspur-ops-writer"), ("ServiceNow", "larkspur-ops-servicenow"))),
                 {"process": "the gateway (LiteLLM with chapter 5's callback, W2's litellm.config.yaml)", "service": "gateway"}]
    return setup, {"processes": processes, "seconds": seconds}


# --- W4 ----------------------------------------------------------------------------------------------------------

def run_w4(work: Path, model: str, session: Session, only: str | None) -> tuple[tracing.TracingSetup, dict[str, Any]]:
    os.environ["W4_LAB_SCRATCH"] = str(work / "w4-scratch")
    isolate(W4 / "eval")
    import lab  # W4's eval/lab.py

    think = THINK.get(model)

    def start_gateway(config: Path, out_dir: Path, ollama_port: int | None = None) -> tuple[int, subprocess.Popen]:
        """W4's start_gateway, with the Collector's endpoint kept and, for Gemma, its thinking off."""
        port = free_port()
        hooks_dir = config.parent
        config = with_ollama(config, out_dir, ollama_port, think)
        env = gateway_env(out_dir / "gateway.jsonl", W4 / "manifest", config, key=lab.GATEWAY_KEY)
        stderr = (out_dir / "gateway.stderr").open("w", encoding="utf-8")
        proc = subprocess.Popen([str(LITELLM), "--config", str(config), "--host", "127.0.0.1", "--port", str(port)],
                                env=env, stdout=stderr, stderr=subprocess.STDOUT, text=True, cwd=str(hooks_dir))
        wait_port(port, 150, proc)
        return port, proc

    lab.start_gateway = start_gateway
    import scribe  # W4's a2a/scribe.py, on the path through lab.py: its main() configures tracing this way
    setup = tracing.configure(scribe.AGENT_NAME, lab.support.SCRIBE_IDENTITY)
    changes = lab.scoring.load_changes(W4 / "eval" / "changes.yaml")
    if only:
        changes = [c for c in changes if c["id"] in set(only.split(","))]
    wait_after_the_last_case(lab.scoring, changes[-1]["id"])
    port = OLLAMA_PORTS[model]
    started = time.time()
    packs, results, summary = lab.run_all(changes, model, GATEWAY_CONFIGS[model], port if port != 11434 else None)
    seconds = round(time.time() - started, 1)
    summary["versions"]["think"] = "model default" if think is None else think
    out = work / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"packs-{model}.json").write_text(json.dumps(packs, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (out / f"results-{model}.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    (out / f"summary-{model}.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    (out / f"readme-{model}.md").write_text(lab.runner.readme_table({model: summary}) + "\n", encoding="utf-8")
    logs = out / f"logs-{model}"
    logs.mkdir(exist_ok=True)
    run = work / "w4-scratch" / "run"
    for source, name in ((run / "scribe.jsonl", "scribe.jsonl"), (run / "analyst" / "agent.log", "analyst.jsonl"),
                         (run / "risk" / "agent.log", "risk-scorer.jsonl"), (run / "gateway.jsonl", "gateway.jsonl")):
        if source.exists():
            (logs / name).write_text(lab.scrub(source.read_text(encoding="utf-8")), encoding="utf-8")
    measured = lab.metrics_mod.metrics(out, model)
    (out / f"metrics-{model}.json").write_text(json.dumps(measured, indent=1) + "\n", encoding="utf-8")
    processes = [{"process": "the scribe, in this process (eval/lab.py)", "service": "scribe"},
                 {"process": "the analyst A2A server (a2a/analyst.py)", "service": "analyst"},
                 {"process": "the risk scorer A2A server (a2a/risk_scorer.py), whose rationale seam calls the gateway",
                  "service": "risk-scorer"},
                 {"process": "the gateway (LiteLLM with chapter 5's callback, W4's manifest)", "service": "gateway"}]
    return setup, {"processes": processes, "seconds": seconds, "think": summary["versions"]["think"]}


# --- W5 ----------------------------------------------------------------------------------------------------------

def start_readers(procs: Processes, launch: Any, folder: Path, secret: str) -> Any:
    """harness/launch.py's start_readers, with the Collector's endpoint kept and no TRACE_FILE."""
    folder.mkdir(parents=True, exist_ok=True)
    table = folder / "membership.json"
    table.write_text(json.dumps(launch.fresh_table(), indent=2), encoding="utf-8")
    readers = launch.Readers(urls={}, logs={}, folder=folder)
    for name in launch.READERS:
        port = free_port()
        log = folder / f"{name}.log"
        env = {**os.environ, "TOOL_IDENTITY": launch.IDENTITY.format(name), "W5_TOKEN_SECRET": secret, "TOOL_LOG_FILE": str(log),
               "MEMBERSHIP_TABLE": str(table), "PYTHONUTF8": "1"}
        env.pop("TRACE_FILE", None)
        proc = procs.start(f"{name}-reader", [sys.executable, "-X", "utf8", str(W5 / "servers" / f"{name}_reader.py"),
                                              "--port", str(port)], env)
        wait_port(port, 60, proc)
        readers.urls[f"{name}-mcp"] = f"http://127.0.0.1:{port}/mcp"
        readers.logs[name] = log
    return readers


def run_w5(work: Path, model: str, session: Session, only: str | None) -> tuple[tracing.TracingSetup, dict[str, Any]]:
    if model != "gpt-oss-20b":
        raise SystemExit("W5's night is on gpt-oss-20b")
    isolate(W5 / "eval", W5 / "harness", W5 / "servers", W5 / "writer", W5 / "detect")
    import github_fake as gh
    import lab  # W5's eval/lab.py: prepare_config and versions
    import launch
    import night as night_mod
    import prose
    import run_nights
    import score as scoring
    from common import mint_app_token
    from ledger import Ledger

    nights = scoring.load_nights(W5 / "eval" / "nights.yaml")
    golden = nights[0]  # night-1: the fixture night over the three workspaces
    logs, out = work / "logs", work / "night"
    out.mkdir(parents=True, exist_ok=True)
    config, num_ctx, base = lab.prepare_config(GATEWAY_CONFIGS[model], work, None, max(lab.MIN_NUM_CTX, prose.MAX_TOKENS + 4096),
                                               lab.THINK.get(model))
    procs = Processes(logs)
    setup = night_mod.install_tracing(out)  # OTLP, since the endpoint is set: the night's root span and all under it
    try:
        gateway = start_gateway(procs, config, gateway_env(logs / "gateway.jsonl", W5 / "manifest", config), GATEWAY_CONFIGS[model].parent)
        secret = secrets.token_hex(32)
        readers = start_readers(procs, launch, work / "readers", secret)
        os.environ.update(W5_MODEL_BASE_URL=f"{gateway}/v1", W5_MODEL_NAME=prose.ALIAS, W5_MODEL_API_KEY=GATEWAY_KEY)
        fake = gh.GitHubFake(night_mod.night_at(golden["date"]))
        gh.seed_platform_infra(fake)
        ledger = Ledger(out / "ledger.json")
        started = time.time()
        record = night_mod.run_night(golden["date"], list(golden["workspaces"]), out, servers=readers.urls,
                                     token=mint_app_token(secret), github=fake, ledger=ledger, gateway_log=logs / "gateway.jsonl")
        seconds = round(time.time() - started, 1)
        fork, upstream = fake.installation_token(gh.FORK_APP), fake.installation_token(gh.UPSTREAM_APP)
        packs = {golden["id"]: {r["key"]: run_nights.pack_of(fake, r, fork, upstream) for r in record["pull_requests"]}}
        results = run_nights.score_all([golden], {golden["id"]: record}, packs, ledger, "model")
    finally:
        procs.stop()
    write_json(work / "results" / "night.json", {"golden_id": golden["id"], "record": record, "result": results[0],
                                                  "versions": lab.versions(base, num_ctx)})
    for name, path in readers.logs.items():
        if path.exists():
            shutil.copyfile(path, logs / f"{name}-reader.jsonl")
    processes = [{"process": "the night's harness, in this process (harness/night.py)", "service": "w5-night"},
                 *({"process": f"the {name} reader (servers/{name}_reader.py)", "service": f"larkspur-drift-{name}"}
                   for name in launch.READERS),
                 {"process": "the gateway (LiteLLM with chapter 5's callback, W5's manifest)", "service": "gateway"}]
    return setup, {"processes": processes, "seconds": seconds, "trace_id": record["trace_id"], "night": golden["id"],
                   "passed": results[0].get("pass")}


RUNS: dict[str, Callable[..., tuple[tracing.TracingSetup, dict[str, Any]]]] = {"w2": run_w2, "w3": run_w3, "w4": run_w4, "w5": run_w5}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("workflow", choices=sorted(RUNS))
    parser.add_argument("--model", choices=sorted(OLLAMA_PORTS), default="gpt-oss-20b")
    parser.add_argument("--wait", choices=sorted(WAITS), default="step3", help="W5: config.yaml's decision_wait, or the root trigger")
    parser.add_argument("--only", help="comma-separated case ids, for a smoke run that isn't kept")
    args = parser.parse_args(argv)
    one_model_on_the_gpu(args.model)
    offline.block_network()
    name = f"{args.workflow}-{args.model}" + (f"-{args.wait}" if args.workflow == "w5" else "") + ("-smoke" if args.only else "")
    work = HERE / "_lab" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{name}"
    (work / "logs").mkdir(parents=True)
    (work / "results").mkdir()
    decision_wait, after_root = WAITS[args.wait] if args.workflow == "w5" else (None, None)
    share = None if args.workflow == "w5" else EVERY_RUN
    meta: dict[str, Any] = {"run": name, "workflow": args.workflow, "model": args.model, "only": args.only,
                            "wait": args.wait if args.workflow == "w5" else None, "date": date.today().isoformat(),
                            "python": sys.version.split()[0], "gpu_before": gpu()}
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ.pop("TRACE_FILE", None)
    with collector(work, share=share, decision_wait=decision_wait, after_root=after_root) as session:
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = session.endpoint  # every process this one starts, and this one
        meta["started"] = time.time()
        setup, ran = RUNS[args.workflow](work, args.model, session, args.only)
        meta["ended"] = time.time()
        meta |= ran
        finish(session, setup, meta)
    meta["gpu_after"] = gpu()
    port = OLLAMA_PORTS[args.model]
    serving = meta["gpu_after"].get(f"ollama_{port}") or {}
    meta["processes"].append({"process": f"Ollama {serving.get('version')} on {port}, serving {args.model}"
                                         + (" with its thinking off" if THINK.get(args.model) is False else ""),
                              "service": None, "loaded": serving.get("loaded")})
    write_json(work / "meta.json", meta)
    print(f"raw records in {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
