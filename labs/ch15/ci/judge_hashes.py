"""Every current judge result made with the judge's prompt and rubrics as they are now (chapter 15, step 7, E-D9).

A verdict answers the question its prompt and rubric asked, and every file that holds current verdicts records the
hashes it was made with (registry.sha256_of, CRLF read as LF). This sets each against the files in judge/ now:

  step 3's runs   results/<date>/judge-<workflow>-<judge>.json, the current files; judge-v1/ and judge-v2/ are the
                  record of the earlier rubrics and are left as they are
  step 6's run    results/<date>/redteam-<workflow>-<model>.json: the prompt and the rubric its judge read
  the live run    the last file in live/: the prompt and each rubric in its pins
  the baseline    baseline/baseline.json: the same

A rubric or the prompt changed without the judge running again fails here, and the line names the file and how
to judge again. tests/test_judge.py holds step 3's files to more than this (every request as the code renders it
now); this is the PR job's own step, and it covers the files the tests don't.

Run (from labs/ch15):  python ci/judge_hashes.py
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

import gate  # noqa: E402
import judge as judging  # noqa: E402
import registry  # noqa: E402
from replay_check import latest_results  # noqa: E402

AGAIN = {
    "step3": "python judge/run_judge.py --judge {judge} --workflows {workflow}, then --summary",
    "step6": "the red-team judging again (redteam/judge_outputs.py, then redteam/report.py)",
    "live": "a live run (python ci/live.py)",
    "baseline": "a live run accepted after review (python ci/live.py --accept live/<run>.json)",
}


def current(rubrics: Path = judging.RUBRICS, prompt: Path = judging.PROMPT) -> dict[str, Any]:
    return {"prompt": registry.sha256_of(prompt),
            "rubrics": {w: registry.sha256_of(rubrics / f"{w}.yaml") for w in measure.JUDGED}}


def _rel(path: Path) -> str:
    try:
        return registry.rel(path)
    except ValueError:
        return path.as_posix()


def _compare(where: str, kind: str, made: dict[str, Any], now: dict[str, Any], **names: str) -> list[str]:
    out = []
    if made.get("prompt") != now["prompt"]:
        out.append(f"{where}: judged with judge/prompt.txt {measure.short(made.get('prompt'))}, which is "
                   f"{measure.short(now['prompt'])} now; run {AGAIN[kind].format(**names)}")
    for workflow, sha in sorted((made.get("rubrics") or {}).items()):
        if sha != now["rubrics"][workflow]:
            out.append(f"{where}: {workflow} judged with judge/rubrics/{workflow}.yaml {measure.short(sha)}, which is "
                       f"{measure.short(now['rubrics'][workflow])} now; run "
                       f"{AGAIN[kind].format(**(names | {'workflow': workflow}))}")
    return out


def check(results: Path | None = None, rubrics: Path = judging.RUBRICS, prompt: Path = judging.PROMPT,
          live: Path = gate.LIVE, baseline: Path = gate.BASELINE) -> list[str]:
    now = current(rubrics, prompt)
    results = results or latest_results()
    problems = []
    for path in sorted(results.glob("judge-w*-*.json")):
        doc = registry.read_json(path)
        made = {"prompt": doc["prompt"]["sha256"], "rubrics": {doc["workflow"]: doc["rubric"]["sha256"]}}
        problems += _compare(_rel(path), "step3", made, now, judge=doc["judge"], workflow=doc["workflow"])
    for path in sorted(results.glob("redteam-w*-*.json")):
        doc = registry.read_json(path)
        for judge, run in sorted((doc.get("judges") or {}).items()):
            made = {"prompt": run.get("prompt"), "rubrics": {doc["workflow"]: (run.get("rubrics") or {}).get(doc["workflow"])}}
            problems += _compare(f"{_rel(path)} ({judge})", "step6", made, now)
    latest = gate.latest_live(live)
    for kind, path in (("live", latest), ("baseline", baseline)):
        if path is None or not path.exists():
            continue
        pins = registry.read_json(path)["pins"]
        made = {"prompt": pins.get("prompt"),
                "rubrics": {w: p.get("rubric") for w, p in pins["workflows"].items() if w in measure.JUDGED}}
        problems += _compare(_rel(path), kind, made, now)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args(argv)
    problems = check()
    if problems:
        print("A judge result was made with another prompt or rubric than judge/ holds now:")
        print("\n".join(f"- {p}" for p in problems))
        return 1
    now = current()
    print(f"Every current judge result was made with judge/prompt.txt {measure.short(now['prompt'])} and the rubrics "
          "as they are now: " + ", ".join(f"{w} {measure.short(s)}" for w, s in now["rubrics"].items()) + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
