"""What a run of the golden sets measures, case by case and check by check, and what it was pinned to
(chapter 15, step 7, E-D9, E-D12).

The gate (ci/gate.py) sets two of these documents side by side: the accepted baseline (baseline/baseline.json)
and the last live run (live/*.json). Both hold, for each of the six sets:

  cases   per case, the workflow scorer's verdict and every check's, the deterministic layer's and the
          trajectory layer's (layers/), named as step 2's replay names them: True, False, or None where the
          check doesn't apply to the case or the kept files can't decide it
  tally   the same, counted per check
  judge   for W1 to W5, the judge's verdicts on the outputs a model wrote (E-D4), counted over the outputs
          whose text is not in the author's sample; a verdict on a sampled text is withheld (E-D5), as step 6
          withheld them. The baseline built from step 3's runs counts the outputs and the sampled texts and
          carries no verdict (ci/baseline.py)
  tokens  the calls and tokens of the workflow's model and of its judge, from the gateway's log where the run
          kept one (E-D12); no prices

and the pins (E-D12): each set's version, each workflow's alias map and the digest of every model behind it
with the Ollama that serves it, the judge's model and alias map, and the hashes of the judge's prompt and
rubrics. Where a run recorded no pin, the document says so and holds None.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "layers", LAB / "cases", LAB, LAB / "judge", LAB / "labels", LAB / "redteam"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import convert  # noqa: E402
import deterministic  # noqa: E402
import judge as judging  # noqa: E402
import registry  # noqa: E402
import trajectory  # noqa: E402

SCHEMA = 1
SCORER = "scorer"
JUDGE = "judge"
WORKFLOWS = registry.ORDER  # the skeleton, then W1 to W5
JUDGED = judging.JUDGED  # E-D3: the workflows whose prose a judge reads
# What step 6 put in place of a verdict on a sampled text (redteam/report.py), so the two read the same.
WITHHELD = "a sampled text: the author labels it blind to the judge (labels/sample.json, E-D5)"
# The model behind an alias, by the name the lab gives each model (items.MODEL_TAGS has the same three).
MODEL_TAGS = {"ollama_chat/gpt-oss:20b": "gpt-oss-20b", "ollama_chat/gemma4:12b": "gemma4-12b",
              "bedrock/converse/ca.amazon.nova-lite-v1:0": "nova-lite"}


def check_names(workflow: str) -> list[str]:
    """Every check the gate knows for a workflow: the scorer's verdict on the case, each check of the
    deterministic layer, each trajectory check the layer can decide for the workflow, and for W1 to W5 the
    judge's verdicts."""
    names = [SCORER]
    names += [f"deterministic.{n}" for n in deterministic.CHECKS[workflow]]
    names += [f"trajectory.{n}" for n in trajectory.CHECKS[workflow]]
    return names + ([JUDGE] if workflow in JUDGED else [])


def case_checks(workflow: str) -> list[str]:
    """The checks decided case by case, which is every check but the judge's."""
    return [n for n in check_names(workflow) if n != JUDGE]


def case_verdicts(workflow: str, rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, bool | None]]:
    """Per case of a replayed run (run_replay.replay_run's rows, or a committed replay file's), the scorer's
    verdict and each check's ok, cases in the converted set's order and checks in check_names' order."""
    traj = set(trajectory.CHECKS[workflow])
    names = case_checks(workflow)
    out: dict[str, dict[str, bool | None]] = {}
    for row in rows:
        verdicts: dict[str, bool | None] = {SCORER: row["scorer"]["pass"]}
        verdicts |= {f"deterministic.{n}": c["ok"] for n, c in row["deterministic"]["checks"].items()}
        verdicts |= {f"trajectory.{n}": c["ok"] for n, c in row["trajectory"]["checks"].items() if n in traj}
        out[row["id"]] = {n: verdicts[n] for n in names if n in verdicts}
    return out


def failing_details(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per case, the detail of every check that failed, as the layers give it: the facts left out by their
    first spelling, the planted phrases, the redacted shapes by what the server writes in their place."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        failed = {f"{layer}.{n}": c["detail"] for layer in ("deterministic", "trajectory")
                  for n, c in row[layer]["checks"].items() if c["ok"] is False}
        if failed:
            out[row["id"]] = failed
    return out


def tally(workflow: str, cases: dict[str, dict[str, bool | None]]) -> dict[str, dict[str, int]]:
    """Per check, the cases it passed, failed, and could not decide or does not apply to."""
    out = {}
    for name in case_checks(workflow):
        values = [verdicts.get(name) for verdicts in cases.values()]
        out[name] = {"passed": sum(v is True for v in values), "failed": sum(v is False for v in values),
                     "undecided": sum(v is None for v in values)}
    return out


def judge_tally(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """The judge's verdicts on a run's outputs: how many it read, how many are withheld as sampled texts, and
    over the rest, right, wrong, and those with no verdict (an unparsable reply or a failed call)."""
    rows = list(rows)
    shown = [r for r in rows if not r.get("withheld")]
    return {"judged": len(rows), "withheld": len(rows) - len(shown),
            "right": sum(r.get("verdict") == "right" for r in shown),
            "wrong": sum(r.get("verdict") == "wrong" for r in shown),
            "no_verdict": sum(r.get("verdict") is None for r in shown)}


def chat_tokens(lines: Iterable[dict[str, Any]], tag: str | None = None) -> dict[str, int]:
    """Chat calls and their tokens in a gateway log, the `call` lines the hooks write, for one workflow's tag;
    embedding calls (W1's larkspur-embed) are counted apart by embed_tokens."""
    calls = [line for line in lines if line.get("event") == "call" and line.get("requested_alias") != "larkspur-embed"
             and (tag is None or line.get("workflow") == tag)]
    return {"calls": len(calls), "prompt": sum(c.get("prompt_tokens") or 0 for c in calls),
            "completion": sum(c.get("completion_tokens") or 0 for c in calls)}


def embed_tokens(lines: Iterable[dict[str, Any]]) -> dict[str, int]:
    calls = [line for line in lines if line.get("event") == "call" and line.get("requested_alias") == "larkspur-embed"]
    return {"calls": len(calls), "prompt": sum(c.get("prompt_tokens") or 0 for c in calls)}


def model_tag(served: str | None) -> str | None:
    """The lab's name for the model behind an alias, or the served name itself for a model the lab doesn't know."""
    if served is None:
        return None
    return MODEL_TAGS.get(served, served.split("/", 1)[-1])


def current_pins() -> dict[str, Any]:
    """What the repository holds now: each set's version and size, each judged workflow's rubric hash, and the
    judge's prompt hash. A run made on other files is stale."""
    sets = {w: {"version": convert.version(w), "cases": len(registry.read_jsonl(registry.CASES / f"{w}.jsonl"))}
            for w in WORKFLOWS}
    rubrics = {w: registry.sha256_of(judging.RUBRICS / f"{w}.yaml") for w in JUDGED}
    return {"prompt": registry.sha256_of(judging.PROMPT), "sets": sets, "rubrics": rubrics}


def write_json(path: Path, document: Any) -> Path:
    """The lab's JSON files: one-space indent, UTF-8 as written, LF, a newline at the end."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def short(sha: str | None) -> str:
    return sha[:12] if sha else "none"
