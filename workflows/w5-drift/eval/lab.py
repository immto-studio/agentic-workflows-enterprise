"""The live wiring for W5's model run: start chapter 5's gateway and the four readers, run the golden nights
with the pull requests' prose written by a local model, score, and record (step 5).

Mirrors W4's eval/lab.py. The gateway is chapter 5's LiteLLM proxy on W2's Ollama-backed config with W5's
manifest (MANIFEST_DIR), loaded from a copy under eval/_lab/ that GATEWAY_CONFIG names (W1's guard: the
hooks refuse any other file), with the config's api_base rewritten for another Ollama port when asked
(--ollama-port, the portable 0.40.13 for Gemma 4 12B) and num_ctx in every deployment's litellm_params at
least --num-ctx and the completion budget plus 4096 (W2's first run learned Ollama's default 4096 returns
empty content from a reasoning model; the budget is harness/prose.py's 8192 unless --max-tokens says
otherwise), and Ollama's think flag off for gemma4-12b (THINK below). The four readers run as subprocesses
under their identities (harness/launch.py) with the agent's app-only token; the prose seam (harness/prose.py) is pointed at the
gateway through W5_MODEL_BASE_URL, so a model writes every title and body on the larkspur-chat alias with
the workflow and class tags and the night's trace id; eval/run_nights.py drives the three nights on one
fake and one ledger; eval/score.py scores them. The findings and the HCL are the detectors' and the
templates' throughout: the model touches only the prose.

Run (from workflows/w5-drift, PYTHONUTF8=1):
  python eval/lab.py --model-tag gpt-oss-20b
  python eval/lab.py --model-tag gemma4-12b --config ../w2-ops-assistant/gateway/litellm.gemma.yaml --ollama-port 11435

Needs Ollama with the model pulled. Everything it starts is stopped at the end, the gateway included. The
night logs, the readers' logs, and the gateway's log are kept beside the results (logs-<tag>/), scrubbed of
the machine path; eval/metrics.py computes W5-D14's metrics from them; the summary records the versions.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
W2 = W5.parent / "w2-ops-assistant"
SCRATCH = Path(os.environ.get("W5_LAB_SCRATCH", HERE / "_lab"))
for folder in (HERE, W5 / "harness", W5 / "servers", W5 / "writer", W5 / "detect"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import launch  # noqa: E402
import metrics as metrics_mod  # noqa: E402
import prose  # noqa: E402
import run_nights as runner  # noqa: E402
import score as scoring  # noqa: E402
from common import mint_app_token  # noqa: E402

GATEWAY_KEY = "sk-w5-lab"  # the proxy's master key for this run, a local value, not a secret
DEFAULT_CONFIG = W2 / "gateway" / "litellm.config.yaml"
MIN_NUM_CTX = 8192
OLLAMA_DEFAULT = "http://127.0.0.1:11434"
# Ollama's think flag per model tag, written into the loaded config's deployments; --think overrides it. Gemma 4 12B
# thinks before it answers, and on W5's prompt the thinking loops: it drafts a correct title and body, then checks
# each rule of the system prompt again, 87 times in one call, until the budget runs out with no content. With its
# default thinking it wrote 4 of 31 bodies (eval/results/2026-11-03/first-run-thinking-loop/); with think false, 31.
# gpt-oss-20b keeps its default reasoning, which converged in 28 of 31 replies at 8192 tokens.
THINK: dict[str, bool] = {"gemma4-12b": False}


def wait_port(port: int, deadline_s: float = 150.0) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def prepare_config(config: Path, out_dir: Path, ollama_port: int | None, num_ctx: int,
                   think: bool | None = None) -> tuple[Path, int, str]:
    """The config copied under out_dir: api_base rewritten for another Ollama port, num_ctx raised to the
    floor in every deployment that has less or none, and with `think` given, Ollama's think flag set in every
    deployment's litellm_params (LiteLLM forwards it; Gemma 4 12B's thinking looped to the budget on W5's
    prompt in 27 of 31 replies, so its run sets think false). Returns (the copy, the effective num_ctx, the api_base)."""
    text = config.read_text(encoding="utf-8")
    if ollama_port:
        text = text.replace(OLLAMA_DEFAULT, f"http://127.0.0.1:{ollama_port}")
    lines, effective, base = [], 0, ""
    for line in text.splitlines():
        match = re.match(r"^(\s*)num_ctx:\s*(\d+)\s*$", line)
        if match and int(match.group(2)) < num_ctx:
            line = f"{match.group(1)}num_ctx: {num_ctx}"
        if match:
            effective = max(effective, int(line.split(":", 1)[1]))
        if think is not None and re.match(r"^\s*think:", line):
            continue  # the run's own setting replaces any the config carries
        lines.append(line)
        if match and think is not None:
            lines.append(f"{match.group(1)}think: {'true' if think else 'false'}")
        at_base = re.match(r"^(\s*)api_base:\s*(\S+)\s*$", line)
        if at_base:
            base = base or at_base.group(2)
            if "num_ctx:" not in text:
                lines.append(f"{at_base.group(1)}num_ctx: {num_ctx}")
                effective = max(effective, num_ctx)
                if think is not None:
                    lines.append(f"{at_base.group(1)}think: {'true' if think else 'false'}")
    copy = out_dir / config.name
    copy.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return copy, effective, base


def ollama_get(base: str, path: str) -> Any:
    import httpx
    return httpx.get(base.rstrip("/") + path, timeout=5.0).json()


def versions(base: str, num_ctx: int) -> dict[str, Any]:
    """What the run ran on: the libraries, the Ollama behind the api_base, the effective context, the W5 commit."""
    import importlib.metadata as meta
    out: dict[str, Any] = {"python": sys.version.split()[0], "litellm": meta.version("litellm"), "mcp": meta.version("mcp"),
                           "ollama_base": base, "num_ctx": num_ctx, "max_tokens": prose.MAX_TOKENS}
    try:
        out["ollama"] = ollama_get(base, "/api/version").get("version", "?")
    except Exception:
        out["ollama"] = "unreachable"
    try:
        out["w5_commit"] = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(W5), text=True).strip()
    except Exception:
        out["w5_commit"] = "unknown"
    return out


def ollama_ps(base: str) -> list[dict[str, Any]]:
    """What Ollama has loaded, with the context length it gave each model (GET /api/ps)."""
    try:
        models = ollama_get(base, "/api/ps").get("models") or []
    except Exception:
        return []
    return [{"name": m.get("name"), "context_length": m.get("context_length"), "size_vram": m.get("size_vram"),
             "expires_at": m.get("expires_at")} for m in models]


def start_gateway(config: Path, hooks_dir: Path, out_dir: Path) -> tuple[int, subprocess.Popen]:
    """Chapter 5's proxy on a free port, its hooks pointed at W5's manifest and at the loaded copy of the config."""
    port = launch.free_port()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "LITELLM_MASTER_KEY": GATEWAY_KEY,
           "MANIFEST_DIR": str(W5 / "manifest"), "GATEWAY_LOG_FILE": str(out_dir / "gateway.jsonl"),
           "GATEWAY_CONFIG": str(config.resolve())}
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    beside = Path(sys.executable).parent / "litellm.exe"
    exe = os.environ.get("W5_LITELLM") or (str(beside) if beside.exists() else "litellm")
    stderr = (out_dir / "gateway.stderr").open("w", encoding="utf-8")
    proc = subprocess.Popen([exe, "--config", str(config), "--host", "127.0.0.1", "--port", str(port)],
                            env=env, stdout=stderr, stderr=subprocess.STDOUT, text=True, cwd=str(hooks_dir))
    if not wait_port(port):
        proc.terminate()
        raise RuntimeError(f"the gateway did not come up on {port}; see {out_dir / 'gateway.stderr'}")
    return port, proc


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except Exception:
        proc.kill()


def gateway_events(out_dir: Path) -> dict[str, int]:
    path = out_dir / "gateway.jsonl"
    if not path.exists():
        return {}
    events: Counter[str] = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events[json.loads(line).get("event", "?")] += 1
            except json.JSONDecodeError:
                events["unparsed"] += 1
    return dict(events)


def run_all(nights: list[dict[str, Any]], model_tag: str, config: Path | None = None, ollama_port: int | None = None,
            num_ctx: int = MIN_NUM_CTX, think: bool | None = None) -> dict[str, Any]:
    # A fresh folder per run, never a deleted one: the companion lives under OneDrive, which refused the rmdir of a
    # folder it had just seen emptied (the first rerun of 3 November stopped there). The folder is git-ignored.
    out_dir = SCRATCH / f"run-{model_tag}-{time.strftime('%Y%m%dT%H%M%S')}"
    out_dir.mkdir(parents=True)
    config = config or DEFAULT_CONFIG
    copy, effective, base = prepare_config(config, out_dir, ollama_port, num_ctx, think)
    ran_on = versions(base, effective)
    ran_on["think"] = "model default" if think is None else think
    gateway_port, gateway = start_gateway(copy, config.parent, out_dir)
    model_env = {"W5_MODEL_BASE_URL": f"http://127.0.0.1:{gateway_port}/v1", "W5_MODEL_NAME": prose.ALIAS, "W5_MODEL_API_KEY": GATEWAY_KEY}
    previous = {k: os.environ.get(k) for k in model_env}
    os.environ.update(model_env)
    secret = secrets.token_hex(32)
    loaded: list[dict[str, Any]] = []

    def after_night(record: dict[str, Any]) -> None:
        if not loaded:
            loaded.extend(ollama_ps(base))  # while the model is still loaded: the context length Ollama gave it

    readers = None
    try:
        readers = launch.start_readers(out_dir / "readers", secret)
        records, packs, ledger = runner.run_golden(nights, out_dir / "nights", servers=readers.urls, token=mint_app_token(secret),
                                                   gateway_log=out_dir / "gateway.jsonl", after_night=after_night,
                                                   progress=lambda line: print(line, flush=True))
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if readers is not None:
            readers.stop()
        stop(gateway)
    results = runner.score_all(nights, records, packs, ledger, "model")
    summary = scoring.summarize(results, model=model_tag, versions=ran_on, measured=date.today().isoformat())
    summary["gateway_events"] = gateway_events(out_dir)
    summary["ollama_ps"] = loaded
    summary["seconds_total"] = round(sum(r.get("seconds", 0) for r in records.values()), 1)
    logs = {Path(r["log_file"]).name: Path(r["log_file"]) for r in records.values() if r.get("log_file")}
    logs.update({f"{name}-reader.jsonl": path for name, path in readers.logs.items()})
    logs["gateway.jsonl"] = out_dir / "gateway.jsonl"
    return {"records": records, "packs": packs, "results": results, "summary": summary, "ledger_path": ledger.path, "logs": logs}


def write_results(model_tag: str, run: dict[str, Any]) -> Path:
    out = HERE / "results" / date.today().isoformat()
    runner.write_run(out, model_tag, run["records"], run["packs"], run["results"], run["summary"], ledger_path=run["ledger_path"],
                     logs=run["logs"])
    measured = metrics_mod.metrics(out, model_tag)
    (out / f"metrics-{model_tag}.json").write_text(json.dumps(measured, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model-tag", default="gpt-oss-20b")
    parser.add_argument("--config", type=Path, help="a LiteLLM config; default W2's Ollama-backed one")
    parser.add_argument("--ollama-port", type=int, help="serve the config's model from another Ollama (the portable 0.40.13)")
    parser.add_argument("--num-ctx", type=int, default=MIN_NUM_CTX, help="the floor for num_ctx in the loaded config")
    parser.add_argument("--max-tokens", type=int, default=prose.MAX_TOKENS,
                        help="override the prose seam's completion budget for this run (harness/prose.py's MAX_TOKENS, "
                             "8192; gpt-oss-20b spent 1200 and 4096 on reasoning and returned nothing)")
    parser.add_argument("--think", choices=("on", "off"), help="set Ollama's think flag in every deployment of the loaded "
                        "config; left out, THINK's setting for the model tag (off for gemma4-12b), or the model's default")
    args = parser.parse_args(argv)
    prose.MAX_TOKENS = args.max_tokens  # read by ask_model at call time; versions() records it
    nights = scoring.load_nights(HERE / "nights.yaml")
    think = THINK.get(args.model_tag) if args.think is None else args.think == "on"
    # The window holds the prompt (under 800 tokens on these nights) and the whole completion budget, with room.
    run = run_all(nights, args.model_tag, args.config, args.ollama_port, max(args.num_ctx, args.max_tokens + 4096), think)
    out = write_results(args.model_tag, run)
    summary = run["summary"]
    print(json.dumps(summary, indent=1))
    print(runner.readme_table({args.model_tag: summary}))
    print(metrics_mod.table({args.model_tag: metrics_mod.metrics(out, args.model_tag)}))
    print(f"results in {out}")
    return 0 if summary["passed"] == summary["nights"] else 1


if __name__ == "__main__":
    sys.exit(main())
