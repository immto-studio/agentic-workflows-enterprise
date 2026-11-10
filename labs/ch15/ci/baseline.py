"""The accepted baseline (chapter 15, step 7, E-D9, E-D12): what the gate holds a live run to.

Until the first live run is accepted, the baseline is built from the results the lab already holds:

  step 2's replay   results/<date>/replay-<workflow>-gpt-oss-20b.json: for each set, the kept run that stands for
                    the workflow on the current alias map (RUNS), every case's verdicts check by check
  step 3's judge    results/<date>/judge-<workflow>-gemma4-12b.json: Gemma 4 12B's reading of the same outputs, the
                    cross-judging of E-D4: its model, digest, server, and alias map, the prompt's and rubrics' hashes,
                    how many outputs it read and how many of those are texts of the author's sample, and its tokens
                    from its gateway log (judge-gateway-gemma4-12b.jsonl). None of its verdicts: the author labels
                    the sample blind (E-D5), and a count over the other outputs, set against step 3's tables, would
                    say how the judge read the sampled ones. The judge is not gated until it is calibrated.

The current alias map is the one the workflows' own configs give: every chat alias on gpt-oss:20b, W1's embedding
alias on qwen3-embedding:0.6b, and chapter 9's restricted alias for the skeleton. So the baseline holds
gpt-oss-20b's runs, judged by Gemma 4 12B, and Gemma's own runs stay in the replay. Every pin the results record
goes in: the sets' versions; the alias maps, which W1's and W2's runs recorded, and for the other four the map
their runner's config has served since before the run, from the file's git history (STARTED_WITH); the Ollama that
served each run where a result records it; the judge's model, digest, server, and alias map; and the prompt's and
rubrics' hashes. No kept workflow run recorded a model digest, so the baseline holds none for the workflows'
models, and the first live run finds it unpinned until a run is accepted (ci/live.py --accept), as E-D12 asks of a
digest it can't show unchanged.

Once a live run is accepted, the baseline is that run's measures and pins, and the source names the result file
and its hash. Either way `--check` rebuilds the baseline from its source and compares, so a replay file, a judge
file, the sample, or an accepted result that changed since fails the gate until the baseline is built or accepted
again and reviewed.

Run (from labs/ch15):  python ci/baseline.py           build baseline/baseline.json from the kept results
                       python ci/baseline.py --check   exit 1 if the baseline is not what its source gives
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import measure  # noqa: E402  (puts the lab's folders on sys.path)
import registry  # noqa: E402

BASELINE = LAB / "baseline" / "baseline.json"
RESULTS = LAB / "results" / "2026-11-03"  # step 2's replay and step 3's judge runs
MODEL = "gpt-oss-20b"  # the model every alias of the current map serves
JUDGE = "gemma4-12b"  # E-D4: the other local model judges it
# The kept run that stands for each workflow on gpt-oss-20b: the one its README reports, the last it kept. W2's
# runs 1 to 3 came before the set grew to 25 cases, and W4's two other runs before the agents' logs were kept.
RUNS = {"skeleton": "2026-10-29", "w1": "2026-10-29", "w2": "2026-11-02", "w3": "2026-11-02", "w4": "2026-11-02",
        "w5": "2026-11-03/after-review"}
# The alias map of the four kept runs that recorded none: the config each one's runner starts the gateway with.
# git log shows each config serving every chat alias from gpt-oss:20b since before the run: chapter 9's since
# 6e70153 (29 October 2026), and W2's, which W3's, W4's, and W5's runners start with, since a8fb2a1 (2 November
# 2026, before their runs). The map is written here, not read from the file, so a later remap of the file leaves
# the record of these runs as it was.
GPT_OSS = "ollama_chat/gpt-oss:20b"
W2_CONFIG = f"{registry.W2}/gateway/litellm.config.yaml"
STARTED_WITH = {
    "skeleton": ("labs/ch09/gateway/litellm.config.yaml", "6e70153", {"larkspur-chat-restricted": GPT_OSS}),
    **{w: (W2_CONFIG, "a8fb2a1", {"larkspur-chat": GPT_OSS, "larkspur-chat-restricted": GPT_OSS})
       for w in ("w3", "w4", "w5")},
}
NO_DIGEST = "the run recorded none"
NOT_CARRIED = ("not carried from step 3's runs: the author labels the sample blind to the judge (E-D5), and a count "
               "over the other outputs, set against step 3's tables, would give away how it read the sampled ones")
# Said beside the pins, since no kept workflow run recorded a digest: the lab's only records of one are later.
DIGESTS_NOTE = ("No kept workflow run recorded a model digest. The lab's records of one are step 3's judge runs and "
                "step 6's red-team run of 3 November 2026, after these runs: gpt-oss:20b a0b38d0b19f7 on Ollama "
                "0.22.1 and gemma4:12b 6114515d63c1 on Ollama 0.40.13.")


def _rel(path: Path) -> str:
    """A repository-relative POSIX path, or the absolute one for a file outside the repository (a test's)."""
    try:
        return registry.rel(path)
    except ValueError:
        return Path(path).resolve().as_posix()


def _source(path: Path) -> dict[str, str]:
    return {"path": _rel(path), "sha256": registry.sha256_of(path)}


def _served_from(workflow: str, run: registry.Run) -> tuple[dict[str, str], str, str | None, str]:
    """The kept run's alias map and where it comes from, and the Ollama version that served it and where that
    comes from."""
    if workflow in ("w1", "w2"):
        meta = registry.read_json(registry.path(run.main))["meta"]
        return (meta["gateway_models"], f"recorded by the run ({run.main}, meta.gateway_models)",
                meta.get("ollama"), "recorded by the run (meta.ollama)")
    config, commit, aliases = STARTED_WITH[workflow]
    where = (f"the run recorded none; its runner starts the gateway with {config}, which has served these "
             f"aliases since {commit}, before the run")
    if workflow == "skeleton":
        memory = "labs/ch09/results/2026-10-29/gpu-memory.json"
        return (aliases, where, registry.read_json(registry.path(memory))["ollama"],
                f"chapter 9's measurement of the same day on the same server ({memory})")
    if workflow in ("w4", "w5"):
        summary = registry.read_json(registry.path(run.folder) / f"summary-{MODEL}.json")
        return aliases, where, summary["versions"]["ollama"], "recorded by the run (summary versions.ollama)"
    return aliases, where, None, "the run recorded none"


def _kept_run(workflow: str) -> registry.Run:
    found = [r for r in registry.kept_runs(workflow) if (r.model, r.label) == (MODEL, RUNS[workflow])]
    if len(found) != 1:
        raise SystemExit(f"{workflow}: no single kept run {RUNS[workflow]} on {MODEL}")
    return found[0]


def from_results(results: Path = RESULTS) -> dict[str, Any]:
    """The baseline built from step 2's replay files and step 3's judge files in `results`."""
    import items as itemize  # the judged texts, to withhold a verdict on a sampled one
    import report  # step 6's withholding: the hash of a text as it compares texts, and the sample's texts

    by_key = {i.key: i for its in itemize.build_all().values() for i in its}
    sampled = report.sampled_texts()
    judge_log = results / f"judge-gateway-{JUDGE}.jsonl"
    calls = {line["trace_id"]: line for line in registry.read_jsonl(judge_log) if line.get("event") == "call"}
    sources = [_source(judge_log), _source(LAB / "labels" / "sample.json")]
    pins: dict[str, Any] = {"prompt": None, "judge": None, "workflows": {}}
    workflows: dict[str, Any] = {}
    for workflow in measure.WORKFLOWS:
        replay_file = results / f"replay-{workflow}-{MODEL}.json"
        replay = registry.read_json(replay_file)
        sources.append(_source(replay_file))
        run = next(r for r in replay["runs"] if r["run"] == RUNS[workflow])
        kept = _kept_run(workflow)
        aliases, aliases_from, server, server_from = _served_from(workflow, kept)
        models = {served: {"digest": None, "server": server, "digest_from": NO_DIGEST, "server_from": server_from}
                  for served in sorted(set(aliases.values()))}
        cases = measure.case_verdicts(workflow, run["cases"])
        entry: dict[str, Any] = {"run": RUNS[workflow], "model": MODEL, "cases": cases,
                                 "tally": measure.tally(workflow, cases)}
        pin: dict[str, Any] = {"set": {"version": replay["set"]["version"], "cases": replay["set"]["cases"]},
                               "rubric": None, "aliases": aliases, "aliases_from": aliases_from, "models": models}
        tokens: dict[str, Any] = {"workflow": _workflow_tokens(workflow, kept)}
        if workflow in measure.JUDGED:
            judge_file = results / f"judge-{workflow}-{JUDGE}.json"
            doc = registry.read_json(judge_file)
            sources.append(_source(judge_file))
            if doc["set"]["version"] != replay["set"]["version"]:
                raise SystemExit(f"{workflow}: the judge read set {doc['set']['version'][:12]}, the replay "
                                 f"{replay['set']['version'][:12]}")
            judge_pin = {"model": JUDGE, "served": doc["judge_model"]["served"], "digest": doc["judge_model"]["digest"],
                         "server": doc["judge_model"]["ollama"], "aliases": doc["gateway"]["aliases"],
                         "config": doc["gateway"]["config"]}
            if pins["judge"] not in (None, judge_pin) or pins["prompt"] not in (None, doc["prompt"]["sha256"]):
                raise SystemExit(f"{judge_file.name}: another judge model or prompt than the other judge files")
            pins["judge"], pins["prompt"] = judge_pin, doc["prompt"]["sha256"]
            pin["rubric"] = doc["rubric"]["sha256"]
            rows = [r for r in doc["items"] if r["slice"] == "cross"
                    and (r["model"], r["author"], r["run"]) == (MODEL, MODEL, RUNS[workflow])]
            withheld = sum(report.text_sha256(by_key[(workflow, r["model"], r["run"], r["case"], r["part"])].output)
                           in sampled for r in rows)
            # No verdict of step 3's is carried: a count over the outputs outside the sample, subtracted from step 3's
            # tables, would say how the judge read the sampled ones, which the author labels blind (E-D5).
            entry["judge"] = {"judged": len(rows), "withheld": withheld, "right": None, "wrong": None, "no_verdict": None,
                              "verdicts": NOT_CARRIED}
            tokens["judge"] = measure.chat_tokens([calls[r["trace_id"]] for r in rows if r["trace_id"] in calls])
        entry["tokens"] = tokens
        pins["workflows"][workflow] = pin
        workflows[workflow] = entry
    return {"kind": "baseline", "schema": measure.SCHEMA,
            "source": {"kind": "kept", "results": _rel(results), "model": MODEL, "judge": JUDGE,
                       "runs": RUNS, "files": sources, "digests": DIGESTS_NOTE},
            "pins": pins, "workflows": workflows}


def _workflow_tokens(workflow: str, run: registry.Run) -> dict[str, Any]:
    """The workflow model's tokens as the kept run holds them: W5 kept the gateway's log; the skeleton, W1, and
    W2 kept each call's usage as the gateway returned it; W3 and W4 kept neither."""
    folder = registry.path(run.folder)
    if workflow == "w5":
        lines = registry.read_jsonl(folder / f"logs-{MODEL}" / "gateway.jsonl")
        return measure.chat_tokens(lines, "w5-drift") | {"from": "the gateway's log the run kept"}
    if workflow in ("skeleton", "w1", "w2"):
        results = registry.read_json(registry.path(run.main))["results"]
        calls = [c for r in results for c in r.get("model_calls") or []]
        return {"calls": len(calls), "prompt": sum(c.get("prompt_tokens") or 0 for c in calls),
                "completion": sum(c.get("completion_tokens") or 0 for c in calls),
                "from": "each call's usage as the gateway returned it, kept by the run"}
    return {"calls": None, "prompt": None, "completion": None, "from": "the run kept no record of its tokens"}


def from_live(result: dict[str, Any], path: Path, accepted: str) -> dict[str, Any]:
    """The baseline a reviewed live run becomes: its pins and its measures, the result file named by its hash."""
    if result.get("kind") != "live" or not result["run"].get("complete"):
        raise ValueError(f"{path.name}: only a complete live run can become the baseline")
    workflows = {w: {k: v for k, v in entry.items() if k in ("run", "model", "cases", "tally", "judge", "tokens")}
                 for w, entry in result["workflows"].items()}
    return {"kind": "baseline", "schema": measure.SCHEMA,
            "source": {"kind": "live", "path": _rel(path), "sha256": registry.sha256_of(path), "accepted": accepted,
                       "model": result["run"]["model"], "judge": result["run"]["judge"]},
            "pins": result["pins"], "workflows": workflows}


def expected(baseline: dict[str, Any]) -> dict[str, Any]:
    """What the baseline's source gives now."""
    source = baseline["source"]
    if source["kind"] == "kept":
        return from_results(registry.path(source["results"]))
    path = registry.path(source["path"])
    if not path.exists():
        raise FileNotFoundError(f"{source['path']}, the accepted run, is not in the repository")
    return from_live(registry.read_json(path), path, source["accepted"])


def check(path: Path = BASELINE) -> list[str]:
    """What no longer matches: a baseline that isn't what its source gives, with the first fields that differ."""
    if not path.exists():
        return [f"{_rel(path)} is missing; run python ci/baseline.py"]
    committed = registry.read_json(path)
    try:
        fresh = expected(committed)
    except (FileNotFoundError, SystemExit, ValueError, KeyError) as exc:
        return [f"{_rel(path)}: its source can't be read: {exc}"]
    if fresh == committed:
        return []
    return [f"{_rel(path)} is not what its source gives now ({where}); build or accept the baseline again and "
            "review the diff" for where in _differences(committed, fresh)[:5]]


def _differences(a: Any, b: Any, at: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                out.append(f"{at}/{key}")
            else:
                out += _differences(a[key], b[key], f"{at}/{key}")
        return out
    return [] if a == b else [at or "/"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the baseline is not what its source gives")
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--out", type=Path, default=BASELINE)
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.out)
        print("\n".join(problems) if problems else f"{_rel(args.out)} is what its source gives")
        return 1 if problems else 0
    if args.out.exists() and registry.read_json(args.out)["source"]["kind"] == "live":
        raise SystemExit(f"{_rel(args.out)} is an accepted live run; building it from the kept results would undo "
                         "the acceptance. Accept a run with ci/live.py --accept instead.")
    measure.write_json(args.out, from_results(args.results))
    print(f"wrote {_rel(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
