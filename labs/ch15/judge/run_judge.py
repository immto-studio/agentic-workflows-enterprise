"""Run the judge over the kept outputs through chapter 5's gateway on one local model, and write the results
(chapter 15, step 3, E-D4, E-D12).

The GPU holds one model at a time, so each judge is its own run: gpt-oss-20b judges Gemma 4 12B's outputs and
Nova Lite's, Gemma judges gpt-oss-20b's and Nova Lite's, each also judges the self slice of its own outputs
and the padded copies of the other's (items.assign). The gateway is chapter 5's LiteLLM proxy, started as W5's
eval/lab.py starts it: W2's Ollama-backed config copied into a scratch folder, its api_base moved to another
Ollama port when asked, num_ctx raised to the floor, and Ollama's think flag off for Gemma 4 12B, as W5's runs
had it. W2's gateway_hooks.py loads chapter 5's callback unchanged. The gateway's manifests are the five
workflows' own, so a judge's call carries the evaluated workflow's tag and the case's class, and the gateway
holds it to that workflow's data-class ceiling, Regions, and rate. A Restricted case goes to the restricted
alias and every other case to larkspur-chat (judge.alias_for); in a judge's config both serve the judge's
model, and the runner refuses a config where they don't. The runner keeps under each manifest's
requests_per_minute, since a call over it would be refused.

Every judgement is appended to judged.jsonl in the scratch folder as it is made, so a stopped run resumes with
--scratch and judges only what is left. Afterwards the token counts come from the gateway's log (E-D12), joined
by trace id, and the results go to results/<date>/judge-<workflow>-<judge>.json with the model's digest, the
gateway's alias map, the prompt's and the rubric's hashes, and the set's version, beside a copy of the
gateway's log (judge-gateway-<judge>.jsonl, which holds no prompt or reply). `--workflows` judges some
workflows only: their files and their lines in the log are replaced, and the other workflows' stay as they
were. `--summary` writes the tables the README prints (judge-summary.md) from the result files of both judges,
with no model. Where the folder keeps earlier runs (judge-v1/, judge-v2/, ...), each table names the run and
the rubric behind its numbers, and the summary ends with each run set against the one before.

Run (from labs/ch15, PYTHONUTF8=1, the judge's Ollama up and alone on the GPU):
  python judge/run_judge.py --judge gpt-oss-20b
  python judge/run_judge.py --judge gemma4-12b --config ../../workflows/w2-ops-assistant/gateway/litellm.gemma.yaml --ollama-port 11435
  python judge/run_judge.py --summary results/<date>
  python judge/run_judge.py --judge gpt-oss-20b --workflows w1,w2,w3   those three again; W4's and W5's files stay
  python judge/run_judge.py --judge gemma4-12b --dry-run      what the judge would read, with no model
  python judge/run_judge.py --rewrite judge/_lab/<run> --out results/<date>   a run's files again, no model
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections import Counter, defaultdict, deque
from datetime import date
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True  # import the workflows' code without leaving caches in their folders
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "layers", LAB / "cases", LAB, HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import httpx  # noqa: E402

import convert  # noqa: E402
import items as itemize  # noqa: E402
import judge as judging  # noqa: E402
import registry  # noqa: E402

W2_GATEWAY = registry.path(f"{registry.W2}/gateway")
DEFAULT_CONFIG = W2_GATEWAY / "litellm.config.yaml"
GATEWAY_KEY = "sk-ch15-judge"  # the proxy's master key for this run, a local value, not a secret
OLLAMA_DEFAULT = "http://127.0.0.1:11434"
MIN_NUM_CTX = 16384  # W2's configs ask for 16k; a reasoning model that fills Ollama's default 4096 returns nothing
THINK: dict[str, bool] = {"gemma4-12b": False}  # W5's runs: Gemma 4 12B's thinking looped to the budget
SCRATCH = Path(os.environ.get("CH15_JUDGE_SCRATCH", HERE / "_lab"))
CODE = ("judge/judge.py", "judge/items.py", "judge/run_judge.py", "layers/registry.py", "layers/deterministic.py",
        "layers/trajectory.py", "cases/convert.py", "run_replay.py")
SLICES = ("cross", "self", "padded")
RATE_MARGIN = 0.9  # stay under a manifest's requests_per_minute by this factor
FIRST_RUN = "judge-v1"  # the first run, with rubric v1, kept unchanged in the results folder of the run after it
KEPT_RUN = re.compile(r"judge-v(\d+)")  # an earlier run's folder beside the current files: judge-v1/, judge-v2/, ...
# What a judge's reason names, by the first pattern it matches: how the summary groups the verdicts where the
# judge fails what the rules pass. A description of the reasons, not a verdict on them.
REASONS = (
    ("length or sentence count", r"multiple sentences|single sentence|one sentence|more than one sentence|too long"),
    ("the no-saving sentence missing", r"(?:fails? to|does not|doesn't) (?:state|say|mention)\w* that no saving"),
    ("a cost or a saving", r"\bcost|\bsaving|\bLCU\b|\bunit\b|\bfigure"),
    ("a cause", r"\bcause"),
    ("a step, an action, or a decision", r"\bwill be\b|\bwill remove|\baction\b|\bstep\b|\bpropos"),
    ("the audit trail or an actor", r"audit trail|cloudtrail|\bactor\b"),
    ("the kind or the resource", r"\bkind\b|\bresource\b"),
    ("a plant or a claim", r"finops|\bclaim|planted|instruction"),
    ("a hint or a refusal", r"\bhint|refus|\baccess\b|\bscope\b"),
    ("a fact left out", r"key fact|fails? to (?:state|mention|include|name)|does not (?:state|mention|include)|omit|missing"),
    ("something the reference does not say or contradicts", r"contradict|not (?:in|present in|provided in|given in|stated "
                                                            r"in) the (?:reference|facts)|facts do not|reference does not"),
)


def reason_group(reason: str | None) -> str:
    for name, pattern in REASONS:
        if re.search(pattern, reason or "", re.IGNORECASE):
            return name
    return "other"


# --- the gateway -------------------------------------------------------------------------------------------------

def prepare_config(config: Path, out_dir: Path, ollama_port: int | None, num_ctx: int,
                   think: bool | None) -> tuple[Path, str]:
    """The config copied into out_dir with W5's three changes (eval/lab.prepare_config): api_base on another
    Ollama port when asked, num_ctx at least the floor in every deployment, and Ollama's think flag set when
    given. Returns the copy and the Ollama base it points at."""
    text = config.read_text(encoding="utf-8")
    if ollama_port:
        text = text.replace(OLLAMA_DEFAULT, f"http://127.0.0.1:{ollama_port}")
    lines, base = [], ""
    for line in text.splitlines():
        if think is not None and re.match(r"^\s*think:", line):
            continue  # the run's own setting replaces any the config carries
        match = re.match(r"^(\s*)num_ctx:\s*(\d+)\s*$", line)
        if match and int(match.group(2)) < num_ctx:
            line = f"{match.group(1)}num_ctx: {num_ctx}"
        lines.append(line)
        if match and think is not None:
            lines.append(f"{match.group(1)}think: {'true' if think else 'false'}")
        at_base = re.match(r"^\s*api_base:\s*(\S+)\s*$", line)
        if at_base:
            base = base or at_base.group(1)
    if "num_ctx:" not in text:
        raise ValueError(f"{config.name} sets no num_ctx; the judge's runs need one in every deployment")
    copy = out_dir / config.name
    copy.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return copy, base


def alias_map(config: Path) -> dict[str, str]:
    """The gateway's aliases and the model each serves, from the config the proxy runs."""
    data = registry.read_yaml(config)
    return {m["model_name"]: m["litellm_params"]["model"] for m in data["model_list"]}


def deployment_settings(config: Path) -> dict[str, Any]:
    params = registry.read_yaml(config)["model_list"][0]["litellm_params"]
    return {"num_ctx": params.get("num_ctx"), "think": params.get("think", "model default")}


def prepare_manifests(out_dir: Path) -> Path:
    """The five judged workflows' manifests in one folder, the gateway's MANIFEST_DIR."""
    folder = out_dir / "manifests"
    folder.mkdir(exist_ok=True)
    for workflow in judging.JUDGED:
        source = registry.path(registry.WORKFLOWS[workflow].manifest)
        shutil.copyfile(source, folder / source.name)
    return folder


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port: int, deadline_s: float = 150.0) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def start_gateway(config: Path, manifests: Path, out_dir: Path) -> tuple[int, subprocess.Popen]:
    """Chapter 5's proxy on a free port of 127.0.0.1, from W2's gateway folder, whose gateway_hooks.py loads
    chapter 5's callback; its log, its spans, and its output stay in out_dir."""
    port = free_port()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "LITELLM_MASTER_KEY": GATEWAY_KEY,
           "MANIFEST_DIR": str(manifests), "GATEWAY_LOG_FILE": str(out_dir / "gateway.jsonl"),
           "GATEWAY_CONFIG": str(config.resolve()), "TRACE_FILE": str(out_dir / "traces.jsonl")}
    env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    beside = Path(sys.executable).parent / ("litellm.exe" if os.name == "nt" else "litellm")
    exe = os.environ.get("CH15_LITELLM") or (str(beside) if beside.exists() else "litellm")
    stderr = (out_dir / "gateway.stderr").open("a", encoding="utf-8")
    proc = subprocess.Popen([exe, "--config", str(config), "--host", "127.0.0.1", "--port", str(port)],
                            env=env, stdout=stderr, stderr=subprocess.STDOUT, text=True, cwd=str(W2_GATEWAY))
    if not wait_port(port):
        proc.terminate()
        raise RuntimeError(f"the gateway did not come up on {port}; see {out_dir / 'gateway.stderr'}")
    return port, proc


def wait_for_log(path: Path, trace_ids: set[str], deadline_s: float = 30.0) -> set[str]:
    """Wait until the gateway's log holds a line for every trace id, and return the ones still missing. The
    hooks write a call's line in LiteLLM's success callback, after the reply has gone back, so a proxy stopped
    right after the last reply loses that call's line (the first smoke run of 3 November did)."""
    end = time.time() + deadline_s
    while True:
        logged = {line.get("trace_id") for line in registry.read_jsonl(path)} if path.exists() else set()
        missing = trace_ids - logged
        if not missing or time.time() > end:
            return missing
        time.sleep(0.5)


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def ollama(base: str, path: str) -> Any:
    return httpx.get(base.rstrip("/") + path, timeout=10.0).json()


def model_record(base: str, served: str, think: Any) -> dict[str, Any]:
    """What the judge ran on: the Ollama behind the gateway, the model's name and digest there."""
    name = served.split("/", 1)[-1]
    out: dict[str, Any] = {"served": served, "name": name, "think": think}
    try:
        out["ollama"] = ollama(base, "/api/version").get("version")
        tags = {m["name"]: m for m in ollama(base, "/api/tags").get("models") or []}
        out["digest"] = (tags.get(name) or {}).get("digest")
    except (httpx.HTTPError, ValueError) as exc:
        out["ollama"] = f"unreachable: {type(exc).__name__}"
    return out


def loaded(base: str) -> list[dict[str, Any]]:
    """What Ollama has loaded, with the context length it gave each model (GET /api/ps)."""
    try:
        models = ollama(base, "/api/ps").get("models") or []
    except (httpx.HTTPError, ValueError):
        return []
    return [{"name": m.get("name"), "context_length": m.get("context_length"), "size_vram": m.get("size_vram")}
            for m in models]


# --- the run ---------------------------------------------------------------------------------------------------------

class Pace:
    """Keeps each workflow's calls under its manifest's requests_per_minute, which the gateway enforces."""

    def __init__(self, clock: Any = time.monotonic, sleep: Any = time.sleep) -> None:
        self.clock, self.sleep = clock, sleep
        self.limits = {registry.manifest(w)["workflow"]: registry.manifest(w)["budget"].get("requests_per_minute")
                       for w in judging.JUDGED}
        self.recent: dict[str, deque[float]] = defaultdict(deque)

    def wait(self, tag: str) -> None:
        limit = self.limits.get(tag)
        if not limit:
            return
        allowed, window = max(1, int(limit * RATE_MARGIN)), self.recent[tag]
        while True:
            now = self.clock()
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) < allowed:
                window.append(now)
                return
            self.sleep(60 - (now - window[0]) + 0.05)


def record_key(slice_: str, item: itemize.Item) -> str:
    return json.dumps([slice_, *item.key])


def read_judged(scratch: Path) -> dict[str, dict[str, Any]]:
    path = scratch / "judged.jsonl"
    return {json.dumps(r["key"]): r for r in registry.read_jsonl(path)} if path.exists() else {}


def judge_all(judge: str, assigned: list[tuple[str, itemize.Item]], scratch: Path, client: httpx.Client, base: str,
              key: str, pace: Pace, max_tokens: int = judging.MAX_TOKENS, progress: Any = print,
              after_first: Any = None) -> int:
    """Judge every assigned output not yet in judged.jsonl, appending each judgement as it is made."""
    prompt = judging.load_prompt()
    rubrics = {w: judging.load_rubric(w) for w in judging.JUDGED}
    done = read_judged(scratch)
    todo = [(s, i) for s, i in assigned if record_key(s, i) not in done]
    with (scratch / "judged.jsonl").open("a", encoding="utf-8", newline="\n") as out:
        for n, (slice_, item) in enumerate(todo, 1):
            messages = judging.render(prompt, rubrics[item.workflow], item.conditions, item.reference, item.output)
            pace.wait(item.tag)
            result = judging.judge(client, base, key, messages, item.tag, item.data_class, max_tokens=max_tokens)
            line = {"key": [slice_, *item.key], "judge": judge, **result}
            out.write(json.dumps(line, ensure_ascii=False) + "\n")
            out.flush()
            if n == 1 and after_first:
                after_first()
            shown = result["verdict"] or ("unparsable" if result["unparsable"] else f"error: {result['error']}")
            progress(f"[{n}/{len(todo)}] {item.workflow} {item.model} {item.run} {item.case} {item.part} "
                     f"{slice_}: {shown} ({result['seconds']} s)")
    return len(todo)


# --- the results --------------------------------------------------------------------------------------------------

def gateway_calls(path: Path) -> dict[str, dict[str, Any]]:
    """The gateway's `call` lines by trace id: what each judgement cost in tokens (E-D12)."""
    if not path.exists():
        return {}
    return {line["trace_id"]: line for line in registry.read_jsonl(path) if line.get("event") == "call"}


def _tokens(calls: list[dict[str, Any]]) -> dict[str, int]:
    return {"calls": len(calls), "prompt": sum(c.get("prompt_tokens") or 0 for c in calls),
            "completion": sum(c.get("completion_tokens") or 0 for c in calls)}


def _agrees(verdict: str | None, rules_pass: bool | None) -> bool | None:
    if verdict is None or rules_pass is None:
        return None
    return (verdict == "right") == rules_pass


def write_results(judge: str, all_items: dict[str, list[itemize.Item]], scratch: Path, out: Path,
                  workflows: tuple[str, ...] = judging.JUDGED) -> list[Path]:
    """One file per workflow judged in this run, and the gateway's log beside them. A run on some workflows
    replaces their lines in the log and keeps the other workflows' lines, so the log holds the call behind every
    current result file."""
    run = registry.read_json(scratch / "run.json")
    judged = read_judged(scratch)
    calls = gateway_calls(scratch / "gateway.jsonl")
    prompt = judging.load_prompt()
    assigned = itemize.assign(all_items, judge)
    readings: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    for entry, item in itemize.known(all_items):
        readings[item.key].append({"says": entry["says"], "readme": entry["readme"]})
    out.mkdir(parents=True, exist_ok=True)
    code = [{"path": f"labs/ch15/{c}", "sha256": registry.sha256_of(LAB / c)} for c in CODE]
    written = []
    for workflow in workflows:
        spec = registry.WORKFLOWS[workflow]
        rubric = judging.load_rubric(workflow)
        rows, used = [], []
        for slice_, item in [(s, i) for s, i in assigned if i.workflow == workflow]:
            line = judged.get(record_key(slice_, item))
            if line is None:
                continue  # not judged in this run (a smoke run's --limit)
            call = calls.get(line["trace_id"])
            if call:
                used.append(call | {"slice": slice_})
            messages = judging.render(prompt, rubric, item.conditions, item.reference, item.output)
            if judging.messages_sha256(messages) != line["messages_sha256"]:
                raise RuntimeError(f"{item.key}: the judge read another text than the code renders now")
            alias = judging.alias_for(item.data_class)
            if line.get("alias") != alias or (call and call.get("requested_alias") != alias):
                raise RuntimeError(f"{item.key}: the judgement did not go to {alias}, the alias its class takes")
            tokens = {"prompt": call.get("prompt_tokens"), "completion": call.get("completion_tokens")} if call else None
            rows.append({
                "slice": slice_, "model": item.model, "author": item.author, "run": item.run, "case": item.case,
                "part": item.part, "data_class": item.data_class, "alias": alias,
                "criteria": [c["id"] for c in judging.criteria_for(rubric, item.conditions)],
                "trace_id": line["trace_id"], "messages_sha256": line["messages_sha256"],
                "verdict": line["verdict"], "reason": line["reason"], "unparsable": line["unparsable"],
                "reply": line["reply"], "error": line["error"], "finish_reason": line["finish_reason"],
                "seconds": line["seconds"], "tokens": tokens,
                "rules": item.rules, "verdicts": item.verdicts, "agrees": _agrees(line["verdict"], item.rules["pass"]),
                "readme": readings.get(item.key, []) if slice_ == "cross" else [],
            })
        mine = [i for i in all_items[workflow] if i.author != judge]
        document = {
            "workflow": workflow, "name": spec.name, "judge": judge, "measured": run["measured"],
            "judge_model": run["model"], "gateway": run["gateway"],
            "prompt": {"path": "labs/ch15/judge/prompt.txt", "sha256": registry.sha256_of(judging.PROMPT)},
            "rubric": {"path": f"labs/ch15/judge/rubrics/{workflow}.yaml",
                       "sha256": registry.sha256_of(judging.RUBRICS / f"{workflow}.yaml")},
            "set": {"path": f"labs/ch15/cases/{workflow}.jsonl", "version": convert.version(workflow)},
            "manifest": {"path": spec.manifest, "sha256": registry.sha256_of(registry.path(spec.manifest))},
            "code": code,
            "tokens": _tokens(used) | {"by_slice": {s: _tokens([c for c in used if c["slice"] == s]) for s in SLICES}},
            "outputs": {"of_other_models": len(mine), "judged": sum(i.judged for i in mine),
                        "not_judged": dict(sorted(Counter(i.writer for i in mine if not i.judged).items()))},
            "items": rows,
        }
        path = out / f"judge-{workflow}-{judge}.json"
        path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    log = out / f"judge-gateway-{judge}.jsonl"
    source = scratch / "gateway.jsonl"
    text = source.read_text(encoding="utf-8") if source.exists() else ""
    if set(workflows) != set(judging.JUDGED) and log.exists():
        tags = {registry.manifest(w)["workflow"] for w in workflows}
        kept = [line for line in log.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("workflow") not in tags]
        text = "".join(f"{line}\n" for line in kept) + text
    log.write_text(text, encoding="utf-8", newline="\n")
    return written + [log]


# --- the summary --------------------------------------------------------------------------------------------------

def _load(folder: Path) -> list[dict[str, Any]]:
    return [registry.read_json(p) for p in sorted(folder.glob("judge-w*-*.json"))]


def _of(n: int, total: int) -> str:
    return f"{n} of {total}"


def _table(header: list[str], rows: list[list[Any]]) -> list[str]:
    return ["|" + " |".join(header) + " |", "|" + "---|" * len(header)] + ["|" + " |".join(map(str, r)) + " |" for r in rows]


def kept_runs(folder: Path) -> list[tuple[int, Path]]:
    """The earlier runs kept beside the current files, judge-v1/, judge-v2/, ..., oldest first."""
    found = [(int(m.group(1)), p) for p in folder.iterdir() if p.is_dir() for m in [KEPT_RUN.fullmatch(p.name)] if m]
    return sorted(found)


def runs(folder: Path) -> list[tuple[str, dict[str, Path]]]:
    """Each run's result files by name, oldest first, labeled v1, v2, ... A kept run's folder holds the files a
    later run judged again. A file it doesn't hold is the next folder's that does, so a current file no later run
    judged again belongs to every run from the one that made it."""
    kept = kept_runs(folder)
    places = [(f"v{n}", p) for n, p in kept] + [(f"v{kept[-1][0] + 1 if kept else 1}", folder)]
    names = sorted({p.name for _, place in places for p in place.glob("judge-w*-*.json")})
    out = []
    for i, (label, _) in enumerate(places):
        files = {}
        for name in names:
            held = [place / name for _, place in places[i:] if (place / name).exists()]
            if held:
                files[name] = held[0]
        out.append((label, files))
    return out


def origins(folder: Path) -> dict[str, str]:
    """The run each current result file comes from, by file name: the first run whose file it is."""
    found: dict[str, str] = {}
    for label, files in runs(folder):
        for name, path in files.items():
            if path.parent == folder:
                found.setdefault(name, label)
    return found


def summarize(folder: Path) -> str:
    """The tables the README prints, from both judges' result files: the judge beside the scorer and the
    layers, its agreement with the rules on the prose, where the rules are certain, the readings the
    workflows' READMEs record, the self-preference and verbosity slices, and the tokens. Where the folder keeps
    earlier runs, the current files may come from more than one, so each table with a workflow column names
    the run and the rubric's hash behind its row, and each run is set against the one before at the end."""
    docs = _load(folder)
    rows = [(d, r) for d in docs for r in d["items"]]
    cross = [(d, r) for d, r in rows if r["slice"] == "cross"]
    lines = ["# The judge against the rules", ""]
    history = runs(folder) if kept_runs(folder) else []
    origin = origins(folder) if history else {}

    def rubric(workflow: str, *judges: str) -> list[str]:  # the run and the rubric's hash behind a row, if any
        if not history:
            return []
        found = {f"{origin[f'judge-{workflow}-{j}.json']} {d['rubric']['sha256'][:12]}"
                 for d in docs for j in judges if (d["workflow"], d["judge"]) == (workflow, j)}
        return ["; ".join(sorted(found))]

    if history:
        by_run: dict[str, list[str]] = defaultdict(list)
        for d in docs:
            label = origin[f"judge-{d['workflow']}-{d['judge']}.json"]
            if d["workflow"] not in by_run[label]:
                by_run[label].append(d["workflow"])
        lines += ["The current files come from these runs: " + "; ".join(
            f"{', '.join(sorted(ws))} from run {label}" for label, ws in sorted(by_run.items(), reverse=True)) +
                  ". Each table with a workflow column names the run and the rubric's hash behind its row. The "
                  "earlier runs are kept in " + ", ".join(f"{p.name}/" for _, p in kept_runs(folder)) +
                  ", and the sections at the end set each run against the one before.", ""]

    # 1. Per run: the judge beside the scorer, the deterministic layer, and the rules on the prose.
    groups: dict[tuple, list] = defaultdict(list)
    for d, r in cross:
        groups[(d["workflow"], r["model"], r["run"], d["judge"])].append(r)
    table = []
    for (workflow, model, run, judge), rs in sorted(groups.items()):
        table.append([workflow, model, run, judge, *rubric(workflow, judge), len(rs),
                      sum(bool(r["verdicts"]["scorer"]) for r in rs),
                      sum(bool(r["verdicts"]["deterministic"]) for r in rs), sum(r["rules"]["pass"] is True for r in rs),
                      sum(r["verdict"] == "right" for r in rs), sum(r["agrees"] is True for r in rs),
                      sum(r["verdict"] is None for r in rs)])
    column = ["Rubric"] if history else []
    lines += ["## Per run", ""] + _table(["Workflow", "Outputs of", "Run", "Judge", *column, "Judged", "Scorer",
                                          "Deterministic", "Rules on the prose", "Judge: right",
                                          "Judge and rules agree", "No verdict"], table) + [""]

    # 2. Agreement with the rules on the prose, by workflow and judge.
    groups = defaultdict(list)
    for d, r in cross:
        groups[(d["workflow"], d["judge"])].append(r)
    table = []
    for (workflow, judge), rs in sorted(groups.items()):
        both = [r for r in rs if r["agrees"] is not None]
        table.append([workflow, judge, *rubric(workflow, judge), len(rs), sum(r["verdict"] == "right" for r in rs),
                      sum(r["verdict"] == "wrong" for r in rs), sum(bool(r["unparsable"]) for r in rs),
                      sum(bool(r["error"]) for r in rs), _of(sum(r["agrees"] for r in both), len(both)),
                      sum(r["verdict"] == "right" and r["rules"]["pass"] is False for r in rs),
                      sum(r["verdict"] == "wrong" and r["rules"]["pass"] is True for r in rs)])
    lines += ["## By workflow and judge (cross-judged outputs)", ""] + _table(
        ["Workflow", "Judge", *column, "Judged", "Right", "Wrong", "Unparsable", "Errors", "Agree with the rules",
         "Right where the rules fail", "Wrong where the rules pass"], table) + [""]
    for judge in sorted({d["judge"] for d in docs}):
        reasons = [r["reason"] for d, r in rows if d["judge"] == judge and r["reason"]]
        short = [x for x in reasons if len(x.split()) < 3]
        quoted = ", ".join(f'"{s}"' for s in sorted(set(short)))
        lines.append(f"{judge}: {len(short)} of {len(reasons)} reasons are under three words" +
                     (f", all of them {quoted}." if len(set(short)) == 1 else f": {quoted}." if short else "."))
    lines += ["", "What the reason names where the judge fails what the rules pass (the first match in "
                  "run_judge.REASONS):", ""]
    for (workflow, judge), rs in sorted(groups.items()):
        failed = [r for r in rs if r["verdict"] == "wrong" and r["rules"]["pass"] is True]
        if failed:
            counts = Counter(reason_group(r["reason"]) for r in failed)
            lines.append(f"- {workflow}, {judge}, {len(failed)}: " + "; ".join(f"{name} {n}" for name, n in
                                                                            sorted(counts.items(), key=lambda x: (-x[1], x[0]))))
    lines.append("")

    # 3. Where the rules are certain.
    lines += ["## Where the rules are certain", ""]
    exact = [(d, r) for d, r in cross if r["rules"]["exact"]]
    missed = [(d, r) for d, r in exact if r["verdict"] == "right"]
    lines.append("Outputs a rule fails by a literal the rubric names (W4's rationale, W5's saving, internals, plant "
                 "claims, forbidden words), and how many of them each judge called right: " +
                 "; ".join(f"{judge}, {len([1 for d, _ in exact if d['judge'] == judge])} and "
                           f"{len([1 for d, _ in missed if d['judge'] == judge])}"
                           for judge in sorted({d["judge"] for d in docs})) + ".")
    lines += [f"- {d['workflow']} {r['model']} {r['run']} {r['case']} {r['part']} ({d['judge']}): "
              f"{', '.join(r['rules']['exact'])}" for d, r in sorted(missed, key=lambda x: _sort(x))]
    pads = _padded_pairs(docs)
    flips = [p for p in pads if p["original"] and p["padded"] and p["original"] != p["padded"]]
    lines += ["", f"Padded copies whose verdict differs from the original's: {len(flips)} of "
                  f"{sum(1 for p in pads if p['original'] and p['padded'])}."]
    lines += [f"- {p['workflow']} {p['model']} {p['run']} {p['case']} {p['part']} ({p['judge']}): "
              f"{p['original']} to {p['padded']}" for p in flips]
    same = _same_prompt_splits(docs)
    lines += ["", f"Identical requests that got different verdicts from one judge: {len(same)}."]
    lines += [f"- {s}" for s in same]
    lines.append("")

    # 4. The readings the workflows' READMEs record.
    lines += ["## The readings the workflows' READMEs record", ""] + _table(
        ["Workflow", *column, "Outputs of", "Run", "Case", "README says", "Judge said", "Rules on the prose", "README"],
        _known_rows(docs, rubric)) + [""]

    # 5. Self-preference.
    lines += ["## Self-preference (the self slice)", ""] + _table(
        ["Outputs of", "Outputs", "Rules pass", "Judged by itself: right", "Judged by the other: right",
         "Where the rules fail: itself right", "Where the rules fail: the other right"], _self_rows(docs)) + [""]

    # 6. Verbosity.
    table = []
    for judge in sorted({p["judge"] for p in pads}):
        ps = [p for p in pads if p["judge"] == judge]
        table.append([judge, len(ps), sum(p["original"] == p["padded"] and p["padded"] is not None for p in ps),
                      sum(p["original"] == "right" and p["padded"] == "wrong" for p in ps),
                      sum(p["original"] == "wrong" and p["padded"] == "right" for p in ps),
                      sum(p["original"] is None or p["padded"] is None for p in ps)])
    lines += ["## Verbosity (the padded slice)", ""] + _table(
        ["Judge", "Padded copies", "Same verdict", "Right to wrong", "Wrong to right", "No verdict on one"], table) + [""]

    # 7. Tokens.
    table = []
    for d in sorted(docs, key=lambda d: (d["judge"], d["workflow"])):
        t = d["tokens"]
        if d["items"]:
            table.append([d["judge"], d["workflow"], *rubric(d["workflow"], d["judge"]), t["calls"], f"{t['prompt']:,}",
                          f"{t['completion']:,}", round(sum(r["seconds"] or 0 for r in d["items"]), 1)])
    for judge in sorted({d["judge"] for d in docs}):
        ds = [d for d in docs if d["judge"] == judge]
        table.append([judge, "all", *(["the current files"] if history else []), sum(d["tokens"]["calls"] for d in ds),
                      f"{sum(d['tokens']['prompt'] for d in ds):,}", f"{sum(d['tokens']['completion'] for d in ds):,}",
                      round(sum(r["seconds"] or 0 for d in ds for r in d["items"]), 1)])
    lines += ["## Tokens, from the gateway's log", ""] + _table(
        ["Judge", "Workflow", *column, "Calls", "Prompt tokens", "Completion tokens", "Seconds"], table)

    # 8. Each run against the one before: what the rubric changed, and what moved.
    for (first, before), (second, after) in zip(history, history[1:]):
        names = [name for name in sorted(after) if before.get(name) != after[name] and name in before]
        old = [registry.read_json(before[name]) for name in names]
        new = [registry.read_json(after[name]) for name in names]
        lines += [""] + _compare(old, new, first, second, before[names[0]].parent if names else folder)
    return "\n".join(lines) + "\n"


# What each comparison names whatever its verdicts did: the requests its rubric change was made for.
NAMED: dict[tuple[str, str], tuple[str, Any]] = {
    ("v1", "v2"): ("The W2 refusals on w2-14 and the padded W4 rationales, which v1's run failed for the rubric's "
                   "words:", lambda k, same: (k[1], k[5]) == ("w2", "w2-14") or (k[1], k[2]) == ("w4", "padded")),
    ("v2", "v3"): ("Every request whose text v3 changed, the refusals, with its verdict in each run:",
                   lambda k, same: not same),
}


def _compare(old: list[dict[str, Any]], new: list[dict[str, Any]], first: str = "v1", second: str = "v2",
             kept: Path | None = None) -> list[str]:
    """One run against the next on the files the second judged again: each run's hashes, its agreement with
    the rules, and every verdict that moved. A request whose text is the same in both runs read the same rubric,
    so its moves are the judge's own variation at temperature 0, and so is a reply to it in other words; a
    request the rubric changed may have moved for the rubric's sake."""
    def rows(docs: list[dict[str, Any]]) -> dict[tuple, dict[str, Any]]:
        return {(d["judge"], d["workflow"], r["slice"], r["model"], r["run"], r["case"], r["part"]): r
                for d in docs for r in d["items"]}

    def hashes(docs: list[dict[str, Any]]) -> dict[str, str]:
        out = {"judge/prompt.txt": docs[0]["prompt"]["sha256"][:12]} if docs else {}
        out |= {f"judge/rubrics/{d['workflow']}.yaml": d["rubric"]["sha256"][:12] for d in docs}
        return out

    def agreement(docs: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
        out = {}
        for d in docs:
            rs = [r for r in d["items"] if r["slice"] == "cross" and r["agrees"] is not None]
            if rs:
                out[(d["workflow"], d["judge"])] = _of(sum(r["agrees"] for r in rs), len(rs))
        return out

    def where(k: tuple) -> str:
        judge, workflow, slice_, model, run, case, part = k
        return f"{workflow} {model} {run} {case} {part}".rstrip() + f" ({slice_}, {judge})"

    before, after = rows(old), rows(new)
    h1, h2 = hashes(old), hashes(new)
    a1, a2 = agreement(old), agreement(new)
    workflows = ", ".join(sorted({d["workflow"] for d in new}))
    where_kept = f"{kept.name}/" if kept is not None else "its folder"
    with_summary = ", with its own summary" if kept is not None and (kept / "judge-summary.md").exists() else ""
    lines = [f"## Rubric {first} and {second}", "",
             f"Run {first}'s result files for {workflows} are kept unchanged in {where_kept}{with_summary}, and run "
             f"{second} judged the same outputs again. The prompt's and the rubrics' hashes in each run:", ""]
    lines += _table(["File", first, second], [[f, h1.get(f, ""), h2.get(f, "")] for f in sorted(set(h1) | set(h2))])
    lines += ["", "Agreement with the rules on the prose, cross-judged outputs:", ""]
    lines += _table(["Workflow", "Judge", first, second], [[w, j, a1.get((w, j), ""), a2.get((w, j), "")]
                                                          for w, j in sorted(set(a1) | set(a2))]) + [""]
    counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    moved: dict[bool, list[str]] = {True: [], False: []}
    for k in sorted(set(before) & set(after)):
        b, a = before[k], after[k]
        same = b["messages_sha256"] == a["messages_sha256"]
        counts[(k[1], k[0])]["same" if same else "changed"] += 1
        if same and (b["verdict"], b["reason"]) == (a["verdict"], a["reason"]):
            counts[(k[1], k[0])]["same reply"] += 1
        if b["verdict"] != a["verdict"]:
            counts[(k[1], k[0])]["same moved" if same else "changed moved"] += 1
            moved[same].append(f"- {where(k)}: {b['verdict']} to {a['verdict']}")
    lines += ["Verdicts that moved, by whether the rubric changed the request's text, and the requests as before "
              "whose reply (verdict and reason) came back word for word:", ""]
    lines += _table(["Workflow", "Judge", "Requests the rubric changed", "Of them moved", "Requests as before",
                     "Of them moved", "Of them the same reply"],
                    [[w, j, c["changed"], c["changed moved"], c["same"], c["same moved"], c["same reply"]]
                     for (w, j), c in sorted(counts.items())]) + [""]
    lines += ["Where the rubric changed the text:", ""] + (moved[False] or ["- nothing moved"]) + [""]
    lines += ["Where the text was the same, so the judge alone moved:", ""] + (moved[True] or ["- nothing moved"]) + [""]
    if (first, second) in NAMED:
        title, pick = NAMED[(first, second)]
        named = [k for k in sorted(set(before) & set(after))
                 if pick(k, before[k]["messages_sha256"] == after[k]["messages_sha256"])]
        lines += [title, ""] + ([f"- {where(k)}: {before[k]['verdict']} to {after[k]['verdict']}" for k in named]
                                or ["- none"])
    return lines


def _sort(pair: tuple[dict[str, Any], dict[str, Any]]) -> tuple:
    d, r = pair
    return (d["workflow"], r["model"], r["run"], r["case"], r["part"], d["judge"])


def _padded_pairs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for d in docs:
        originals = {(r["model"], r["run"], r["case"], r["part"]): r for r in d["items"] if r["slice"] == "cross"}
        for r in d["items"]:
            if r["slice"] != "padded":
                continue
            o = originals.get((r["model"], r["run"], r["case"], r["part"]))
            out.append({"workflow": d["workflow"], "judge": d["judge"], "model": r["model"], "run": r["run"],
                        "case": r["case"], "part": r["part"], "original": o["verdict"] if o else None,
                        "padded": r["verdict"]})
    return sorted(out, key=lambda p: (p["workflow"], p["judge"], p["model"], p["run"], p["case"], p["part"]))


def _same_prompt_splits(docs: list[dict[str, Any]]) -> list[str]:
    seen: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for d in docs:
        for r in d["items"]:
            if r["verdict"]:
                seen[(d["judge"], r["messages_sha256"])].append((r["verdict"], f"{d['workflow']} {r['run']} {r['case']} {r['part']}"))
    out = []
    for (judge, _), found in sorted(seen.items()):
        if len({v for v, _ in found}) > 1:
            out.append(f"{judge}: " + "; ".join(f"{where} {v}" for v, where in sorted(found, key=lambda x: x[1])))
    return out


def _known_rows(docs: list[dict[str, Any]], rubric: Any = lambda workflow, *judges: []) -> list[list[Any]]:
    """One row per output a workflow's README reads, with what each judge said of it."""
    found: dict[tuple, dict[str, Any]] = {}
    for d in docs:
        for r in d["items"]:
            if r["slice"] != "cross" or not r["readme"]:
                continue
            key = (d["workflow"], r["model"], r["run"], r["case"], r["part"])
            row = found.setdefault(key, {"readings": r["readme"], "rules": r["rules"]["pass"], "judges": [], "by": []})
            row["judges"].append(f"{r['verdict'] or 'no verdict'} ({d['judge']})")
            row["by"].append(d["judge"])
    rows = []
    for (workflow, model, run, case, part), row in sorted(found.items()):
        for reading in row["readings"]:
            rows.append([workflow, *rubric(workflow, *row["by"]), model, run, f"{case} {part}".strip(), reading["says"],
                         "; ".join(sorted(row["judges"])), "pass" if row["rules"] else "fail", reading["readme"]])
    return rows


def _self_rows(docs: list[dict[str, Any]]) -> list[list[Any]]:
    by_output: dict[tuple, dict[str, Any]] = defaultdict(dict)
    for d in docs:
        for r in d["items"]:
            if r["slice"] in ("self", "cross"):
                by_output[(d["workflow"], r["model"], r["run"], r["case"], r["part"])][r["slice"]] = r
    rows = []
    for model in itemize.JUDGES:
        pairs = [v for k, v in sorted(by_output.items()) if k[1] == model and "self" in v and "cross" in v]
        failing = [v for v in pairs if v["self"]["rules"]["pass"] is False]
        rows.append([model, len(pairs), sum(v["self"]["rules"]["pass"] is True for v in pairs),
                     sum(v["self"]["verdict"] == "right" for v in pairs), sum(v["cross"]["verdict"] == "right" for v in pairs),
                     _of(sum(v["self"]["verdict"] == "right" for v in failing), len(failing)),
                     _of(sum(v["cross"]["verdict"] == "right" for v in failing), len(failing))])
    return rows


# --- the command --------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--judge", choices=itemize.JUDGES)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="the LiteLLM config; default W2's on gpt-oss:20b")
    parser.add_argument("--ollama-port", type=int, help="serve the config's model from another Ollama (the portable 0.40.13)")
    parser.add_argument("--think", choices=("on", "off"), help="Ollama's think flag; left out, THINK's setting for the judge")
    parser.add_argument("--num-ctx", type=int, default=MIN_NUM_CTX)
    parser.add_argument("--max-tokens", type=int, default=judging.MAX_TOKENS)
    parser.add_argument("--out", type=Path, default=LAB / "results" / date.today().isoformat())
    parser.add_argument("--scratch", type=Path, help="resume the run whose scratch folder this is")
    parser.add_argument("--limit", type=int, help="judge only the first N outputs of each workflow (a smoke run)")
    parser.add_argument("--workflows", help="judge only these workflows, comma-separated (w1,w2,w3); the result files "
                        "of the others in --out, and their lines in the gateway's log, stay as they are")
    parser.add_argument("--dry-run", action="store_true", help="say what the judge would read, and call nothing")
    parser.add_argument("--summary", type=Path, help="write judge-summary.md from the result files in this folder")
    parser.add_argument("--rewrite", type=Path, help="write a run's result files again from its scratch folder, with "
                        "no model; refused if any request would render differently now")
    args = parser.parse_args(argv)
    if args.summary:
        text = summarize(args.summary)
        (args.summary / "judge-summary.md").write_text(text, encoding="utf-8", newline="\n")
        print(text, end="")
        return 0
    if args.rewrite:
        run = registry.read_json(args.rewrite / "run.json")
        workflows = tuple(run.get("workflows", judging.JUDGED))
        for path in write_results(run["judge"], itemize.build_all(), args.rewrite, args.out, workflows):
            print(f"wrote {path}")
        return 0
    if not args.judge:
        parser.error("--judge is required unless --summary is given")
    workflows = judging.JUDGED
    if args.workflows:
        asked = [w.strip() for w in args.workflows.split(",") if w.strip()]
        unknown = sorted(set(asked) - set(judging.JUDGED))
        if unknown or not asked:
            parser.error(f"--workflows takes some of {', '.join(judging.JUDGED)}; got {args.workflows!r}")
        workflows = tuple(w for w in judging.JUDGED if w in asked)
    problems = convert.check()
    if problems:
        raise SystemExit("the conversion check failed; nothing judged:\n" + "\n".join(problems))
    all_items = itemize.build_all()
    assigned = [p for p in itemize.assign(all_items, args.judge) if p[1].workflow in workflows]
    if args.limit:
        assigned = [p for w in workflows for p in [x for x in assigned if x[1].workflow == w][:args.limit]]
    counts = Counter((item.workflow, slice_) for slice_, item in assigned)
    print(json.dumps({f"{w} {s}": n for (w, s), n in sorted(counts.items())}, indent=1))
    if args.dry_run:
        return 0
    think = THINK.get(args.judge) if args.think is None else args.think == "on"
    scratch = args.scratch or SCRATCH / f"run-{args.judge}-{time.strftime('%Y%m%dT%H%M%S')}"
    scratch.mkdir(parents=True, exist_ok=True)
    copy, base = prepare_config(args.config, scratch, args.ollama_port, max(args.num_ctx, args.max_tokens + 4096), think)
    aliases = alias_map(copy)
    if aliases.get(judging.ALIAS) != aliases.get(judging.RESTRICTED_ALIAS):
        raise SystemExit(f"{args.config.name}: {judging.ALIAS} and {judging.RESTRICTED_ALIAS} serve different models; "
                         "a judge's run serves both from the judge's model")
    run_file = scratch / "run.json"
    if not run_file.exists():
        import importlib.metadata as meta
        run = {"measured": date.today().isoformat(), "judge": args.judge, "workflows": list(workflows),
               "model": model_record(base, aliases[judging.ALIAS], deployment_settings(copy)["think"]),
               "gateway": {"alias_by_class": {"restricted": judging.RESTRICTED_ALIAS, "other": judging.ALIAS},
                           "aliases": aliases,
                           "config": {"source": registry.rel(args.config), "sha256": registry.sha256_of(copy)},
                           "num_ctx": deployment_settings(copy)["num_ctx"], "max_tokens": args.max_tokens,
                           "temperature": judging.TEMPERATURE, "litellm": meta.version("litellm"),
                           "python": sys.version.split()[0]}}
        run_file.write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8", newline="\n")
    recorded = tuple(registry.read_json(run_file).get("workflows", judging.JUDGED))
    if recorded != workflows:
        raise SystemExit(f"{scratch.name} judged {', '.join(recorded)}; resume it with the same --workflows")
    port, gateway = start_gateway(copy, prepare_manifests(scratch), scratch)
    print(f"gateway up on 127.0.0.1:{port}; scratch {scratch}", flush=True)

    def after_first() -> None:  # while the model is loaded: the context length Ollama gave it
        run = registry.read_json(run_file)
        if "loaded" not in run["model"]:
            run["model"]["loaded"] = loaded(base)
            run_file.write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8", newline="\n")

    try:
        with httpx.Client(timeout=judging.TIMEOUT_S) as client:
            judge_all(args.judge, assigned, scratch, client, f"http://127.0.0.1:{port}/v1", GATEWAY_KEY, Pace(),
                      args.max_tokens, progress=lambda line: print(line, flush=True), after_first=after_first)
        answered = {line["trace_id"] for line in read_judged(scratch).values() if not line["error"]}
        missing = wait_for_log(scratch / "gateway.jsonl", answered)
        if missing:
            print(f"the gateway's log has no line for {len(missing)} answered calls", flush=True)
    finally:
        stop(gateway)
    for path in write_results(args.judge, all_items, scratch, args.out, workflows):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
