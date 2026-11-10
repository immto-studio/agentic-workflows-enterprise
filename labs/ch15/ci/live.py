"""The live job (chapter 15, step 7, E-D9, E-D12): every golden set through chapter 5's gateway on the current alias
map, the judge on the prose, one result file, and the comparison with the accepted baseline.

It runs on the workstation, on demand and after every alias remap, because the standard GitHub-hosted runners
have no GPU. For each of the six sets it starts chapter 5's gateway with the config the workflow's own runs use
(chapter 9's for the skeleton, W1's for W1, W2's for W2 to W5), copied into the scratch folder with the context
window and Ollama's think flag the lab's runs set, and runs every case through the workflow's harness:

  skeleton  chapter 9's run_local_golden on the restricted alias, as chapter 9 ran chapter 5's set
  W1, W2    the harness's answer step against W1's knowledge server or W2's three servers (step 6's runners in
            redteam/run_redteam.py, with nothing placed)
  W3        the five servers and the approval service, as W3's eval/lab.py starts them, each incident through
            lab.run_incident; a second eligible person approves a proposed write, as in W3's golden run
  W4        the analyst and the risk scorer, each change through the scribe (step 6's runner)
  W5        the four readers and the three golden nights in order, on one fake and one ledger (run_nights)

The current alias map is what those configs say: --model gpt-oss-20b, the default, takes the workflows' own
configs, and --model gemma4-12b their Gemma copies. Each set's outputs are written into the scratch folder in the
shape the workflow's own runs keep, so step 2's layers replay them as they replay the kept runs. Then the
workflows' model is unloaded, and the judge reads every output a model wrote, as step 3's judge does: the other
local model judges (E-D4), through a gateway that serves both chat aliases from the judge's model. A verdict on a
text in the author's sample is withheld from the result, as step 6 withheld them, and no verdict is printed.

The result, live/<UTC time>-<model>.json, holds the pins (each set's version; each workflow's alias map and the
digest of every model behind it, with the Ollama that serves it; the judge's model, digest, server, and alias map;
the prompt's and rubrics' hashes), every case's verdicts check by check with the detail of each failure, the
judge's verdicts with the text each one read, and per workflow the tokens of its model and of its judge from the
gateways' logs (E-D12). The run is then compared with the baseline as the gate compares it (ci/gate.py). A changed
digest or alias map invalidates the baseline until a run is accepted; after review, --accept makes the run the
baseline.

--workflows and --limit make a smoke run, whose result stays in the scratch folder and can't be accepted. The
scratch folder (ci/_lab/live-<time>/, git-ignored) keeps every output and log, and --scratch resumes a run that
stopped: a set whose files are written isn't run again, and the judge reads only what it hasn't.

Run (from labs/ch15, PYTHONUTF8=1, the model's Ollama up and alone on the GPU):
  python ci/live.py --dry-run                         the alias map, the digests, and whether the baseline holds
  python ci/live.py                                   the sets on gpt-oss-20b (Ollama 0.22.1 on 11434), then the
                                                      judge, Gemma 4 12B (the portable Ollama 0.40.13 on 11435)
  python ci/live.py --scratch ci/_lab/live-<time>     resume, with the same options
  python ci/live.py --compare live/<run>.json         the comparison again, with no model
  python ci/live.py --accept live/<run>.json          after review: the run becomes the baseline
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata as metadata
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import measure  # noqa: E402  (puts the lab's folders on sys.path)

import httpx  # noqa: E402

import baseline as baseline_file  # noqa: E402
import convert  # noqa: E402
import deterministic  # noqa: E402
import gate  # noqa: E402
import items as itemize  # noqa: E402
import judge as judging  # noqa: E402
import registry  # noqa: E402
import run_judge  # noqa: E402
import run_redteam  # noqa: E402
import run_replay  # noqa: E402
import trajectory  # noqa: E402

W1, W2, W3, W5 = registry.W1, registry.W2, registry.W3, registry.W5
SCRATCH = Path(os.environ.get("CH15_LIVE_SCRATCH", HERE / "_lab"))
GATEWAY_KEY = run_redteam.GATEWAY_KEY  # the key step 6's runners send; the proxy's master key here, a local value
MODELS = ("gpt-oss-20b", "gemma4-12b")  # the two local models; each judges the other (E-D4)
SKELETON_ALIAS = "larkspur-chat-restricted"  # chapter 9 ran chapter 5's set on the self-hosted alias
LABEL = "live"  # the run's label where step 2's code names a kept run's
CONFIGS = {("skeleton", "gpt-oss-20b"): "labs/ch09/gateway/litellm.config.yaml",
           ("skeleton", "gemma4-12b"): "labs/ch09/gateway/litellm.gemma.yaml", **run_redteam.CONFIGS}
HOOKS = {"skeleton": "labs/ch09/gateway", **run_redteam.HOOKS}
MANIFESTS = {"skeleton": "labs/ch05/manifest", **run_redteam.MANIFESTS}
JUDGE_CONFIGS = {"gpt-oss-20b": f"{W2}/gateway/litellm.config.yaml", "gemma4-12b": f"{W2}/gateway/litellm.gemma.yaml"}
MAIN_FILE = {"skeleton": "golden-{model}.json", "w1": "answers-{model}.json", "w2": "answers-{model}.json",
             "w3": "runs-{model}.json", "w4": "packs-{model}.json", "w5": "packs-{model}.json"}
SERVED_FROM = {"digest_from": "Ollama's /api/tags when the set ran", "server_from": "Ollama's /api/version when the set ran"}
QUIET_S = 2.0  # how long the gateway's log must stay still before a set's gateway is stopped
# Gemma 4 12B loads only on the portable Ollama 0.40.13, which the lab runs on 11435 beside the 0.22.1 on 11434.
OLLAMA_PORTS = {"gemma4-12b": 11435}

Gateway = tuple[str, Path, Callable[[], None]]  # the gateway's URL, its log, and how to stop it
Progress = Callable[[str], None]


@dataclass(frozen=True)
class Plan:
    model: str  # which configs: the workflows' own (gpt-oss-20b) or their Gemma copies (gemma4-12b)
    judge: str
    ollama_port: int | None = None  # the workflows' model's Ollama, when not the configs' 11434
    judge_ollama_port: int | None = None
    workflows: tuple[str, ...] = measure.WORKFLOWS
    limit: int | None = None  # the first N cases of each set (W5: nights): a smoke run

    @property
    def complete(self) -> bool:
        return self.workflows == measure.WORKFLOWS and not self.limit


def slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in ".-" else "-" for c in text)


def chat_model(config: Path) -> str:
    """The lab's name for the model a config serves the chat alias from (the skeleton's: the restricted alias)."""
    aliases = run_judge.alias_map(config)
    return slug(measure.model_tag(aliases.get("larkspur-chat") or aliases[SKELETON_ALIAS]))


def chat_models(plan: Plan) -> dict[str, str]:
    """Per set, the model its config serves: after a remap of the configs themselves, the model the run is of."""
    return {w: chat_model(registry.path(CONFIGS[(w, plan.model)])) for w in plan.workflows}


# --- the gateway and the models behind it -------------------------------------------------------------------------

def start_gateway(name: str, config: Path, manifests: Path, hooks: Path, out: Path) -> Gateway:
    """Chapter 5's proxy on a free port of 127.0.0.1, started from the hooks' folder with the manifests the
    workflow's own runs give it; its log, its spans, and its output stay in `out`."""
    port = run_redteam.free_port()
    log = out / f"gateway-{name}.jsonl"
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "LITELLM_MASTER_KEY": GATEWAY_KEY,
           "MANIFEST_DIR": str(manifests), "GATEWAY_LOG_FILE": str(log), "GATEWAY_CONFIG": str(config.resolve()),
           "TRACE_FILE": str(out / f"traces-{name}.jsonl")}
    for variable in ("OTEL_EXPORTER_OTLP_ENDPOINT", run_redteam.place.ENV):
        env.pop(variable, None)
    hook = str(run_redteam.place.HOOK)
    env["PYTHONPATH"] = os.pathsep.join(p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and p != hook)
    beside = Path(sys.executable).parent / ("litellm.exe" if os.name == "nt" else "litellm")
    exe = os.environ.get("CH15_LITELLM") or (str(beside) if beside.exists() else "litellm")
    stderr = (out / f"gateway-{name}.stderr").open("a", encoding="utf-8")
    proc = subprocess.Popen([exe, "--config", str(config), "--host", "127.0.0.1", "--port", str(port)], env=env,
                            stdout=stderr, stderr=subprocess.STDOUT, text=True, cwd=str(hooks))
    if not run_redteam.wait_port(port, proc=proc):
        run_redteam.stop(proc)
        stderr.close()
        raise RuntimeError(f"the gateway did not come up; see {out / f'gateway-{name}.stderr'}")

    def stop() -> None:
        run_redteam.stop(proc)
        stderr.close()

    return f"http://127.0.0.1:{port}", log, stop


def _ollama(base: str, path: str) -> Any:
    return httpx.get(base.rstrip("/") + path, timeout=10.0).json()


def served_models(config: Path) -> dict[str, dict[str, Any]]:
    """Each model the config serves, with its digest and the version of the Ollama that serves it, read from that
    Ollama now (each Ollama reports its own digest for a tag, so the server is part of the pin)."""
    out: dict[str, dict[str, Any]] = {}
    for deployment in registry.read_yaml(config)["model_list"]:
        params = deployment["litellm_params"]
        served = params["model"]
        if served in out:
            continue
        record: dict[str, Any] = {"digest": None, "server": None, **SERVED_FROM}
        try:
            record["server"] = _ollama(params["api_base"], "/api/version").get("version")
            tags = {t["name"]: t for t in _ollama(params["api_base"], "/api/tags").get("models") or []}
            record["digest"] = (tags.get(served.split("/", 1)[-1]) or {}).get("digest")
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            record["server_from"] = f"unreachable when the set ran ({type(exc).__name__})"
        out[served] = record
    return out


def unload(config: Path, progress: Progress) -> None:
    """Every model the config serves, unloaded from its Ollama (keep_alive 0, as `ollama stop` does), so the GPU is
    free for the judge's model."""
    for deployment in registry.read_yaml(config)["model_list"]:
        params = deployment["litellm_params"]
        name = params["model"].split("/", 1)[-1]
        try:
            httpx.post(params["api_base"].rstrip("/") + "/api/generate", json={"model": name, "keep_alive": 0},
                       timeout=30.0)
        except (httpx.HTTPError, KeyError) as exc:
            progress(f"could not unload {name}: {type(exc).__name__}")


def settle(log: Path, quiet_s: float | None = None, deadline_s: float = 30.0) -> None:
    """Wait until the gateway's log stops growing: the hooks write a call's line after the reply has gone back,
    and a proxy stopped right after the last reply loses that line (step 3's first smoke run did)."""
    quiet_s = QUIET_S if quiet_s is None else quiet_s
    end, last, still = time.time() + deadline_s, -1, time.time()
    while time.time() < end:
        size = log.stat().st_size if log.exists() else 0
        if size != last:
            last, still = size, time.time()
        elif time.time() - still >= quiet_s:
            return
        time.sleep(0.25)


def prepare(workflow: str, plan: Plan, folder: Path) -> tuple[Path, dict[str, Any]]:
    """The workflow's config copied into its folder for this run, and what it serves: the source and the copy's
    hash, the alias map, and every model behind it with its digest and server."""
    folder.mkdir(parents=True, exist_ok=True)
    source = CONFIGS[(workflow, plan.model)]
    think = run_redteam.THINK.get(chat_model(registry.path(source)))  # Gemma 4 12B with thinking off, as its runs had it
    copy, _ = run_redteam.prepare_config(registry.path(source), folder, plan.ollama_port, think)
    return copy, {"config": {"source": source, "sha256": registry.sha256_of(copy)},
                  "aliases": run_judge.alias_map(copy), "models": served_models(copy)}


def prepare_judge(plan: Plan, folder: Path) -> tuple[Path, dict[str, Any]]:
    """The judge's config, as step 3 starts it (judge/run_judge.py): both chat aliases on the judge's model."""
    folder.mkdir(parents=True, exist_ok=True)
    source = JUDGE_CONFIGS[plan.judge]
    think = run_judge.THINK.get(plan.judge)
    copy, base = run_judge.prepare_config(registry.path(source), folder, plan.judge_ollama_port,
                                          max(run_judge.MIN_NUM_CTX, judging.MAX_TOKENS + 4096), think)
    aliases = run_judge.alias_map(copy)
    if aliases.get(judging.ALIAS) != aliases.get(judging.RESTRICTED_ALIAS):
        raise SystemExit(f"{source}: the judge's config serves its two chat aliases from different models")
    record = served_models(copy)[aliases[judging.ALIAS]]
    return copy, {"model": plan.judge, "served": aliases[judging.ALIAS], "digest": record["digest"],
                  "server": record["server"], "aliases": aliases,
                  "config": {"source": source, "sha256": registry.sha256_of(copy)}}


# --- the sets -----------------------------------------------------------------------------------------------------

@contextmanager
def paced(cls: Any, pace: Any) -> Iterator[None]:
    """Each call of the harness's model class waits for the pace first: the gateway refuses a call over the
    manifest's requests_per_minute (step 6's runners pace their own the same way)."""
    call = cls.__call__

    def waiting(self: Any, messages: Any) -> Any:
        pace.wait()
        return call(self, messages)

    cls.__call__ = waiting
    try:
        yield
    finally:
        cls.__call__ = call


def golden_items(workflow: str, limit: int | None) -> list[dict[str, Any]]:
    """Every case of the set, as step 6's runners take a case, with nothing placed in the fakes."""
    ids = [c["id"] for c in registry.read_jsonl(registry.CASES / f"{workflow}.jsonl")]
    return [{"workflow": workflow, "variant": "golden", "family": "golden", "parent": None,
             "technique": "the fakes as they are", "case": cid, "placements": [], "workspace": None, "pieces": []}
            for cid in ids[:limit] if cid]


def _jsonl_append(path: Path, line: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as out:
        out.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


def _lines(path: Path) -> list[dict[str, Any]]:
    return registry.read_jsonl(path) if path.exists() else []


def _in_order(workflow: str, rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    order = {c["id"]: n for n, c in enumerate(registry.read_jsonl(registry.CASES / f"{workflow}.jsonl"))}
    return sorted(rows, key=lambda r: order.get(key(r), len(order)))


def run_skeleton(plan: Plan, folder: Path, url: str, served: dict[str, Any], tag: str, progress: Progress) -> None:
    path = folder / "results.jsonl"
    done = {r["id"] for r in _lines(path)}
    with registry.isolated(("labs/ch09",)):
        import run_local_golden as rl
        saved = os.environ.get("LITELLM_MASTER_KEY")
        os.environ["LITELLM_MASTER_KEY"] = GATEWAY_KEY  # chapter 5's GatewayModel sends the key it finds there
        try:
            cases = {c["id"]: c for c in rl.run_golden.load_cases()}
            specs = rl.advertised_tools()
            with paced(rl.GatewayModel, run_redteam.Pace("skeleton")):
                for item in golden_items("skeleton", plan.limit):
                    if item["case"] in done:
                        continue
                    case, started = cases[item["case"]], time.perf_counter()
                    try:
                        result = asyncio.run(rl.run_case(case, url, SKELETON_ALIAS, specs))
                        entry = asdict(result) | {"tool_ok": result.tool_ok, "facts_ok": result.facts_ok,
                                                  "typographic": result.typographic}
                    except Exception as exc:  # recorded as a failed case; the run goes on
                        facts = rl.key_facts(case)
                        entry = {"id": case["id"], "question": case["question"], "answer": "",
                                 "expected_calls": rl.run_golden.expected_calls(case), "calls": [], "facts": facts,
                                 "missing_facts": facts, "seconds": round(time.perf_counter() - started, 2),
                                 "model_calls": [], "tool_ok": False, "facts_ok": not facts, "typographic": False,
                                 "error": f"{type(exc).__name__}: {exc}"[:500]}
                    _jsonl_append(path, entry)
                    progress(f"skeleton {case['id']} {time.perf_counter() - started:.1f}s" + (" ERROR" if "error" in entry else ""))
            results = _in_order("skeleton", _lines(path), lambda r: r["id"])
            names = [f.name for f in fields(rl.LocalResult)]
            summary = rl.summarize([rl.LocalResult(**{n: r[n] for n in names}) for r in results])
        finally:
            if saved is None:
                os.environ.pop("LITELLM_MASTER_KEY", None)
            else:
                os.environ["LITELLM_MASTER_KEY"] = saved
    measure.write_json(folder / "kept" / MAIN_FILE["skeleton"].format(model=tag), {"summary": summary, "results": results})


def _answers(workflow: str, folder: Path, served: dict[str, Any], tag: str) -> None:
    """W1's or W2's outputs as its own runner keeps them (eval/answer_eval.py): each case with the scorer's verdict,
    and the gateway's map in meta, by which step 3 says whose an output is."""
    lines = {r["case"]: r for r in _lines(folder / "outputs.jsonl")}
    golden = {q["id"]: q for q in registry.read_yaml(registry.path(registry.WORKFLOWS[workflow].golden))}
    results = []
    with registry.loaded(workflow) as mods:
        ctx = deterministic.context(workflow, mods)
        for case_id in [i["case"] for i in golden_items(workflow, None) if i["case"] in lines]:
            line = lines[case_id]
            o = line["output"]
            q = golden[o["id"]]
            labels = [(c["data_class"], c["alias"]) for c in o["calls"]]
            if workflow == "w1":
                case = {"question": q, "persona": o["persona"], "denied": q["trap"] == "access" and o["persona"] == "oncall.engineer"}
                verdict = mods.answer_eval.score(case, o["answer"], labels, ctx["pages"])
            else:
                verdict = mods.answer_eval.score(q, o["answer"], labels, o.get("read_events", []), ctx["hidden_for"][o["persona"]])
            if line.get("error"):
                verdict.update(passed=False, error=line["error"])
            results.append({"id": o["id"], "trap": o["trap"], "persona": o["persona"], "seconds": line.get("seconds"),
                            "answer": o["answer"], "typography": o["typography"], "calls": o["calls"],
                            "model_calls": o["model_calls"], **({"read_events": o["read_events"]} if workflow == "w2" else {}),
                            **verdict})
        summary = mods.answer_eval.summarize(results)
    chat = served["models"].get(served["aliases"].get("larkspur-chat"), {})
    meta = {"measured": date.today().isoformat(), "ollama": chat.get("server"), "gateway_models": served["aliases"]}
    measure.write_json(folder / "kept" / MAIN_FILE[workflow].format(model=tag), {"meta": meta, "summary": summary, "results": results})


def run_w1(plan: Plan, folder: Path, url: str, served: dict[str, Any], tag: str, progress: Progress) -> None:
    run_redteam.run_w1(run_redteam.Run(tag, folder, plan.ollama_port), golden_items("w1", plan.limit), url, progress)
    _answers("w1", folder, served, tag)


def run_w2(plan: Plan, folder: Path, url: str, served: dict[str, Any], tag: str, progress: Progress) -> None:
    run_redteam.run_w2(run_redteam.Run(tag, folder, plan.ollama_port), golden_items("w2", plan.limit), url, progress)
    _answers("w2", folder, served, tag)


def run_w3(plan: Plan, folder: Path, url: str, served: dict[str, Any], tag: str, progress: Progress) -> None:
    """W3's golden run as eval/lab.py makes it: the five servers and the approval service, every incident through
    run_incident, a second eligible person approving a proposed write; each record kept as it is made."""
    path = folder / "records.jsonl"
    done = {r["id"] for r in _lines(path)}
    incidents = {c["id"]: c for c in registry.read_yaml(registry.path(registry.WORKFLOWS["w3"].golden))}
    todo = [i for i in golden_items("w3", plan.limit) if i["case"] not in done]
    with registry.isolated((f"{W3}/eval",)):
        import lab
        import loop
        import score as scoring
        from access import MembershipTable
        from approval_service import Service, serve as serve_approvals
        saved = lab.GATEWAY_KEY
        lab.GATEWAY_KEY = GATEWAY_KEY  # run_incident hands the module's key to the model
        try:
            if todo:
                out = folder / f"servers-{len(done)}"
                out.mkdir(parents=True, exist_ok=True)
                # A fresh membership table, as lab.fresh_table_path writes one; that function imports W2's test
                # conftest by its bare name, which inside a pytest session is the lab's own.
                table_path = run_redteam.fresh_membership(out / "table.json")
                members = lab.members_by_user(table_path)
                state_file, snow_file = out / "cluster.json", out / "servicenow.json"
                approvals = Service(out / "approvals.sqlite", lambda: MembershipTable.from_dict(
                    json.loads(table_path.read_text(encoding="utf-8"))), lab.SECRET, lab.APPROVERS, io.StringIO())
                http = serve_approvals(approvals, lab.SERVICE_KEY, port=run_redteam.free_port())
                threading.Thread(target=http.serve_forever, daemon=True).start()
                approval_url = f"http://127.0.0.1:{http.server_address[1]}"
                procs: list[subprocess.Popen] = []
                try:
                    ports, procs = lab.start_servers(table_path, state_file, snow_file, approval_url, out)
                    with paced(loop.W3GatewayModel, run_redteam.Pace("w3")):
                        for item in todo:
                            incident, started = incidents[item["case"]], time.perf_counter()
                            try:
                                record = asyncio.run(lab.run_incident(incident, url, ports, table_path, approval_url,
                                                                      state_file, snow_file, members))
                            except BaseException as exc:  # recorded as a failed case, as eval/lab.py records one
                                detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
                                record = {"id": incident["id"], "triage": "", "proposal": None, "executed": False,
                                          "approved": False, "labels": [], "reads": [], "hidden_reads": [],
                                          "state": "error", "error": detail}
                            record["seconds"] = round(time.perf_counter() - started, 1)
                            record["trace_id"] = lab.TRACE.get("id", "")
                            _jsonl_append(path, record)
                            progress(f"w3 {incident['id']} {record.get('state')} {record['seconds']:.1f}s")
                finally:
                    for proc in procs:
                        run_redteam.stop(proc)
                    http.shutdown()
            records = _in_order("w3", _lines(path), lambda r: r["id"])
            summary = scoring.summarize([scoring.score(incidents[r["id"]], r) for r in records])
        finally:
            lab.GATEWAY_KEY = saved
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    measure.write_json(folder / "kept" / MAIN_FILE["w3"].format(model=tag),
                       {"model": tag, "run_at": stamp, "summary": summary, "records": records})


def run_w4(plan: Plan, folder: Path, url: str, served: dict[str, Any], tag: str, progress: Progress) -> None:
    run_redteam.run_w4(run_redteam.Run(tag, folder, plan.ollama_port), golden_items("w4", plan.limit), url, progress)
    lines = {r["case"]: r for r in _lines(folder / "outputs.jsonl")}
    batch = folder / "w4" / run_redteam.slug("golden")
    changes = {c["id"]: c for c in registry.read_yaml(registry.path(registry.WORKFLOWS["w4"].golden))}
    packs = {cid: lines[cid]["output"]["pack"] | {"seconds": lines[cid].get("seconds")}
             for cid in changes if cid in lines}
    with registry.isolated((f"{registry.W4}/eval",)):
        import run_changes as runner
        import score as scoring
        wanted = [changes[c] for c in packs]
        results = runner.score_all(wanted, packs)
        summary = scoring.summarize(results) | {"model": tag, "measured": date.today().isoformat()}
    kept = folder / "kept"
    measure.write_json(kept / MAIN_FILE["w4"].format(model=tag), packs)
    measure.write_json(kept / f"results-{tag}.json", results)
    measure.write_json(kept / f"summary-{tag}.json", summary)
    logs = kept / f"logs-{tag}"
    logs.mkdir(parents=True, exist_ok=True)
    for source, name in ((batch / "scribe.jsonl", "scribe.jsonl"), (batch / "analyst" / "agent.log", "analyst.jsonl"),
                         (batch / "risk" / "agent.log", "risk-scorer.jsonl")):
        if source.exists():
            (logs / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")


def run_w5(plan: Plan, folder: Path, url: str, served: dict[str, Any], tag: str, progress: Progress,
           gateway_log: Path | None = None) -> None:
    """W5's golden run as eval/lab.py makes it: the four readers, the three nights in order on one fake and one
    ledger, the prose seam on the gateway; the files written as W5 keeps a run (run_nights.write_run). The nights
    depend on each other, so a stopped W5 runs again from its first night, in a folder of its own."""
    nights = registry.read_yaml(registry.path(registry.WORKFLOWS["w5"].golden))[:plan.limit or None]
    attempt = folder / f"attempt-{len([p for p in folder.glob('attempt-*')]) + 1}"
    model_env = {"W5_MODEL_BASE_URL": url + "/v1", "W5_MODEL_NAME": "larkspur-chat", "W5_MODEL_API_KEY": GATEWAY_KEY}
    pace = run_redteam.Pace("w5")
    with registry.isolated((f"{W5}/eval",)):
        import run_nights as runner  # first: it puts the harness's, the writer's, and the servers' folders on the path
        import launch
        import prose
        import score as scoring
        from common import mint_app_token
        saved_env = {k: os.environ.get(k) for k in model_env}
        saved_tokens, ask = prose.MAX_TOKENS, prose.ask_model

        def paced(finding: Any, **keywords: Any) -> Any:
            # The gateway holds W5 to its manifest's rate. The keywords pass through as the seam gives them, the
            # night's traceparent among them since chapter 16's step 3b.
            pace.wait()
            return ask(finding, **keywords)

        os.environ.update(model_env)
        prose.MAX_TOKENS, prose.ask_model = run_redteam.MAX_TOKENS, paced
        readers = None
        try:
            secret = secrets.token_hex(32)
            readers = launch.start_readers(attempt / "readers", secret)
            records, packs, ledger = runner.run_golden(nights, attempt / "nights", servers=readers.urls,
                                                       token=mint_app_token(secret), gateway_log=gateway_log,
                                                       progress=lambda line: progress(f"w5 {line}"))
            results = runner.score_all(nights, records, packs, ledger, "model")
            summary = scoring.summarize(results, model=tag, versions={"max_tokens": run_redteam.MAX_TOKENS},
                                        measured=date.today().isoformat())
            logs = {Path(r["log_file"]).name: Path(r["log_file"]) for r in records.values() if r.get("log_file")}
            logs.update({f"{name}-reader.jsonl": path for name, path in readers.logs.items()})
            if gateway_log is not None:
                logs["gateway.jsonl"] = gateway_log
            runner.write_run(folder / "kept", tag, records, packs, results, summary, ledger_path=ledger.path, logs=logs)
        finally:
            if readers is not None:
                readers.stop()
            prose.MAX_TOKENS, prose.ask_model = saved_tokens, ask
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


RUNNERS: dict[str, Callable[..., None]] = {"skeleton": run_skeleton, "w1": run_w1, "w2": run_w2, "w3": run_w3,
                                           "w4": run_w4, "w5": run_w5}


def run_set(workflow: str, plan: Plan, scratch: Path, start: Callable[..., Gateway], progress: Progress) -> None:
    """One set through its gateway, its files written in the shape its workflow keeps them; done once its
    served.json is written."""
    folder = scratch / workflow
    if (folder / "served.json").exists():
        return
    copy, served = prepare(workflow, plan, folder)
    down = sorted(s for s, m in served["models"].items() if m["server"] is None)
    if down:
        raise SystemExit(f"{workflow}: no Ollama answers for {', '.join(down)} at the config's api_base; start it "
                         f"and resume with --scratch {scratch}")
    tag = chat_model(copy)
    url, log, stop = start(workflow, copy, registry.path(MANIFESTS[workflow]), registry.path(HOOKS[workflow]), folder)
    progress(f"{workflow}: gateway up at {url}")
    started = time.perf_counter()
    try:
        if workflow == "w5":
            run_w5(plan, folder, url, served, tag, progress, gateway_log=log)
        else:
            RUNNERS[workflow](plan, folder, url, served, tag, progress)
        settle(log)
    finally:
        stop()
    base = registry.read_yaml(copy)["model_list"][0]["litellm_params"].get("api_base", "")
    served |= {"tag": tag, "log": log.name, "seconds": round(time.perf_counter() - started, 1),
               "loaded": run_judge.loaded(base) if base else []}
    measure.write_json(folder / "served.json", served)


def kept_run(workflow: str, scratch: Path) -> registry.Run:
    """The set's files as a kept run, which step 2's code reads like any other."""
    folder = scratch / workflow
    tag = registry.read_json(folder / "served.json")["tag"]
    kept = folder / "kept"
    main = kept / MAIN_FILE[workflow].format(model=tag)
    files = [main]
    if workflow in ("w4", "w5"):
        files += [p for p in (kept / f"results-{tag}.json", kept / f"summary-{tag}.json") if p.exists()]
        for sub in (f"logs-{tag}", f"nights-{tag}"):
            if (kept / sub).is_dir():
                files += sorted((kept / sub).iterdir())
    return registry.Run(workflow, tag, LABEL, kept.resolve().as_posix(), main.resolve().as_posix(),
                        tuple(p.resolve().as_posix() for p in files))


# --- the layers and the judge -------------------------------------------------------------------------------------

def replay(workflow: str, scratch: Path) -> tuple[registry.Run, list[dict[str, Any]], list[itemize.Item]]:
    """Step 2's layers over the set's outputs, and for W1 to W5 what the judge reads, as step 3 builds it."""
    run = kept_run(workflow, scratch)
    cases = {c["id"]: c for c in registry.read_jsonl(registry.CASES / f"{workflow}.jsonl")}
    aliases = registry.read_json(scratch / workflow / "served.json")["aliases"]
    found: list[itemize.Item] = []
    with registry.loaded(workflow) as mods:
        ctx = deterministic.context(workflow, mods) | trajectory.context(workflow, mods)
        rows = run_replay.replay_run(workflow, mods, ctx, cases, run)["cases"]
        if workflow in measure.JUDGED:
            outputs = registry.outputs(run)
            tag = registry.manifest(workflow)["workflow"]
            extra = {"w4_stub": itemize._w4_stub()} if workflow == "w4" else {}
            for row in rows:
                case, output = cases[row["id"]], outputs[row["id"]]
                base = {"workflow": workflow, "model": run.model, "author": author(output, aliases, run.model),
                        "run": LABEL, "case": row["id"], "part": "", "data_class": case["data_class"], "tag": tag}
                found += itemize._items_for_case(workflow, mods, ctx, case, output, row, base, extra)
    return run, rows, found


def author(output: Any, aliases: dict[str, str], default: str) -> str:
    """Who wrote the output: the model behind the alias of the call that wrote it, where the output records its
    calls (W1, W2), and the set's model elsewhere, as step 3 decides it (items._author)."""
    calls = output.get("calls") if isinstance(output, dict) else None
    if not calls or calls[-1].get("alias") not in aliases:
        return default
    return slug(measure.model_tag(aliases[calls[-1]["alias"]]))


def key_of(item: itemize.Item) -> str:
    return json.dumps(list(item.key))


def judge_all(plan: Plan, scratch: Path, todo: list[itemize.Item], start: Callable[..., Gateway],
              progress: Progress) -> dict[str, Any]:
    """The judge over the outputs it hasn't read yet, each judgement appended as it is made; the judge's pins."""
    folder = scratch / "judge"
    copy, pins = prepare_judge(plan, folder)
    if pins["server"] is None:
        raise SystemExit(f"no Ollama answers for the judge, {pins['served']}; start it (the portable Ollama 0.40.13 "
                         f"serves Gemma 4 12B on 11435) and resume with --scratch {scratch}")
    run_file = folder / "run.json"
    if run_file.exists() and registry.read_json(run_file) != pins:
        raise SystemExit(f"{run_file}: the judge's model or config changed since this run began; start a new run")
    measure.write_json(run_file, pins)
    judged_file = scratch / "judged.jsonl"
    done = {json.dumps(r["key"]) for r in _lines(judged_file)}
    left = [i for i in todo if key_of(i) not in done]
    progress(f"the judge: {len(todo)} outputs to read, {len(left)} left")
    if not left:
        return pins
    prompt = judging.load_prompt()
    rubrics = {w: judging.load_rubric(w) for w in measure.JUDGED}
    url, log, stop = start("judge", copy, run_judge.prepare_manifests(folder), registry.path(f"{W2}/gateway"), folder)
    pace = run_judge.Pace()
    try:
        with httpx.Client(timeout=judging.TIMEOUT_S) as client:
            for n, item in enumerate(left, 1):
                messages = judging.render(prompt, rubrics[item.workflow], item.conditions, item.reference, item.output)
                pace.wait(item.tag)
                result = judging.judge(client, url + "/v1", GATEWAY_KEY, messages, item.tag, item.data_class)
                _jsonl_append(judged_file, {"key": list(item.key), "judge": plan.judge, **result})
                # No verdict on the console: a live output can repeat a sampled text, which the author labels blind.
                shown = "judged" if result["verdict"] else "unparsable" if result["unparsable"] else f"error: {result['error']}"
                progress(f"[{n}/{len(left)}] {item.workflow} {item.case} {item.part}: {shown}")
        settle(log)
    finally:
        stop()
    return pins


# --- the run ------------------------------------------------------------------------------------------------------

def new_id(plan: Plan) -> str:
    """The run's id: its UTC start and the model the chat alias serves (W2's config, or the first set's)."""
    served = chat_models(plan)
    return f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')}-{served.get('w2') or next(iter(served.values()))}"


def run(plan: Plan, scratch: Path, start: Callable[..., Gateway] = start_gateway, out: Path = gate.LIVE,
        progress: Progress = print) -> Path:
    """The live job, resumable from its scratch folder: the sets, the judge, and the result file. Returns the
    result's path: live/<id>.json for a complete run, the scratch folder's result.json for a smoke run."""
    own = sorted(w for w, served in chat_models(plan).items() if served == plan.judge)
    if plan.judge == plan.model or own:
        raise SystemExit(f"{plan.judge} would judge its own outputs ({', '.join(own) or 'every set'}); the other local "
                         "model judges (E-D4)")
    scratch.mkdir(parents=True, exist_ok=True)
    meta_file = scratch / "run.json"
    wanted = {"model": plan.model, "judge": plan.judge, "workflows": list(plan.workflows), "limit": plan.limit,
              "ollama_port": plan.ollama_port, "judge_ollama_port": plan.judge_ollama_port}
    meta = registry.read_json(meta_file) if meta_file.exists() else {
        "id": new_id(plan), "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), **wanted}
    if any(meta.get(k) != v for k, v in wanted.items()):
        raise SystemExit(f"{scratch.name} was started with other options; resume it with the same ones: "
                         + json.dumps({k: meta.get(k) for k in wanted}))
    measure.write_json(meta_file, meta)
    problems = convert.check()
    if problems:
        raise SystemExit("the conversion check failed; nothing run:\n" + "\n".join(problems))
    for workflow in plan.workflows:
        run_set(workflow, plan, scratch, start, progress)
    for workflow in plan.workflows:  # free the GPU for the judge's model
        unload(next((scratch / workflow).glob("litellm*.yaml")), progress)
    replayed = {w: replay(w, scratch) for w in plan.workflows}
    todo = [i for w in plan.workflows for i in replayed[w][2] if i.judged and i.author != plan.judge]
    judge_pins = judge_all(plan, scratch, todo, start, progress)
    result = assemble(plan, meta, scratch, replayed, judge_pins)
    if plan.complete:
        path = out / f"{meta['id']}.json"
    else:
        path = scratch / "result.json"
    measure.write_json(path, result)
    return path


def assemble(plan: Plan, meta: dict[str, Any], scratch: Path, replayed: dict[str, Any],
             judge_pins: dict[str, Any]) -> dict[str, Any]:
    """The result: the run, the pins, and per set every case's verdicts, the judge's, and the tokens."""
    import report  # step 6's withholding: a text's hash as it compares texts, and the sample's texts

    sampled = report.sampled_texts()
    rubrics = {w: judging.load_rubric(w) for w in measure.JUDGED}
    judged = {json.dumps(r["key"]): r for r in _lines(scratch / "judged.jsonl")}
    judge_log = scratch / "judge" / "gateway-judge.jsonl"
    judge_calls = {line["trace_id"]: line for line in _lines(judge_log) if line.get("event") == "call"}
    now = measure.current_pins()
    pins: dict[str, Any] = {"prompt": now["prompt"], "judge": judge_pins, "workflows": {}}
    workflows: dict[str, Any] = {}
    complete = plan.complete
    for workflow in plan.workflows:
        served = registry.read_json(scratch / workflow / "served.json")
        run_, rows, found = replayed[workflow]
        cases = measure.case_verdicts(workflow, rows)
        pins["workflows"][workflow] = {"set": now["sets"][workflow],
                                       "rubric": now["rubrics"].get(workflow), "aliases": served["aliases"],
                                       "aliases_from": "the run's config copy", "config": served["config"],
                                       "models": served["models"]}
        if len(cases) != now["sets"][workflow]["cases"]:
            complete = False
        lines = _lines(scratch / workflow / served["log"])
        tag = registry.manifest(workflow)["workflow"]
        entry: dict[str, Any] = {"run": LABEL, "model": run_.model, "cases": cases,
                                 "tally": measure.tally(workflow, cases), "failing": measure.failing_details(rows),
                                 "tokens": {"workflow": measure.chat_tokens(lines, tag) | {"from": "the gateway's log"}},
                                 "seconds": served["seconds"], "loaded": served.get("loaded")}
        if workflow == "w1":
            entry["tokens"]["embedding"] = measure.embed_tokens(lines)
        if workflow in measure.JUDGED:
            rows_out, not_judged = [], {}
            for item in found:
                if not item.judged or item.author == plan.judge:
                    why = item.writer if not item.judged else f"written by {item.author}, the judge"
                    not_judged[why] = not_judged.get(why, 0) + 1
                    continue
                line = judged.get(key_of(item))
                if line is None:
                    complete = False
                    continue
                call = judge_calls.get(line["trace_id"])
                text = report.text_sha256(item.output)
                withheld = text in sampled
                rows_out.append({
                    "case": item.case, "part": item.part, "author": item.author, "data_class": item.data_class,
                    "criteria": [c["id"] for c in judging.criteria_for(rubrics[workflow], item.conditions)],
                    "trace_id": line["trace_id"], "messages_sha256": line["messages_sha256"], "text_sha256": text,
                    "verdict": None if withheld else line["verdict"], "reason": None if withheld else line["reason"],
                    "withheld": measure.WITHHELD if withheld else None, "unparsable": line["unparsable"],
                    "error": line["error"], "rules": item.rules,
                    "tokens": {"prompt": call.get("prompt_tokens"), "completion": call.get("completion_tokens")} if call else None,
                    "output": item.output})
            entry["judge"] = measure.judge_tally(rows_out) | {"not_judged": dict(sorted(not_judged.items()))}
            entry["judged"] = rows_out
            entry["tokens"]["judge"] = measure.chat_tokens([judge_calls[r["trace_id"]] for r in rows_out
                                                            if r["trace_id"] in judge_calls])
        workflows[workflow] = entry
    why = [] if plan.complete else [f"workflows {', '.join(plan.workflows)}" + (f", the first {plan.limit} cases" if plan.limit else "")]
    served = chat_models(plan)
    run_info = {"id": meta["id"], "started": meta["started"],
                "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "model": served.get("w2") or next(iter(served.values())), "configs": plan.model,
                "judge": plan.judge, "complete": complete, "why_partial": "; ".join(why) or None,
                "workflows": list(plan.workflows), "limit": plan.limit,
                "versions": {"python": sys.version.split()[0], **{p: _version(p) for p in ("litellm", "mcp", "httpx")}}}
    return {"kind": "live", "schema": measure.SCHEMA, "run": run_info, "pins": pins, "workflows": workflows}


def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


# --- the commands -------------------------------------------------------------------------------------------------

def compare(path: Path, baseline: Path = gate.BASELINE, thresholds: Path = gate.THRESHOLDS) -> tuple[bool, str]:
    loaded, problems = gate.load_thresholds(thresholds)
    if problems:
        return False, "\n".join(problems) + "\n"
    report = gate.compare(registry.read_json(baseline), registry.read_json(path), loaded)
    return report["passed"], gate.render(report, baseline.name, path.name)


def accept(path: Path, baseline: Path = gate.BASELINE, today: str | None = None) -> str:
    """The run becomes the baseline, after review: refused for a smoke run and for a run made on sets, a prompt, or
    rubrics the repository no longer holds."""
    result = registry.read_json(path)
    if not result["run"].get("complete"):
        raise SystemExit(f"{path.name} is a partial run ({result['run'].get('why_partial')}); only a complete run is accepted")
    stale = gate.stale(result)
    if stale:
        raise SystemExit(f"{path.name} is stale, so it can't be accepted: " + "; ".join(stale))
    measure.write_json(baseline, baseline_file.from_live(result, path, today or date.today().isoformat()))
    return f"{baseline.name} now holds {path.name}; commit the two together, with the review."


def _served(model: dict[str, Any]) -> str:
    if model.get("server") is None:
        return "unreachable: no Ollama answers at the config's api_base"
    return f"{measure.short(model.get('digest'))} on Ollama {model['server']}"


def dry_run(plan: Plan, baseline: Path = gate.BASELINE, progress: Progress = print) -> dict[str, Any]:
    """What a run would be pinned to, read now with no gateway and no model call: each set's alias map and the
    digests behind it, the judge's, and every pin that would invalidate the baseline."""
    with tempfile.TemporaryDirectory(prefix="ch15-live-") as tmp:
        now = measure.current_pins()
        _, judge_pins = prepare_judge(plan, Path(tmp) / "judge")
        pins: dict[str, Any] = {"prompt": now["prompt"], "judge": judge_pins, "workflows": {}}
        for workflow in plan.workflows:
            _, served = prepare(workflow, plan, Path(tmp) / workflow)
            pins["workflows"][workflow] = {"set": now["sets"][workflow], "rubric": now["rubrics"].get(workflow),
                                           "aliases": served["aliases"], "models": served["models"]}
            progress(f"{workflow}: {len(registry.read_jsonl(registry.CASES / f'{workflow}.jsonl'))} cases; "
                     + "; ".join(f"{a} -> {s}" for a, s in served["aliases"].items()) + "; "
                     + "; ".join(f"{s} {_served(m)}" for s, m in served["models"].items()))
        progress(f"judge: {plan.judge}, {judge_pins['served']} {_served(judge_pins)}")
    held = registry.read_json(baseline)["pins"]
    problems = gate.pin_problems({**held, "workflows": {w: p for w, p in held["workflows"].items() if w in plan.workflows}},
                                 pins)
    for scope, found in sorted(problems.items()):
        for problem in found:
            progress(f"invalidates the baseline, {scope}: {problem}")
    if not problems:
        progress("The baseline holds for this alias map and these digests.")
    return {"pins": pins, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", choices=MODELS, default=MODELS[0],
                        help="which configs: the workflows' own (gpt-oss-20b) or their Gemma copies")
    parser.add_argument("--judge", choices=MODELS, help="the judge; by default the other local model")
    parser.add_argument("--ollama-port", type=int, help="the workflows' model's Ollama; by default the configs' 11434, "
                        "and 11435 for Gemma 4 12B, the portable 0.40.13")
    parser.add_argument("--judge-ollama-port", type=int, help="the judge's Ollama, by the same defaults")
    parser.add_argument("--workflows", help="a smoke run on these sets, comma-separated (skeleton,w1,...,w5)")
    parser.add_argument("--limit", type=int, help="a smoke run on the first N cases of each set")
    parser.add_argument("--scratch", type=Path, help="resume the run whose scratch folder this is")
    parser.add_argument("--dry-run", action="store_true", help="the pins a run would have, and whether the baseline holds")
    parser.add_argument("--compare", type=Path, help="compare this result with the baseline again")
    parser.add_argument("--accept", type=Path, help="after review: make this complete run the baseline")
    args = parser.parse_args(argv)
    if args.accept:
        print(compare(args.accept)[1], end="")
        print(accept(args.accept))
        return 0
    if args.compare:
        passed, text = compare(args.compare)
        print(text, end="")
        return 0 if passed else 1
    workflows = measure.WORKFLOWS
    if args.workflows:
        asked = [w.strip() for w in args.workflows.split(",") if w.strip()]
        unknown = sorted(set(asked) - set(measure.WORKFLOWS))
        if unknown or not asked:
            parser.error(f"--workflows takes some of {', '.join(measure.WORKFLOWS)}; got {args.workflows!r}")
        workflows = tuple(w for w in measure.WORKFLOWS if w in asked)
    judge = args.judge or next(m for m in MODELS if m != args.model)
    plan = Plan(args.model, judge, args.ollama_port or OLLAMA_PORTS.get(args.model),
                args.judge_ollama_port or OLLAMA_PORTS.get(judge), workflows, args.limit)
    if args.dry_run:
        dry_run(plan)
        return 0
    scratch = args.scratch or SCRATCH / f"live-{time.strftime('%Y%m%dT%H%M%S')}"
    path = run(plan, scratch, progress=lambda line: print(line, flush=True))
    print(f"wrote {path}")
    if not plan.complete:
        print("A smoke run: its result stays in the scratch folder and can't be accepted.")
        return 0
    passed, text = compare(path)
    print(text, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
