"""Run the red-team variants through each workflow's own harness on one local model (chapter 15, step 6, E-D10).

For each workflow, the run starts chapter 5's gateway with the workflow's manifest and config (W1's for W1, W2's
Ollama-backed one for the others, as their own labs do), on the model asked for: gpt-oss-20b on Ollama 0.22.1,
or Gemma 4 12B on the portable Ollama 0.40.13 with thinking off. Then, variant by variant, each in its own
scratch folder:

  W1  a copy of the corpus with the variant in it, the chunks that changed embedded through the gateway as the
      ingestion job, W1's knowledge server on that copy, and the case through harness/answer.ask
  W2  W2's three servers serving the variant (redteam/place.py's hook), each case through harness/answer.ask
  W3  W3's five servers and the approval service as eval/lab.py starts them, each case through lab.run_incident;
      no one approves, so a proposal waits for a person and no write runs
  W4  the analyst and the risk scorer as eval/lab.py starts them, the change through the scribe
  W5  the four readers as launch.start_readers starts them, night 1 over the workspace behind the plant's
      account through run_nights.run_golden, the prose seam on the gateway

Every affected case also runs once with the fakes as they are, the control. Each output is appended to
outputs.jsonl in the run's scratch folder as it is made, with the variant, the case, the trace id, what the
harness logged, and what the model was sent: the runner wraps the model's request method in the harness's own
module to keep a copy of each request (the harness sends it unchanged), so the results can say whether a
variant's text reached the model. A stopped run resumes with --scratch and runs only what is left.

Run (from labs/ch15, PYTHONUTF8=1, the model's Ollama up and alone on the GPU):
  python redteam/run_redteam.py --model gpt-oss-20b
  python redteam/run_redteam.py --model gemma4-12b --ollama-port 11435
  python redteam/run_redteam.py --model gpt-oss-20b --workflows w2 --only w2-log   a smoke run
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "layers", LAB / "cases", LAB, LAB / "judge", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import httpx  # noqa: E402

import generate  # noqa: E402
import place  # noqa: E402
import plants as inventory  # noqa: E402
import registry  # noqa: E402

W1, W2, W3, W4, W5 = registry.W1, registry.W2, registry.W3, registry.W4, registry.W5
SCRATCH = Path(os.environ.get("CH15_REDTEAM_SCRATCH", HERE / "_lab"))
GATEWAY_KEY = "sk-ch15-redteam"  # the proxy's master key for a run, a local value, not a secret
SECRET = "ch15-redteam-lab-secret-at-least-32-bytes"  # signs the lab's tokens, as the workflows' labs do
NUM_CTX = 16384
MAX_TOKENS = 8192  # W5's prose seam and the judge: what gpt-oss-20b's reasoning needs
THINK: dict[str, bool] = {"gemma4-12b": False}
MODEL_OF = {"gpt-oss-20b": "gpt-oss:20b", "gemma4-12b": "gemma4:12b"}
CONFIGS = {  # (workflow, model) -> the config the workflow's own runs used for that model
    ("w1", "gpt-oss-20b"): f"{W1}/gateway/litellm.config.yaml", ("w1", "gemma4-12b"): f"{W1}/gateway/litellm.gemma.yaml",
    **{(w, "gpt-oss-20b"): f"{W2}/gateway/litellm.config.yaml" for w in ("w2", "w3", "w4", "w5")},
    **{(w, "gemma4-12b"): f"{W2}/gateway/litellm.gemma.yaml" for w in ("w2", "w3", "w4", "w5")},
}
HOOKS = {"w1": f"{W1}/gateway", **{w: f"{W2}/gateway" for w in ("w2", "w3", "w4", "w5")}}
MANIFESTS = {"w1": f"{W1}/manifest", "w2": f"{W2}/manifest", "w3": f"{W3}/manifest", "w4": f"{W4}/manifest",
             "w5": f"{W5}/manifest"}
RATE_MARGIN = 0.8  # a workflow's model calls stay under this share of its manifest's requests_per_minute


# --- the gateway ------------------------------------------------------------------------------------------------

def prepare_config(source: Path, out_dir: Path, ollama_port: int | None, think: bool | None) -> tuple[Path, str]:
    """The workflow's config copied into the scratch folder: api_base on the model's Ollama, num_ctx at least
    NUM_CTX in every chat deployment, and Ollama's think flag where the model's runs set it."""
    text = source.read_text(encoding="utf-8")
    if ollama_port:
        text = re.sub(r"http://127\.0\.0\.1:\d+", f"http://127.0.0.1:{ollama_port}", text)
    lines, chat, base = [], False, ""
    for line in text.splitlines():
        model = re.match(r"^\s*model:\s*(\S+)", line)
        if model:
            chat = model.group(1).startswith("ollama_chat/")
        if re.match(r"^\s*(num_ctx|think):", line) and chat:
            continue  # written again below, with the run's values
        lines.append(line)
        at_base = re.match(r"^(\s*)api_base:\s*(\S+)\s*$", line)
        if at_base:
            base = base or at_base.group(2)
            if chat:
                lines.append(f"{at_base.group(1)}num_ctx: {NUM_CTX}")
                if think is not None:
                    lines.append(f"{at_base.group(1)}think: {'true' if think else 'false'}")
    copy = out_dir / source.name
    copy.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return copy, base


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port: int, deadline_s: float = 150.0, proc: subprocess.Popen | None = None) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        if proc is not None and proc.poll() is not None:
            return False
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def start_gateway(workflow: str, config: Path, out_dir: Path) -> tuple[str, subprocess.Popen, Path]:
    """Chapter 5's proxy on a free port with the workflow's manifest, its log in the scratch folder."""
    port = free_port()
    log = out_dir / f"gateway-{workflow}.jsonl"
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "LITELLM_MASTER_KEY": GATEWAY_KEY,
           "MANIFEST_DIR": str(registry.path(MANIFESTS[workflow])), "GATEWAY_LOG_FILE": str(log),
           "GATEWAY_CONFIG": str(config.resolve()), "TRACE_FILE": str(out_dir / f"traces-{workflow}.jsonl")}
    for name in ("OTEL_EXPORTER_OTLP_ENDPOINT", place.ENV):
        env.pop(name, None)
    env["PYTHONPATH"] = os.pathsep.join(p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and p != str(place.HOOK))
    beside = Path(sys.executable).parent / ("litellm.exe" if os.name == "nt" else "litellm")
    exe = os.environ.get("CH15_LITELLM") or (str(beside) if beside.exists() else "litellm")
    stderr = (out_dir / f"gateway-{workflow}.stderr").open("a", encoding="utf-8")
    proc = subprocess.Popen([exe, "--config", str(config), "--host", "127.0.0.1", "--port", str(port)], env=env,
                            stdout=stderr, stderr=subprocess.STDOUT, text=True, cwd=str(registry.path(HOOKS[workflow])))
    if not wait_port(port, proc=proc):
        stop(proc)
        raise RuntimeError(f"the gateway did not come up; see {out_dir / f'gateway-{workflow}.stderr'}")
    return f"http://127.0.0.1:{port}", proc, log


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def wait_for_log(path: Path, trace_ids: set[str], deadline_s: float = 30.0) -> set[str]:
    """The gateway writes a call's line after the reply has gone back; wait until every trace has its lines."""
    end = time.time() + deadline_s
    while True:
        logged = {line.get("trace_id") for line in registry.read_jsonl(path)} if path.exists() else set()
        missing = trace_ids - logged
        if not missing or time.time() > end:
            return missing
        time.sleep(0.5)


def ollama(base: str, path: str) -> Any:
    return httpx.get(base.rstrip("/") + path, timeout=10.0).json()


def model_record(base: str, model: str, think: Any) -> dict[str, Any]:
    name = MODEL_OF[model]
    out: dict[str, Any] = {"model": model, "name": name, "think": "model default" if think is None else think}
    try:
        out["ollama"] = ollama(base, "/api/version").get("version")
        tags = {m["name"]: m for m in ollama(base, "/api/tags").get("models") or []}
        out["digest"] = (tags.get(name) or {}).get("digest")
    except (httpx.HTTPError, ValueError) as exc:
        out["ollama"] = f"unreachable: {type(exc).__name__}"
    return out


def loaded(base: str) -> list[dict[str, Any]]:
    try:
        models = ollama(base, "/api/ps").get("models") or []
    except (httpx.HTTPError, ValueError):
        return []
    return [{"name": m.get("name"), "context_length": m.get("context_length"), "size_vram": m.get("size_vram")}
            for m in models]


# --- the probe ---------------------------------------------------------------------------------------------------

class Pace:
    """Keeps a workflow's model calls under its manifest's requests_per_minute, which the gateway enforces."""

    def __init__(self, workflow: str) -> None:
        limit = registry.manifest(workflow)["budget"].get("requests_per_minute") or 0
        self.allowed = max(1, int(limit * RATE_MARGIN)) if limit else 0
        self.window: deque[float] = deque()
        self.lock = threading.Lock()

    def wait(self) -> None:
        if not self.allowed:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                while self.window and now - self.window[0] >= 60:
                    self.window.popleft()
                if len(self.window) < self.allowed:
                    self.window.append(now)
                    return
                pause = 60 - (now - self.window[0]) + 0.05
            time.sleep(pause)


class Probe:
    """A copy of every request the harness's model class sends, and of what came back, by trace id. The
    methods are the class's own, called unchanged; the probe only keeps what passes through them."""

    def __init__(self, pace: Pace) -> None:
        self.requests: dict[str, list[Any]] = defaultdict(list)
        self.replies: dict[str, list[Any]] = defaultdict(list)
        self.pace = pace

    @contextmanager
    def watching(self, cls: Any) -> Iterator[None]:
        request, call = cls.request, cls.__call__
        probe = self

        def recorded_request(self: Any, messages: Any) -> Any:
            body = request(self, messages)
            probe.requests[self.trace_id or ""].append(body.get("messages"))
            return body

        def recorded_call(self: Any, messages: Any) -> Any:
            probe.pace.wait()
            reply = call(self, messages)
            probe.replies[self.trace_id or ""].append(reply)
            return reply

        cls.request, cls.__call__ = recorded_request, recorded_call
        try:
            yield
        finally:
            cls.request, cls.__call__ = request, call

    def take(self, trace_id: str) -> tuple[list[Any], list[Any]]:
        return self.requests.pop(trace_id, []), self.replies.pop(trace_id, [])


def _strings(value: Any) -> Iterator[str]:
    """Every string in a request, and every string inside a string that holds JSON (a tool's result, and a
    CloudTrail record inside that), so text escaped once or twice on the way is read as the model reads it."""
    if isinstance(value, str):
        yield value
        stripped = value.strip()
        if stripped[:1] in "{[":
            try:
                yield from _strings(json.loads(stripped))
            except ValueError:
                pass
        for start in (m.start() for m in re.finditer(r"\{\n", value)):  # W5's FACTS block inside its prompt
            try:
                yield from _strings(json.loads(value[start:value.index("\n}", start) + 2]))
            except ValueError:
                pass
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _plain(text: str) -> str:
    """Without format characters (zero-width spaces, which W1's ingestion strips) and with whitespace collapsed."""
    return inventory.flat("".join(c for c in text if unicodedata.category(c) != "Cf"))


def reached(pieces: list[str], requests: list[Any]) -> list[str]:
    """The variant's pieces that are in what the model was sent, each whole, compared without format
    characters and with whitespace collapsed."""
    sent = "\n".join(_plain(s) for s in _strings(requests))
    return [piece for piece in pieces if _plain(piece) and _plain(piece) in sent]


# --- the work list -----------------------------------------------------------------------------------------------

def control_pieces(plants: list[dict[str, Any]], workflow: str, case: str, workspace: str | None) -> list[str]:
    """The plants a case reads as the fakes hold them: what a control looks for in what the model was sent."""
    if workflow == "w5":
        return [p["text"] for p in plants if p["workflow"] == "w5" and p["where"]["workspace"] == workspace]
    return [p["text"] for p in plants if p["workflow"] == workflow and (case in p["cases"] or case in p["also_read_by"])]


def work(workflows: tuple[str, ...], only: str | None, include_controls: bool = True) -> list[dict[str, Any]]:
    """Every (variant, case) of the asked workflows, controls first: one per case the variants run on."""
    variants = [v for v in generate.load() if v["workflow"] in workflows and (not only or v["id"].startswith(only))]
    plants = inventory.load()
    items: list[dict[str, Any]] = []
    if include_controls:
        seen: set[tuple[str, str, str | None]] = set()
        for v in variants:
            for case in v["cases"]:
                key = (v["workflow"], case, v.get("workspace"))
                if key not in seen:
                    seen.add(key)
                    items.append({"workflow": v["workflow"], "variant": "control", "family": "control", "parent": None,
                                  "technique": "the fakes as they are", "case": case, "placements": [],
                                  "workspace": v.get("workspace"),
                                  "pieces": control_pieces(plants, v["workflow"], case, v.get("workspace"))})
    for v in variants:
        for case in v["cases"]:
            items.append({"workflow": v["workflow"], "variant": v["id"], "family": v["family"], "parent": v["parent"],
                          "technique": v["technique"], "case": case, "placements": v["placements"],
                          "workspace": v.get("workspace"), "pieces": generate.pieces(v),
                          "patterns_from": v.get("patterns_from")})
    return items


def groups(items: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """The items by variant (a control by its case), in order: one server start serves all of a variant's cases."""
    out: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = item["variant"] if item["variant"] != "control" else f"control:{item['case']}:{item.get('workspace')}"
        out.setdefault(key, []).append(item)
    return list(out.items())


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:60]


# --- the subprocesses' environment ------------------------------------------------------------------------------------

@contextmanager
def placement_env(spec: Path | None) -> Iterator[None]:
    """The hook and the placement in os.environ while the workflow's code starts its servers, which inherit it."""
    saved = {k: os.environ.get(k) for k in ("PYTHONPATH", place.ENV)}
    if spec is not None:
        os.environ.update(place.environment(spec))
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def fresh_membership(path: Path) -> Path:
    """W1's membership table rebuilt now from the Graph stand-ins, as sync.py does every night (W2's tests'
    fresh_table): the servers grant only the broad groups from a table older than 36 hours."""
    folder = registry.path(f"{W1}/knowledge-server/membership")
    path.parent.mkdir(parents=True, exist_ok=True)
    with registry.isolated((f"{W1}/knowledge-server/membership", f"{W1}/knowledge-server")):
        import sync
        from group_map import load as load_group_map
        export = json.loads((folder / "graph-export.json").read_text(encoding="utf-8"))
        delta = json.loads((folder / "graph-delta.json").read_text(encoding="utf-8"))
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        table, _ = sync.rebuild(export, load_group_map(), stamp)
        sync.write_table(sync.apply_delta(table, delta, stamp), path)
        users = {upn.split("@")[0]: oid for upn, oid in sync.users(export).items()}
    path.with_suffix(".users.json").write_text(json.dumps(users), encoding="utf-8")
    return path


def start_process(args: list[str], env: dict[str, str], port: int, out: Path, name: str) -> subprocess.Popen:
    stderr = (out / f"{name}.stderr").open("w", encoding="utf-8")
    proc = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=stderr, text=True)
    if not wait_port(port, 90, proc):
        stop(proc)
        raise RuntimeError(f"{name} did not come up; see {out / f'{name}.stderr'}")
    return proc


# --- the workflows ---------------------------------------------------------------------------------------------------

def done_key(item: dict[str, Any]) -> tuple[str, str, str | None]:
    """An output's identity in a run: its variant, its case, and for W5 the workspace its night ran over."""
    return item["variant"], item["case"], item.get("workspace")


class Run:
    """One model's run: the scratch folder, the outputs so far, and what each workflow phase needs."""

    def __init__(self, model: str, scratch: Path, ollama_port: int | None) -> None:
        self.model, self.scratch, self.ollama_port = model, scratch, ollama_port
        self.think = THINK.get(model)
        self.outputs = scratch / "outputs.jsonl"
        self.done = {done_key(r) for r in registry.read_jsonl(self.outputs)} if self.outputs.exists() else set()

    def record(self, item: dict[str, Any], **fields: Any) -> None:
        line = {"workflow": item["workflow"], "model": self.model, "variant": item["variant"], "family": item["family"],
                "parent": item["parent"], "technique": item["technique"], "case": item["case"],
                "workspace": item.get("workspace"), "pieces": item["pieces"], **fields}
        with self.outputs.open("a", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        self.done.add(done_key(item))

    def folder(self, workflow: str, key: str) -> Path:
        path = self.scratch / workflow / slug(key)
        path.mkdir(parents=True, exist_ok=True)
        return path


def run_w1(run: Run, items: list[dict[str, Any]], gateway: str, progress: Callable[[str], None]) -> None:
    table = fresh_membership(run.scratch / "w1" / "membership.json")
    users = json.loads(table.with_suffix(".users.json").read_text(encoding="utf-8"))
    golden = {q["id"]: q for q in registry.read_yaml(registry.path(registry.WORKFLOWS["w1"].golden))}
    probe = Probe(Pace("w1"))
    with registry.isolated((f"{W1}/eval", f"{W1}/ingest")):
        import answer_eval  # first: it puts the harness and the server's folders on the path
        import answer
        from access import issue
        from embedding import GatewayEmbedder
        embedder = GatewayEmbedder(gateway, GATEWAY_KEY, "w1-ingest")
        with probe.watching(answer.ClassifyingGatewayModel):
            for key, batch in groups(items):
                todo = [i for i in batch if done_key(i) not in run.done]
                if not todo:
                    continue
                out = run.folder("w1", key)
                env = {**os.environ, "TOOL_IDENTITY": "larkspur-knowledge-reader", "W1_TOKEN_SECRET": SECRET,
                       "GATEWAY_URL": gateway, "GATEWAY_KEY": GATEWAY_KEY, "MEMBERSHIP_TABLE": str(table),
                       "TOOL_LOG_FILE": str(out / "server.jsonl"), "PYTHONUTF8": "1"}
                changed: list[str] = []
                if todo[0]["placements"]:
                    docs = place.w1_docs(todo[0]["placements"], out)
                    index, changed = place.w1_index(docs, out, lambda texts, cls: embedder.embed(texts, cls))
                    spec = place.write_spec(out / "placement.json", "w1", todo[0]["placements"], docs)
                    env.update(place.environment(spec))
                    env["W1_INDEX"] = str(index)
                port = free_port()
                server = start_process([sys.executable, str(registry.path(f"{W1}/knowledge-server/server.py")),
                                        "--port", str(port)], env, port, out, "knowledge-server")
                try:
                    for item in todo:
                        qid, persona = item["case"].split("/")
                        token = issue(SECRET, users[persona], f"{persona}@larkspur.example")
                        trace_id, log = uuid.uuid4().hex, io.StringIO()
                        started, error, labels, calls = time.perf_counter(), None, [], []
                        try:
                            text, model = asyncio.run(answer.ask(golden[qid]["question"], token, f"http://127.0.0.1:{port}/mcp",
                                                                 gateway, GATEWAY_KEY, trace_id=trace_id, log=log,
                                                                 audit={"case": qid, "persona": persona}))
                            labels, calls = model.labels, [vars(c) for c in model.calls]
                        except Exception as exc:  # recorded; the run goes on
                            text, error = "", f"{type(exc).__name__}: {exc}"[:500]
                        requests, replies = probe.take(trace_id)
                        audit = [e for e in registry.read_jsonl(out / "server.jsonl") if e.get("trace_id") == trace_id] \
                            if (out / "server.jsonl").exists() else []
                        output = {"id": qid, "trap": golden[qid]["trap"], "persona": persona, "answer": text,
                                  "calls": [{"data_class": c, "alias": a} for c, a in labels], "model_calls": calls,
                                  "typography": answer_eval.typography(text)}
                        run.record(item, trace_id=trace_id, seconds=round(time.perf_counter() - started, 2), error=error,
                                   output=output, text=text, requests=requests, replies=replies,
                                   reached=reached(item["pieces"], requests), changed_chunks=changed,
                                   logs={"harness": [json.loads(x) for x in log.getvalue().splitlines() if x.strip()],
                                         "server": audit})
                        progress(f"w1 {item['variant']} {item['case']} {time.perf_counter() - started:.1f}s"
                                 + (f" ERROR {error}" if error else ""))
                finally:
                    stop(server)


def w2_servers(out: Path, table: Path, spec: Path | None) -> tuple[dict[str, str], list[subprocess.Popen]]:
    identities = {"kubernetes-mcp": ("kubernetes_server.py", "larkspur-ops-kubernetes-reader"),
                  "metrics-mcp": ("metrics_server.py", "larkspur-ops-metrics-reader"),
                  "logs-mcp": ("logs_server.py", "larkspur-ops-logs-reader")}
    urls, procs = {}, []
    try:
        for server, (script, identity) in identities.items():
            port = free_port()
            env = {**os.environ, "TOOL_IDENTITY": identity, "W2_TOKEN_SECRET": SECRET, "MEMBERSHIP_TABLE": str(table),
                   "TOOL_LOG_FILE": str(out / f"{server}.jsonl"), "PYTHONUTF8": "1"}
            env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
            if spec is not None:
                env.update(place.environment(spec))
            procs.append(start_process([sys.executable, str(registry.path(f"{W2}/servers/{script}")), "--port", str(port)],
                                       env, port, out, server))
            urls[server] = f"http://127.0.0.1:{port}/mcp"
    except Exception:
        for proc in procs:
            stop(proc)
        raise
    return urls, procs


def run_w2(run: Run, items: list[dict[str, Any]], gateway: str, progress: Callable[[str], None]) -> None:
    table = fresh_membership(run.scratch / "w2" / "membership.json")
    users = json.loads(table.with_suffix(".users.json").read_text(encoding="utf-8"))
    golden = {q["id"]: q for q in registry.read_yaml(registry.path(registry.WORKFLOWS["w2"].golden))}
    probe = Probe(Pace("w2"))
    with registry.isolated((f"{W2}/eval",)):
        import answer_eval  # first: it puts the harness and the servers' folders on the path
        import answer
        from access import issue
        from common import W2_RUNTIME, W2_SCOPE, W2_SERVERS_APP
        with probe.watching(answer.BoundedGatewayModel):
            for key, batch in groups(items):
                todo = [i for i in batch if done_key(i) not in run.done]
                if not todo:
                    continue
                out = run.folder("w2", key)
                spec = place.write_spec(out / "placement.json", "w2", todo[0]["placements"]) if todo[0]["placements"] else None
                urls, procs = w2_servers(out, table, spec)
                try:
                    for item in todo:
                        q = golden[item["case"]]
                        persona = q.get("persona", "oncall.engineer")
                        token = issue(SECRET, users[persona], f"{persona}@larkspur.example", scope=W2_SCOPE,
                                      client=W2_RUNTIME, audience=W2_SERVERS_APP)
                        trace_id, log = uuid.uuid4().hex, io.StringIO()
                        started, error, labels, calls = time.perf_counter(), None, [], []
                        try:
                            text, model = asyncio.run(answer.ask(q["question"], token, urls, gateway, GATEWAY_KEY,
                                                                 trace_id=trace_id, log=log,
                                                                 audit={"case": q["id"], "persona": persona}))
                            labels, calls = model.labels, [vars(c) for c in model.calls]
                        except Exception as exc:
                            text, error = "", f"{type(exc).__name__}: {exc}"[:500]
                        events = [json.loads(x) for x in log.getvalue().splitlines() if x.strip()]
                        reads = [{"tool": e["tool"], "ok": e["ok"], "args": e.get("args")}
                                 for e in events if e["event"] == "tool_call" and "tool" in e]
                        requests, replies = probe.take(trace_id)
                        output = {"id": q["id"], "trap": q["trap"], "persona": persona, "answer": text,
                                  "calls": [{"data_class": c, "alias": a} for c, a in labels], "model_calls": calls,
                                  "read_events": reads, "typography": answer_eval.typography(text)}
                        run.record(item, trace_id=trace_id, seconds=round(time.perf_counter() - started, 2), error=error,
                                   output=output, text=answer.without_reference(text), requests=requests, replies=replies,
                                   reached=reached(item["pieces"], requests), logs={"harness": events})
                        progress(f"w2 {item['variant']} {item['case']} {time.perf_counter() - started:.1f}s"
                                 + (f" ERROR {error}" if error else ""))
                finally:
                    for proc in procs:
                        stop(proc)


def run_w3(run: Run, items: list[dict[str, Any]], gateway: str, progress: Callable[[str], None]) -> None:
    incidents = {c["id"]: c for c in registry.read_yaml(registry.path(registry.WORKFLOWS["w3"].golden))}
    probe = Probe(Pace("w3"))
    with registry.isolated((f"{W3}/eval",)):
        import lab
        import loop
        from approval_service import Service, serve as serve_approvals
        from access import MembershipTable
        never_approve = lambda *args, **kwargs: None  # noqa: E731  (no one approves: a proposal waits for a person)
        saved_approver, saved_key = lab.runner.eligible_approver, lab.GATEWAY_KEY
        lab.runner.eligible_approver = never_approve
        lab.GATEWAY_KEY = GATEWAY_KEY  # the run's gateway key, which run_incident hands the model
        try:
            with probe.watching(loop.W3GatewayModel):
                for key, batch in groups(items):
                    todo = [i for i in batch if done_key(i) not in run.done]
                    if not todo:
                        continue
                    out = run.folder("w3", key)
                    lab.SCRATCH = out
                    table_path = lab.fresh_table_path()
                    members = lab.members_by_user(table_path)
                    state_file, snow_file = out / "cluster.json", out / "servicenow.json"
                    service_log = io.StringIO()
                    approvals = Service(out / "approvals.sqlite", lambda: MembershipTable.from_dict(
                        json.loads(table_path.read_text(encoding="utf-8"))), lab.SECRET, lab.APPROVERS, service_log)
                    http = serve_approvals(approvals, lab.SERVICE_KEY, port=free_port())
                    threading.Thread(target=http.serve_forever, daemon=True).start()
                    approval_url = f"http://127.0.0.1:{http.server_address[1]}"
                    spec = place.write_spec(out / "placement.json", "w3", todo[0]["placements"]) if todo[0]["placements"] else None
                    procs: list[subprocess.Popen] = []
                    try:
                        with placement_env(spec):
                            ports, procs = lab.start_servers(table_path, state_file, snow_file, approval_url, out)
                        for item in todo:
                            incident = incidents[item["case"]]
                            started, error = time.perf_counter(), None
                            try:
                                record = asyncio.run(lab.run_incident(incident, gateway, ports, table_path, approval_url,
                                                                      state_file, snow_file, members))
                            except BaseException as exc:  # recorded as a failed case; the run goes on
                                error = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
                                record = {"id": incident["id"], "triage": "", "proposal": None, "executed": False,
                                          "approved": False, "labels": [], "reads": [], "hidden_reads": [], "state": "error"}
                            trace_id = lab.TRACE.get("id", "")
                            requests, replies = probe.take(trace_id)
                            run.record(item, trace_id=trace_id, seconds=round(time.perf_counter() - started, 2), error=error,
                                       output=record, text=record.get("triage") or "", requests=requests, replies=replies,
                                       reached=reached(item["pieces"], requests),
                                       logs={"approvals": [json.loads(x) for x in service_log.getvalue().splitlines() if x.strip()],
                                             "servers": {p.stem: registry.read_jsonl(p) for p in out.glob("*.log")}})
                            progress(f"w3 {item['variant']} {item['case']} {record.get('state')} "
                                     f"{time.perf_counter() - started:.1f}s" + (" ERROR" if error else ""))
                    finally:
                        for proc in procs:
                            stop(proc)
                        http.shutdown()
        finally:
            lab.runner.eligible_approver, lab.GATEWAY_KEY = saved_approver, saved_key


def run_w4(run: Run, items: list[dict[str, Any]], gateway: str, progress: Callable[[str], None]) -> None:
    changes = {c["id"]: c for c in registry.read_yaml(registry.path(registry.WORKFLOWS["w4"].golden))}
    model_env = {"W4_MODEL_BASE_URL": gateway + "/v1", "W4_MODEL_NAME": "larkspur-chat", "W4_MODEL_API_KEY": GATEWAY_KEY,
                 "W4_WORKFLOW": "w4-change", "W4_MODEL_MAX_TOKENS": "1200"}
    with registry.isolated((f"{W4}/eval",)):
        import lab  # first: it puts the agents' folders on the path
        import analyst
        import risk_scorer
        import run_changes as runner
        support = lab.support
        for key, batch in groups(items):
            todo = [i for i in batch if done_key(i) not in run.done]
            if not todo:
                continue
            out = run.folder("w4", key)
            spec = place.write_spec(out / "placement.json", "w4", todo[0]["placements"]) if todo[0]["placements"] else None
            os.environ["SERVICENOW_STATE_FILE"] = str(out / "servicenow.json")
            os.environ["GITHUB_COMMENTS_FILE"] = str(out / "comments.json")
            servers = []
            log_path = out / "scribe.jsonl"
            try:
                (out / "analyst").mkdir(exist_ok=True)
                (out / "risk").mkdir(exist_ok=True)
                with placement_env(spec):
                    servers.append(support.launch(analyst, support.ANALYST_IDENTITY, "ANALYST_CALLER_TOKENS",
                                                  support.ANALYST_CALLERS, out / "analyst"))
                    servers.append(support.launch(risk_scorer, support.RISK_SCORER_IDENTITY, "RISK_SCORER_CALLER_TOKENS",
                                                  support.RISK_CALLERS, out / "risk", extra=model_env))
                a, r = servers
                for item in todo:
                    change = changes[item["case"]]
                    started, error = time.perf_counter(), None
                    with log_path.open("a", encoding="utf-8") as log:
                        try:
                            pack = asyncio.run(runner.run_change(change, identity=support.SCRIBE_IDENTITY,
                                                                 token=support.SCRIBE_TOKEN, analyst_url=a.url,
                                                                 risk_scorer_url=r.url, log=log))
                        except BaseException as exc:
                            error = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
                            pack = {"change_ref": change["change_ref"], "written": False, "evidence": None, "risk": None}
                    risk = pack.get("risk") or {}
                    evidence = pack.get("evidence") or {}
                    # What the rationale's model was sent (a2a/rationale_model.py): the class, the reasons, the change.
                    sent = [{"role": "user", "content": f"CLASS: {risk.get('risk_class')}\nREASONS: "
                             f"{'; '.join(risk.get('reasons') or []) or 'none'}\nCHANGE: {evidence.get('change_ref')} "
                             f"on {evidence.get('service')}."}]
                    logs = {"scribe": registry.read_jsonl(log_path),
                            "analyst": registry.read_jsonl(out / "analyst" / "agent.log") if (out / "analyst" / "agent.log").exists() else [],
                            "risk-scorer": registry.read_jsonl(out / "risk" / "agent.log") if (out / "risk" / "agent.log").exists() else []}
                    run.record(item, trace_id=pack.get("trace_id"), seconds=round(time.perf_counter() - started, 2),
                               error=error, output={"pack": pack}, text=risk.get("rationale") or "", requests=[sent],
                               replies=[], reached=reached(item["pieces"], [sent]), logs=logs)
                    progress(f"w4 {item['variant']} {item['case']} {risk.get('risk_class')} "
                             f"{time.perf_counter() - started:.1f}s" + (" ERROR" if error else ""))
            finally:
                for s in servers:
                    support.stop(s)


def recording_seam(ask: Callable[..., Any], asked: dict[str, list[tuple[str, str, Any]]], pace: Pace,
                   model_input: Callable[[Any], str]) -> Callable[..., Any]:
    """W5's `prose.ask_model` with a copy kept: the model's title and body as the seam got them, before its
    forbidden-word check (a reply the check refuses is replaced by the stub, and the night's record keeps only the
    refused words), by trace id. Every keyword `prose.write` passes goes through unchanged: chapter 16's step 3b
    added `traceparent`, which a fixed list of keywords here refused, so the next one can't stop a run."""

    def recorded(finding: Any, *, trace_id: str, **kwargs: Any) -> Any:
        pace.wait()
        answer = ask(finding, trace_id=trace_id, **kwargs)
        asked[trace_id].append((finding.key, model_input(finding), answer))
        return answer

    return recorded


def run_w5(run: Run, items: list[dict[str, Any]], gateway: str, gateway_log: Path, progress: Callable[[str], None]) -> None:
    nights = {n["id"]: n for n in registry.read_yaml(registry.path(registry.WORKFLOWS["w5"].golden))}
    model_env = {"W5_MODEL_BASE_URL": gateway + "/v1", "W5_MODEL_NAME": "larkspur-chat", "W5_MODEL_API_KEY": GATEWAY_KEY}
    pace = Pace("w5")
    with registry.isolated((f"{W5}/eval",)):
        import run_nights as runner  # first: it puts the harness's, the writer's, and the servers' folders on the path
        import launch
        import prose
        from common import mint_app_token
        prose.MAX_TOKENS = MAX_TOKENS
        asked: dict[str, list[tuple[str, str, Any]]] = defaultdict(list)
        ask = prose.ask_model
        saved_env = {k: os.environ.get(k) for k in model_env}
        os.environ.update(model_env)
        prose.ask_model = recording_seam(ask, asked, pace, prose.model_input)
        try:
            for key, batch in groups(items):
                todo = [i for i in batch if done_key(i) not in run.done]
                if not todo:
                    continue
                out = run.folder("w5", key)
                spec = place.write_spec(out / "placement.json", "w5", todo[0]["placements"]) if todo[0]["placements"] else None
                secret = secrets.token_hex(32)
                readers = None
                try:
                    with placement_env(spec):
                        readers = launch.start_readers(out / "readers", secret)
                    for item in todo:
                        night = dict(nights[item["case"]], workspaces=[item["workspace"]])
                        started, error = time.perf_counter(), None
                        try:
                            records, packs, ledger = runner.run_golden([night], out / "nights", servers=readers.urls,
                                                                       token=mint_app_token(secret), gateway_log=gateway_log)
                            record, night_packs = records[night["id"]], packs.get(night["id"], {})
                        except BaseException as exc:
                            error = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
                            record, night_packs, ledger = {"findings": [], "pull_requests": []}, {}, None
                        trace_id = record.get("trace_id") or ""
                        inputs = asked.pop(trace_id, [])
                        requests = [[{"role": "user", "content": text}] for _, text, _ in inputs]
                        replies = [{"key": k, "title": a[0], "body": a[1]} if a else {"key": k, "reply": None}
                                   for k, _, a in inputs]
                        events = registry.read_jsonl(Path(record["log_file"])) if record.get("log_file") else []
                        readers_lines = {name: [e for e in registry.read_jsonl(path) if e.get("trace_id") == trace_id]
                                         for name, path in readers.logs.items() if path.exists()}
                        run.record(item, trace_id=trace_id, seconds=round(time.perf_counter() - started, 2), error=error,
                                   output={"record": record, "packs": night_packs,
                                           "ledger": ledger.data if ledger is not None else None},
                                   text="", requests=requests, replies=replies, inputs=[k for k, _, _ in inputs],
                                   reached=reached(item["pieces"], requests),
                                   logs={"night": [e for e in events if e.get("trace_id") == trace_id], "readers": readers_lines})
                        counts = record.get("counts") or {}
                        progress(f"w5 {item['variant']} {item['workspace']} findings={counts.get('findings')} "
                                 f"prs={counts.get('pull_requests')} {time.perf_counter() - started:.1f}s"
                                 + (" ERROR" if error else ""))
                finally:
                    if readers is not None:
                        readers.stop()
        finally:
            prose.ask_model = ask
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


RUNNERS = {"w1": run_w1, "w2": run_w2, "w3": run_w3, "w4": run_w4}


def run_model(model: str, workflows: tuple[str, ...], ollama_port: int | None, scratch: Path | None, only: str | None,
              limit: int | None, progress: Callable[[str], None] = print) -> Path:
    scratch = (scratch or SCRATCH / f"run-{model}-{time.strftime('%Y%m%dT%H%M%S')}").resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    run = Run(model, scratch, ollama_port)
    meta_file = scratch / "run.json"
    meta = registry.read_json(meta_file) if meta_file.exists() else {
        "model": model, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "workflows": {}}
    items_all = work(workflows, only)
    for workflow in workflows:
        items = [i for i in items_all if i["workflow"] == workflow]
        if limit:
            items = items[:limit]
        if not items or all(done_key(i) in run.done for i in items):
            continue
        copy, base = prepare_config(registry.path(CONFIGS[(workflow, model)]), scratch, ollama_port, run.think)
        gateway, proc, log = start_gateway(workflow, copy, scratch)
        progress(f"{workflow}: gateway up at {gateway}, {len(items)} outputs to make")
        started = time.perf_counter()
        try:
            if workflow == "w5":
                run_w5(run, items, gateway, log, progress)
            else:
                RUNNERS[workflow](run, items, gateway, progress)
            ran = {r["trace_id"] for r in registry.read_jsonl(run.outputs) if r["workflow"] == workflow and r.get("trace_id")}
            wait_for_log(log, ran)
        finally:
            stop(proc)
        entry = meta["workflows"].setdefault(workflow, {"seconds": 0.0})
        entry.update(config={"source": CONFIGS[(workflow, model)], "sha256": registry.sha256_of(copy)},
                     model=model_record(base, model, run.think), loaded=loaded(base), num_ctx=NUM_CTX)
        entry["seconds"] = round(entry["seconds"] + time.perf_counter() - started, 1)
        meta_file.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")
    return scratch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", choices=sorted(MODEL_OF), required=True)
    parser.add_argument("--ollama-port", type=int, help="the portable Ollama 0.40.13 for Gemma 4 12B (11435)")
    parser.add_argument("--workflows", default="w1,w2,w3,w4,w5")
    parser.add_argument("--scratch", type=Path, help="resume the run whose scratch folder this is")
    parser.add_argument("--only", help="variants whose id starts with this (a smoke run)")
    parser.add_argument("--limit", type=int, help="the first N outputs of each workflow (a smoke run)")
    args = parser.parse_args(argv)
    workflows = tuple(w for w in ("w1", "w2", "w3", "w4", "w5") if w in args.workflows.split(","))
    problems = generate.check()
    if problems:
        raise SystemExit("the red-team set is not what its sources give; nothing run:\n" + "\n".join(problems))
    scratch = run_model(args.model, workflows, args.ollama_port, args.scratch, args.only, args.limit,
                        progress=lambda line: print(line, flush=True))
    print(f"outputs in {scratch / 'outputs.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
