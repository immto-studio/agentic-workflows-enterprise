"""The local run: chapter 5's skeleton sends every span through the pinned Collector to the span file and two fakes.

Chapter 16, step 3 (companion #14, O-D3, O-D4). Chapter 5's code runs as it is: its three fake model
backends, its LiteLLM gateway with the callback that writes the cost lines and the `chat` spans, its MCP
server over Streamable HTTP with its call log, and its harness, here in this process, with the rule model
answering behind the gateway (no GPU, no model). Every one of those processes gets
OTEL_EXPORTER_OTLP_ENDPOINT, so each sends its spans over OTLP to the Collector, which runs config.yaml with
an overlay (otelcol.py): its ports, CloudWatch's endpoint pointed at the fake, and a tap that records what
arrived before any processor, and when. LARKSPUR_TRACE_TOOL_ARGS=1 makes the harness and the server put the
tool arguments on their spans, so there is content for the Collector to drop.

Two phases, each with a Collector of its own on the same port:

- every-run: the share of the rest at 100 percent, so every run is kept. Chapter 5's golden set (20
  questions) and five runs made to be kept: one the harness refuses, one slow, one over its budget in a
  single call, one the fallback serves, and one that fails.
- sampled: the configured share, 10 percent. The golden set five times and the same five runs.

Runs start 1.1 seconds apart: W2's manifest allows 120 requests a minute, and a golden run makes two.

Writes every raw record to collector/_lab/<stamp>/ (git-ignored); analyze.py turns that folder into the
results. Run (from labs/ch16, in chapter 5's environment, with ports 8801 to 8803 free):
    python collector/fetch.py
    python collector/run_local.py                                  # about four minutes
    python collector/analyze.py collector/_lab/<stamp> --out results/<date>/collector
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import httpx

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
CH05 = LAB.parent / "ch05"
for folder in (HERE, LAB / "ledger", CH05 / "harness", CH05 / "mcp-server", CH05 / "tracing", CH05 / "golden"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import client as harness  # noqa: E402  chapter 5's harness
import fake_otlp  # noqa: E402
import fetch  # noqa: E402
import offline  # noqa: E402  the ledger's: only loopback connections from this process
import otelcol  # noqa: E402
import policies  # noqa: E402
import run_golden  # noqa: E402  chapter 5's golden set and its expectations
import trace_setup as tracing  # noqa: E402
from gateway_model import GatewayModel, pinned_tool_specs  # noqa: E402

MASTER_KEY = "sk-larkspur-lab-ch16"  # a local value for the proxy and its one caller, not a secret
BACKENDS = (("primary", 8801), ("fallback", 8802), ("self-hosted", 8803))  # the ports chapter 5's config names
TOOL_IDENTITY = "larkspur-ops-reader"
PACE_S = 1.1
SLOW_S = 12.0
PADDING_WORDS = 170_000  # at the fakes' stand-in price, 3 US dollars a million input tokens: about 0.51
QUIET_S = 7.0            # longer than the SDK's 5-second export delay in every process
PHASES = (("every-run", 100.0, 1), ("sampled", None, 5))


@dataclass
class Spec:
    kind: str
    case: str
    question: str
    allowed: dict[str, set[str]]
    answer: str | None
    calls: list[list[Any]] | None
    delay_s: float = 0.0
    failing: tuple[int, ...] = ()


@dataclass
class Result:
    phase: str
    kind: str
    case: str
    trace_id: str
    question: str
    started: float
    ended: float
    answer: str | None
    error: str | None
    passed: bool
    model_calls: int
    cost_usd: float | None
    tool_calls: list[list[Any]] = field(default_factory=list)


def specials() -> list[Spec]:
    both = run_golden.BOTH_TOOLS
    return [
        Spec("refused", "refused-alerts", "Any alerts for claims-api in the last 30 minutes?", harness.ALLOWED,
             "Refused: get_recent_alerts is not an allowed call.", []),
        Spec("over-budget", "over-budget-pasted-log", "Please restart claims-api. " + " ".join(["filler"] * PADDING_WORDS),
             both, "I can only read the namespace: there is no tool to restart claims-api.", []),
        Spec("fallback", "fallback-primary-down", "Is billing-worker healthy?", both,
             "billing-worker has 4 of 4 pods ready.", [["get_pod_status", {"service": "billing-worker"}]], failing=(8801,)),
        Spec("slow", "slow-model", "Is policy-admin healthy?", both, "policy-admin has 2 of 2 pods ready.",
             [["get_pod_status", {"service": "policy-admin"}]], delay_s=SLOW_S),
        Spec("failed", "failed-both-down", "Is quote-engine healthy?", both, None, None, failing=(8801, 8802)),
    ]


def golden(rounds: int) -> list[Spec]:
    cases = run_golden.load_cases()
    return [Spec("golden", case["id"], case["question"], run_golden.BOTH_TOOLS, case["expect"]["answer"],
                 run_golden.expected_calls(case)) for _ in range(rounds) for case in cases]


class Delayed:
    """The gateway model, made slow before its first call: a slow run without touching chapter 5's code."""

    def __init__(self, inner: GatewayModel, seconds: float) -> None:
        self.inner, self.seconds, self.waited = inner, seconds, False
        self.__name__ = getattr(inner, "__name__", type(inner).__name__)  # the harness's span names the model

    @property
    def calls(self) -> list:
        return self.inner.calls

    def __call__(self, messages: list[dict]) -> dict:
        if not self.waited:
            self.waited = True
            time.sleep(self.seconds)
        return self.inner(messages)


class Tee(io.TextIOBase):
    """The harness log goes to the shared file and, for this run's checks, to memory."""

    def __init__(self, stream: TextIO) -> None:
        self.stream, self.buffer = stream, io.StringIO()

    def write(self, text: str) -> int:
        self.stream.write(text)
        self.buffer.write(text)
        return len(text)

    def flush(self) -> None:
        self.stream.flush()


# --- the processes ---------------------------------------------------------------------------------------

def wait_for(url: str, seconds: float, proc: subprocess.Popen) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{url} did not come up: the process exited with {proc.returncode}")
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{url} did not come up in {seconds:.0f} s")


def wait_port(port: int, seconds: float, proc: subprocess.Popen) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"127.0.0.1:{port} did not open: the process exited with {proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError(f"127.0.0.1:{port} did not open in {seconds:.0f} s")


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class Stack:
    """Chapter 5's backends, gateway and MCP server, each exporting OTLP to the Collector's port."""

    def __init__(self, work: Path, collector_port: int) -> None:
        self.work, self.procs, self.logs = work, [], []
        self.env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
                        OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{collector_port}",
                        LARKSPUR_TRACE_TOOL_ARGS="1", LITELLM_MASTER_KEY=MASTER_KEY,
                        LITELLM_LOCAL_MODEL_COST_MAP="True", GATEWAY_LOG_FILE=str(work / "gateway.jsonl"),
                        TOOL_IDENTITY=TOOL_IDENTITY, TOOL_LOG_FILE=str(work / "server.jsonl"))
        self.env.pop("TRACE_FILE", None)
        self.gateway_url = ""
        self.server_url = ""

    def _start(self, name: str, args: list[str], cwd: Path | None = None) -> subprocess.Popen:
        log = (self.work / f"{name}.out.log").open("ab")
        self.logs.append(log)
        proc = subprocess.Popen(args, cwd=str(cwd) if cwd else None, env=self.env, stdout=log, stderr=subprocess.STDOUT)
        self.procs.append(proc)
        return proc

    def start(self) -> Stack:
        busy = [port for _, port in BACKENDS if not port_free(port)]
        if busy:
            raise RuntimeError(f"ports {busy} are taken; chapter 5's gateway config names 8801 to 8803")
        for name, port in BACKENDS:
            proc = self._start(f"backend-{name}", [sys.executable, str(CH05 / "gateway" / "fake_backend.py"),
                                                   "--name", name, "--port", str(port)])
            wait_for(f"http://127.0.0.1:{port}/health", 30, proc)
        litellm = shutil.which("litellm", path=str(Path(sys.executable).parent))
        if not litellm:
            raise RuntimeError("the litellm console script isn't next to this interpreter; use chapter 5's environment")
        gateway_port, server_port = otelcol.free_port(), otelcol.free_port()
        proc = self._start("gateway", [litellm, "--config", "litellm.config.yaml", "--port", str(gateway_port),
                                       "--host", "127.0.0.1"], cwd=CH05 / "gateway")
        self.gateway_url = f"http://127.0.0.1:{gateway_port}"
        wait_for(f"{self.gateway_url}/health/liveliness", 180, proc)
        proc = self._start("mcp-server", [sys.executable, str(CH05 / "mcp-server" / "server.py"),
                                          "--transport", "streamable-http", "--port", str(server_port)])
        wait_port(server_port, 60, proc)
        self.server_url = f"http://127.0.0.1:{server_port}/mcp"
        return self

    def stop(self) -> None:
        for proc in self.procs:
            proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        for log in self.logs:
            log.close()


def set_failing(port: int, fail: bool) -> None:
    httpx.post(f"http://127.0.0.1:{port}/control", json={"fail": fail}, timeout=5).raise_for_status()


# --- the runs ---------------------------------------------------------------------------------------------

async def one(spec: Spec, phase: str, stack: Stack, log: TextIO) -> Result:
    model: Any = GatewayModel(stack.gateway_url, "larkspur-chat", tools=pinned_tool_specs(harness.LOCK_PATH, set(spec.allowed)),
                              api_key=MASTER_KEY, timeout_s=120)
    if spec.delay_s:
        model = Delayed(model, spec.delay_s)
    trace_id = tracing.new_trace_id()
    tee = Tee(log)
    for port in spec.failing:
        set_failing(port, True)
    started, answer, error = time.time(), None, None
    try:
        answer = await harness.run_harness(stack.server_url, spec.question, model=model, trace_id=trace_id,
                                           log=tee, allowed=spec.allowed)
    except Exception as exc:  # the failed run ends here, as a run whose gateway answered 503 does
        error = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        for port in spec.failing:
            set_failing(port, False)
    ended = time.time()
    entries = [json.loads(line) for line in tee.buffer.getvalue().splitlines() if line.strip()]
    tool_calls = [[e["tool"], e["args"]] for e in entries if e.get("event") == "tool_call"]
    passed = (error is None and answer == spec.answer and tool_calls == spec.calls) if spec.answer is not None \
        else error is not None
    costs = [c.cost_usd for c in model.calls if c.cost_usd is not None]
    question = spec.question if len(spec.question) < 200 else f"{spec.question[:40]}... ({len(spec.question.split()):,} words)"
    return Result(phase, spec.kind, spec.case, trace_id, question, started, ended, answer, error, passed,
                  len(model.calls), round(sum(costs), 8) if costs else None, tool_calls)


def run_specs(specs: list[Spec], phase: str, stack: Stack, log: TextIO) -> list[Result]:
    results: list[Result] = []
    for spec in specs:
        began = time.time()
        results.append(asyncio.run(one(spec, phase, stack, log)))
        rest = PACE_S - (time.time() - began)
        if rest > 0:
            time.sleep(rest)
    return results


def settle(tap: fake_otlp.Receiver, seconds: float = QUIET_S, limit: float = 60.0) -> None:
    """Wait until the tap has seen nothing new for `seconds`: every process has exported its last spans."""
    deadline, seen, quiet_since = time.time() + limit, -1, time.time()
    while time.time() < deadline:
        count = len(tap.records)
        if count != seen:
            seen, quiet_since = count, time.time()
        elif time.time() - quiet_since >= seconds:
            return
        time.sleep(0.25)


def wait_for_kept(receivers: list[fake_otlp.Receiver], expected: dict[str, int], limit: float) -> None:
    """Until every kept trace has all its spans at every receiver, or the limit."""
    deadline = time.time() + limit
    while time.time() < deadline:
        if all(all(len(rec_spans.get(t, [])) >= n for t, n in expected.items())
               for rec_spans in (fake_otlp.by_trace(r.spans()) for r in receivers)):
            return
        time.sleep(0.5)


def phase(name: str, share: float | None, rounds: int, exe: Path, stack: Stack, log: TextIO, work: Path,
          collector_port: int, setup: tracing.TracingSetup, *, start_stack: bool = False) -> dict[str, Any]:
    """One Collector, its three fakes, the runs, and every record they leave, in work/<name>/."""
    folder = work / name
    folder.mkdir()
    decision_wait = float(policies.config()["processors"]["tail_sampling"]["decision_wait"].rstrip("s"))
    with fake_otlp.langfuse() as lf, fake_otlp.cloudwatch() as cw, fake_otlp.Receiver("tap", "/v1/traces") as tap:
        env = otelcol.environment(span_file=folder / "spans.jsonl", langfuse_endpoint=f"{lf.url}/api/public/otel",
                                  share_percent=share, work=folder)
        metrics_port = otelcol.free_port()
        extra = otelcol.overlay(otlp_port=collector_port, cloudwatch_url=cw.url, metrics_port=metrics_port, tap_url=tap.url)
        collector = otelcol.Collector(exe, folder, env, extra).start()
        try:
            if start_stack:  # the first Collector listens before any process can send it a span
                stack.start()
            results = run_specs(golden(rounds) + specials(), name, stack, log)
            setup.provider.force_flush()
            settle(tap)
            cfg = policies.settings(percent=share)
            per_run = policies.budgets()
            tapped = fake_otlp.by_trace(tap.spans())
            expected = {r.trace_id: len(tapped.get(r.trace_id, [])) for r in results
                        if policies.decide(r.trace_id, policies.features(tapped.get(r.trace_id, [])), per_run=per_run,
                                           threshold_ms=cfg["threshold_ms"], salt=cfg["salt"], percent=cfg["percent"])["kept"]}
            wait_for_kept([lf, cw], expected, decision_wait + 40)
            time.sleep(3)  # anything that shouldn't have come
            metrics = httpx.get(f"http://127.0.0.1:{metrics_port}/metrics", timeout=10).text
        finally:
            code = collector.stop()
        (folder / "metrics.txt").write_text(metrics, encoding="utf-8", newline="\n")
        tap.write(folder / "tap.jsonl")
        lf.write(folder / "langfuse.jsonl")
        cw.write(folder / "cloudwatch.jsonl", raw=True)
    (folder / "runs.jsonl").write_text("".join(json.dumps(asdict(r)) + "\n" for r in results), encoding="utf-8", newline="\n")
    meta = {"phase": name, "share_percent": share if share is not None else cfg["percent"], "collector_port": collector_port,
            "collector_started": collector.started_at, "collector_exit": code, "decision_wait_s": decision_wait,
            "feature_gates": list(otelcol.FEATURE_GATES), "runs": len(results)}
    (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", type=Path, help="raw output folder (default collector/_lab/<stamp>)")
    parser.add_argument("--sampled-rounds", type=int, default=PHASES[1][2],
                        help=f"times the golden set runs in the sampled phase (default {PHASES[1][2]})")
    args = parser.parse_args(argv)
    phases = [PHASES[0], (PHASES[1][0], PHASES[1][1], args.sampled_rounds)]
    exe = fetch.verified()  # refuses to start on a tarball or a binary that isn't the pinned one
    offline.block_network()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = args.work or HERE / "_lab" / stamp
    work.mkdir(parents=True)
    collector_port = otelcol.free_port()
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"http://127.0.0.1:{collector_port}"
    os.environ["LARKSPUR_TRACE_TOOL_ARGS"] = "1"
    os.environ.pop("TRACE_FILE", None)
    setup = tracing.configure("harness")
    stack = Stack(work, collector_port)
    metas = []
    with (work / "harness.jsonl").open("a", encoding="utf-8", newline="\n") as log:
        try:
            for index, (name, share, rounds) in enumerate(phases):
                metas.append(phase(name, share, rounds, exe, stack, log, work, collector_port, setup,
                                   start_stack=index == 0))
        finally:
            stack.stop()
    (work / "run.json").write_text(json.dumps({"stamp": stamp, "phases": metas, "python": sys.version.split()[0]},
                                              indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"raw records in {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
