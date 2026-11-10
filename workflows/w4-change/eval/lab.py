"""The live wiring for W4's model run: start the gateway and the two A2A servers, run the golden changes
through the scribe with the risk scorer's rationale written by a local model, score, and record (step 5b).

Mirrors W3's eval/lab.py. The gateway is chapter 5's LiteLLM proxy with W2's Ollama-backed config and
W4's manifest (MANIFEST_DIR); the analyst and the risk scorer run as subprocesses under their identities,
the risk scorer's rationale seam pointed at the gateway (W4_MODEL_BASE_URL) so a model writes the prose;
the scribe runs in-process over the golden set and writes each pack to the ServiceNow and GitHub stores;
eval/score.py scores the packs. The class is the rubric's throughout: the model touches only the rationale.

Run (from workflows/w4-change):  python eval/lab.py --model-tag gpt-oss-20b
                                 python eval/lab.py --model-tag gemma4-12b --config ../w2-ops-assistant/gateway/litellm.gemma.yaml --ollama-port 11435
Needs Ollama with the model pulled (gpt-oss:20b loads on the 0.22.1 on PATH; Gemma 4 12B needs the portable
0.40.13, served on another port: --ollama-port rewrites the config's api_base into a copy under _lab/). If
the gateway or a server will not start, it records what ran and stops. Everything it starts is stopped at
the end. The agents' logs are kept beside the results (logs-<tag>/) and eval/metrics.py computes W4-D16's
metrics from them; the summary records the versions the run used.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
W4 = HERE.parent
W2 = W4.parent / "w2-ops-assistant"
CH05 = W4.parents[1] / "labs" / "ch05"
SCRATCH = Path(os.environ.get("W4_LAB_SCRATCH", HERE / "_lab"))
for folder in (W4 / "a2a", W4 / "servers", W4 / "tests", HERE, CH05 / "tracing"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import a2a_support as support  # noqa: E402  (the test launchers; plain stdlib)
import analyst  # noqa: E402
import risk_scorer  # noqa: E402
import metrics as metrics_mod  # noqa: E402
import run_changes as runner  # noqa: E402
import score as scoring  # noqa: E402

GATEWAY_KEY = "sk-w4-lab"  # the proxy's master key for this run, a local value, not a secret
WORKFLOW = "w4-change"
DEFAULT_CONFIG = W2 / "gateway" / "litellm.config.yaml"


def wait_port(port: int, deadline_s: float = 120.0) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def api_base(config: Path) -> str:
    """The first api_base the config names: where the model runs, for the version the summary records."""
    for line in config.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("api_base:"):
            return line.split(":", 1)[1].strip()
    return ""


def versions(config: Path) -> dict[str, str]:
    """What the run ran on: the libraries, and the Ollama behind the config's api_base."""
    import importlib.metadata as meta
    out = {"python": sys.version.split()[0], "a2a-sdk": meta.version("a2a-sdk"), "litellm": meta.version("litellm")}
    base = api_base(config)
    if base:
        try:
            import httpx
            out["ollama"] = httpx.get(base.rstrip("/") + "/api/version", timeout=5.0).json().get("version", "?")
        except Exception:
            out["ollama"] = "unreachable"
    return out


def start_gateway(config: Path, out_dir: Path, ollama_port: int | None = None) -> tuple[int, subprocess.Popen]:
    """Chapter 5's proxy on a free port, its hooks pointed at W4's manifest. With an Ollama port, the config's
    api_base is rewritten into a copy under out_dir, which the proxy and its hooks then both read; the grid's
    model_info is the same in both."""
    port = support.free_port()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "LITELLM_MASTER_KEY": GATEWAY_KEY,
           "MANIFEST_DIR": str(W4 / "manifest"), "GATEWAY_LOG_FILE": str(out_dir / "gateway.jsonl")}
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    hooks_dir = config.parent  # the hooks module (gateway_hooks) imports from the original config's folder
    if ollama_port:
        rewritten = out_dir / config.name
        text = config.read_text(encoding="utf-8").replace("http://127.0.0.1:11434", f"http://127.0.0.1:{ollama_port}")
        rewritten.write_text(text, encoding="utf-8")
        config = rewritten
    # The hooks refuse to start unless GATEWAY_CONFIG names the file the proxy was started with (W1's guard).
    env["GATEWAY_CONFIG"] = str(config.resolve())
    beside = Path(sys.executable).parent / "litellm.exe"
    exe = os.environ.get("W4_LITELLM") or (str(beside) if beside.exists() else "litellm")
    stderr = (out_dir / "gateway.stderr").open("w", encoding="utf-8")
    proc = subprocess.Popen([exe, "--config", str(config), "--host", "127.0.0.1", "--port", str(port)],
                            env=env, stdout=stderr, stderr=subprocess.STDOUT, text=True, cwd=str(hooks_dir))
    if not wait_port(port, 150):
        proc.terminate()
        raise RuntimeError(f"the gateway did not come up on {port}; see {out_dir / 'gateway.stderr'}")
    return port, proc


def gateway_events(out_dir: Path) -> dict[str, int]:
    path = out_dir / "gateway.jsonl"
    if not path.exists():
        return {}
    events = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events[json.loads(line).get("event", "?")] += 1
            except json.JSONDecodeError:
                events["unparsed"] += 1
    return dict(events)


def run_all(changes: list[dict[str, Any]], model_tag: str, config: Path | None = None,
            ollama_port: int | None = None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    out_dir = SCRATCH / "run"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("servicenow.json", "comments.json", "gateway.jsonl", "gateway.stderr", "scribe.jsonl",
                 "analyst/agent.log", "risk/agent.log"):
        (out_dir / name).unlink(missing_ok=True)
    config = config or DEFAULT_CONFIG
    if ollama_port:  # the version check reaches the port the run will use
        probe = out_dir / "probe.yaml"
        probe.write_text(f"api_base: http://127.0.0.1:{ollama_port}\n", encoding="utf-8")
        ran_on = versions(probe)
    else:
        ran_on = versions(config)
    os.environ["SERVICENOW_STATE_FILE"] = str(out_dir / "servicenow.json")
    os.environ["GITHUB_COMMENTS_FILE"] = str(out_dir / "comments.json")

    gateway_port, gateway = start_gateway(config, out_dir, ollama_port)
    gateway_url = f"http://127.0.0.1:{gateway_port}"
    model_env = {"W4_MODEL_BASE_URL": gateway_url + "/v1", "W4_MODEL_NAME": "larkspur-chat",
                 "W4_MODEL_API_KEY": GATEWAY_KEY, "W4_WORKFLOW": WORKFLOW}
    servers = []
    packs: dict[str, dict[str, Any]] = {}
    log = (out_dir / "scribe.jsonl").open("w", encoding="utf-8")
    try:
        (out_dir / "analyst").mkdir(exist_ok=True)
        (out_dir / "risk").mkdir(exist_ok=True)
        a = support.launch(analyst, support.ANALYST_IDENTITY, "ANALYST_CALLER_TOKENS", support.ANALYST_CALLERS,
                           out_dir / "analyst")
        servers.append(a)
        r = support.launch(risk_scorer, support.RISK_SCORER_IDENTITY, "RISK_SCORER_CALLER_TOKENS",
                           support.RISK_CALLERS, out_dir / "risk", extra=model_env)
        servers.append(r)
        for change in changes:
            started = time.perf_counter()
            try:
                pack = asyncio.run(runner.run_change(change, identity=support.SCRIBE_IDENTITY,
                                                     token=support.SCRIBE_TOKEN, analyst_url=a.url,
                                                     risk_scorer_url=r.url, log=log))
            except BaseException as exc:  # recorded as a failed change; the run goes on
                import traceback
                pack = {"change_ref": change["change_ref"], "written": False, "evidence": None, "risk": None,
                        "error": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]}
            pack["seconds"] = round(time.perf_counter() - started, 1)
            packs[change["id"]] = pack
            verdict = scoring.score(change, pack)
            risk = (pack.get("risk") or {}).get("risk_class")
            print(f"{'PASS' if verdict['pass'] else 'FAIL'} {change['id']} {change['change_ref']:20s} "
                  f"{str(risk):6s} {pack['seconds']:6.1f}s rationale_ok={verdict['rationale_ok']}", flush=True)
    finally:
        log.close()
        for s in servers:
            support.stop(s)
        gateway.terminate()
        try:
            gateway.wait(timeout=20)
        except Exception:
            gateway.kill()
    results = runner.score_all(changes, packs)
    summary = scoring.summarize(results)
    summary["model"] = model_tag
    summary["measured"] = date.today().isoformat()
    summary["versions"] = ran_on
    summary["gateway_events"] = gateway_events(out_dir)
    summary["seconds_total"] = round(sum(p.get("seconds", 0) for p in packs.values()), 1)
    return packs, results, summary


def scrub(text: str) -> str:
    """The kept logs name the tracing file by its absolute path; the machine's part becomes <companion>."""
    root = json.dumps(str(W4.parents[1]))[1:-1]  # as json_line escaped it
    return text.replace(root, "<companion>")


def write_results(model_tag: str, packs: dict[str, Any], results: list[dict[str, Any]],
                  summary: dict[str, Any]) -> Path:
    out = HERE / "results" / date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"packs-{model_tag}.json").write_text(json.dumps(packs, indent=1, sort_keys=True, default=str) + "\n",
                                                  encoding="utf-8")
    (out / f"results-{model_tag}.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    (out / f"summary-{model_tag}.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    (out / f"readme-{model_tag}.md").write_text(runner.readme_table({model_tag: summary}) + "\n", encoding="utf-8")
    logs = out / f"logs-{model_tag}"
    logs.mkdir(exist_ok=True)
    run = SCRATCH / "run"
    for source, name in ((run / "scribe.jsonl", "scribe.jsonl"), (run / "analyst" / "agent.log", "analyst.jsonl"),
                         (run / "risk" / "agent.log", "risk-scorer.jsonl")):
        if source.exists():
            (logs / name).write_text(scrub(source.read_text(encoding="utf-8")), encoding="utf-8")
    measured = metrics_mod.metrics(out, model_tag)
    (out / f"metrics-{model_tag}.json").write_text(json.dumps(measured, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model-tag", default="gpt-oss-20b")
    parser.add_argument("--config", type=Path, help="a LiteLLM config; default W2's Ollama-backed one")
    parser.add_argument("--only", help="comma-separated change IDs")
    parser.add_argument("--ollama-port", type=int, help="serve the config's model from another Ollama (the portable 0.40.13)")
    args = parser.parse_args(argv)
    changes = scoring.load_changes(HERE / "changes.yaml")
    if args.only:
        wanted = set(args.only.split(","))
        changes = [c for c in changes if c["id"] in wanted]
    packs, results, summary = run_all(changes, args.model_tag, args.config, args.ollama_port)
    out = write_results(args.model_tag, packs, results, summary)
    print(json.dumps(summary, indent=1))
    print(runner.readme_table({args.model_tag: summary}))
    print(metrics_mod.table({args.model_tag: metrics_mod.metrics(out, args.model_tag)}))
    print(f"results in {out}")
    return 0 if summary["passed"] == summary["changes"] else 1


if __name__ == "__main__":
    sys.exit(main())
