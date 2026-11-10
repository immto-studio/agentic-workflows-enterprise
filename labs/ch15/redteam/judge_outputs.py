"""The judge over the red-team outputs (chapter 15, step 6, E-D10), with step 3's code and current rubrics.

Each local model judges the other's red-team outputs, as in step 3 (E-D4): the rubric of the output's workflow
(W1 to W3 at v3, W4 and W5 at v2, the files as they are), the reference its case gives (judge/items.py), and
the output, rendered by judge.render and sent by judge.judge through chapter 5's gateway at temperature 0, with
the evaluated workflow's tag and the case's class, started as judge/run_judge.py starts it. Every red-team
output read a plant, so the rubric's planted criterion is read for every W1 to W3 output, where step 3 read it
for the cases a golden file marks injection. Text a workflow's code fixes (the fixed refusals, W4's stub, W5's
stub bodies) goes to no judge, as in step 3. W5's outputs are its pull requests' titles and prose, one item each.

The verdicts are provisional: no judge is calibrated until the author's labels (step 5, E-D5).

Run (from labs/ch15, the judge's Ollama up and alone on the GPU):
  python redteam/judge_outputs.py --judge gemma4-12b --outputs redteam/_lab/run-gpt-oss-20b --ollama-port 11435
  python redteam/judge_outputs.py --judge gpt-oss-20b --outputs redteam/_lab/run-gemma4-12b
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "layers", LAB / "cases", LAB, LAB / "judge", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import httpx  # noqa: E402

import deterministic  # noqa: E402
import items as itemize  # noqa: E402
import judge as judging  # noqa: E402
import registry  # noqa: E402
import run_judge  # noqa: E402

TAGS = {"w1": "w1-knowledge", "w2": "w2-ops-assistant", "w3": "w3-incident", "w4": "w4-change", "w5": "w5-drift"}
CONFIGS = {"gpt-oss-20b": f"{registry.W2}/gateway/litellm.config.yaml", "gemma4-12b": f"{registry.W2}/gateway/litellm.gemma.yaml"}


def judge_key(line: dict[str, Any], part: str = "") -> str:
    return json.dumps([line["workflow"], line["variant"], line["case"], line.get("workspace"), part])


def build(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the judge reads for each red-team output a model wrote: one item per output (W5: per pull request
    whose title and prose the model wrote), with its reference, the rubric's conditions, its tag and class."""
    cases = {w: {c["id"]: c for c in registry.read_jsonl(registry.CASES / f"{w}.jsonl")} for w in TAGS}
    out: list[dict[str, Any]] = []
    by_workflow: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        by_workflow.setdefault(line["workflow"], []).append(line)
    for workflow, rows in by_workflow.items():
        with registry.loaded(workflow) as mods:
            ctx = deterministic.context(workflow, mods)
            for line in rows:
                if line.get("error"):
                    continue
                base = {"key": None, "workflow": workflow, "tag": TAGS[workflow], "variant": line["variant"],
                        "case": line["case"], "part": "", "author": line["model"]}
                if workflow == "w5":
                    out += _w5_items(mods, line, base)
                    continue
                case = cases[workflow][line["case"]]
                e, n = case["expected"], case["negative"]
                item = _item(workflow, mods, ctx, line, case, e, n)
                if item is not None:
                    out.append({**base, "key": judge_key(line), "data_class": case["data_class"], **item})
    return out


def _item(workflow: str, mods: Any, ctx: dict[str, Any], line: dict[str, Any], case: dict[str, Any], e: dict[str, Any],
          n: dict[str, Any]) -> dict[str, Any] | None:
    text = line["text"] or ""
    if workflow == "w2":
        text = mods.answer.without_reference(text)  # as step 3's items read W2's answers
    if not text.strip():
        return None
    if workflow == "w1":
        if text in (mods.answer.REFUSAL, mods.answer.SEARCH_FAILED):
            return None
        qid = case["id"].split("/")[0]
        conditions = itemize._conditions(("answerable", not n["refusal"]), ("denied", n["refusal"]),
                                         ("stale", n["trap"] == "stale"), ("injection", True))
        reference = itemize._w1_reference(case, mods.answer_eval.FACTS[qid], ctx["pages"][e["source_document"]])
    elif workflow == "w2":
        if text in (mods.answer.REFUSAL, mods.answer.READ_FAILED):
            return None
        conditions = itemize._conditions(("facts", bool(e["facts"])), ("answer", not n["refusal"]),
                                         ("refusal", n["refusal"]), ("injection", True))
        reference = itemize._w2_reference(case)
    elif workflow == "w3":
        fixed = {mods.loop.w2.REFUSAL, mods.loop.w2.READ_FAILED, mods.loop.BUDGET_EXHAUSTED, mods.loop.MODEL_UNAVAILABLE}
        if text.strip() in fixed:
            return None
        conditions = itemize._conditions(("facts", bool(e["facts"])), ("answer", not n["refusal"]),
                                         ("refusal", n["refusal"]), ("injection", True))
        reference = itemize._w3_reference(case)
    else:
        pack = line["output"]["pack"]
        if (pack.get("risk") or {}).get("rationale_source") != "model":
            return None
        conditions = ("always",)
        reference = itemize._w4_reference(case, pack)
    return {"conditions": list(conditions), "reference": reference, "output": text}


def _w5_items(mods: Any, line: dict[str, Any], base: dict[str, Any]) -> list[dict[str, Any]]:
    score = mods.score
    record, packs = line["output"]["record"], line["output"]["packs"]
    found = {f["key"]: f for f in record.get("findings") or []}
    out = []
    for key, pack in sorted(packs.items()):
        if pack.get("action") not in ("opened", "updated") or pack.get("number") is None or pack.get("body_source") != "model":
            continue
        finding = score.finding_from(found[key])
        facts = score.prose.facts_for_model(finding)
        conditions = itemize._conditions(("attribution", "audit_trail_event" in facts),
                                         ("no_attribution", "audit_trail_event" not in facts),
                                         ("saving", "estimated_monthly_saving" in facts),
                                         ("no_saving", "estimated_monthly_saving" not in facts))
        prose_part = score.split_body(pack.get("body") or "")[0].strip()
        out.append({**base, "key": judge_key(line, key), "part": key, "data_class": "confidential",
                    "conditions": list(conditions), "reference": itemize._w5_reference(facts),
                    "output": f"TITLE: {pack.get('title') or ''}\n\n{prose_part}"})
    return out


def judge_all(judge: str, outputs: Path, ollama_port: int | None, progress: Any = print) -> Path:
    lines = registry.read_jsonl(outputs / "outputs.jsonl")
    authors = {line["model"] for line in lines}
    if judge in authors:
        raise SystemExit(f"{judge} wrote these outputs; each model judges the other's (E-D4)")
    todo_items = build(lines)
    scratch = (outputs / f"judge-{judge}").resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    judged_file = outputs / f"judged-by-{judge}.jsonl"
    done = {r["key"] for r in registry.read_jsonl(judged_file)} if judged_file.exists() else set()
    todo = [i for i in todo_items if i["key"] not in done]
    progress(f"{len(todo_items)} outputs to judge, {len(todo)} left")
    if not todo:
        return judged_file
    think = run_judge.THINK.get(judge)
    copy, base = run_judge.prepare_config(registry.path(CONFIGS[judge]), scratch, ollama_port,
                                          max(run_judge.MIN_NUM_CTX, judging.MAX_TOKENS + 4096), think)
    meta = scratch / "run.json"
    if not meta.exists():
        meta.write_text(json.dumps({"measured": date.today().isoformat(), "judge": judge,
                                    "model": run_judge.model_record(base, run_judge.alias_map(copy)[judging.ALIAS], think),
                                    "config": {"source": CONFIGS[judge], "sha256": registry.sha256_of(copy)},
                                    "prompt": registry.sha256_of(judging.PROMPT),
                                    "rubrics": {w: registry.sha256_of(judging.RUBRICS / f"{w}.yaml") for w in TAGS}},
                                   indent=1) + "\n", encoding="utf-8", newline="\n")
    port, gateway = run_judge.start_gateway(copy, run_judge.prepare_manifests(scratch), scratch)
    prompt = judging.load_prompt()
    rubrics = {w: judging.load_rubric(w) for w in TAGS}
    pace = run_judge.Pace()
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=judging.TIMEOUT_S) as client, judged_file.open("a", encoding="utf-8", newline="\n") as out:
            for n, item in enumerate(todo, 1):
                messages = judging.render(prompt, rubrics[item["workflow"]], tuple(item["conditions"]), item["reference"],
                                          item["output"])
                pace.wait(item["tag"])
                result = judging.judge(client, f"http://127.0.0.1:{port}/v1", run_judge.GATEWAY_KEY, messages, item["tag"],
                                       item["data_class"])
                out.write(json.dumps({"key": item["key"], "judge": judge, "workflow": item["workflow"],
                                      "variant": item["variant"], "case": item["case"], "part": item["part"],
                                      "criteria": [c["id"] for c in judging.criteria_for(rubrics[item["workflow"]],
                                                                                         tuple(item["conditions"]))],
                                      **result}, ensure_ascii=False) + "\n")
                out.flush()
                # No verdict on the console: a red-team text can be a sampled output's, which the author labels
                # blind (report.py withholds those verdicts).
                shown = "judged" if result["verdict"] else "unparsable" if result["unparsable"] else f"error: {result['error']}"
                progress(f"[{n}/{len(todo)}] {item['workflow']} {item['variant']} {item['case']} {item['part']}: {shown}")
        answered = {r["trace_id"] for r in registry.read_jsonl(judged_file) if not r.get("error")}
        run_judge.wait_for_log(scratch / "gateway.jsonl", answered)
    finally:
        run_judge.stop(gateway)
    record = registry.read_json(meta)
    record["seconds"] = round(record.get("seconds", 0) + time.perf_counter() - started, 1)
    record.setdefault("model", {})["loaded"] = run_judge.loaded(base)
    meta.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")
    return judged_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--judge", choices=sorted(CONFIGS), required=True)
    parser.add_argument("--outputs", type=Path, required=True, help="the other model's red-team run folder")
    parser.add_argument("--ollama-port", type=int)
    args = parser.parse_args(argv)
    path = judge_all(args.judge, args.outputs, args.ollama_port, progress=lambda line: print(line, flush=True))
    print(f"judgements in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
