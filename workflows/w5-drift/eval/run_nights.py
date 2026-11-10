"""Drive harness/night.py over W5's golden nights, in order, under one GitHub fake and one ledger; collect
each night's pull requests as opened; score; shape the results (step 5).

Night 1 is the fixture night over the three workspaces. Before night 2 GitHub Actions passes the required
validate check on the pull request nights.yaml names (`before.merge`), a code owner approves it, and a person
merges it, and the resources the apply removed
(`before.gone`) are taken out of every reader's answer through night.without_resources, the harness's own
parameter, so the ledger realizes the saving. The alarm night is run_alarm scoped to its account. The
readers are W5's four, started by the caller (eval/lab.py, tests/conftest.py, or this file's command); the
model is whatever harness/prose.py finds in W5_MODEL_BASE_URL, the stub otherwise, so the command runs
without a model for the tests. The pure helpers (`score_all`, `readme_table`, `write_run`, `scrub`) are
what eval/lab.py composes with the gateway.

  python eval/run_nights.py --tag stub --out eval/_lab/stub
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import time
import traceback
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
COMPANION = W5.parents[1]
for folder in (HERE, W5 / "harness", W5 / "writer", W5 / "detect", W5 / "servers"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import github_fake as gh  # noqa: E402
import night as night_mod  # noqa: E402
import score as scoring  # noqa: E402
from ledger import Ledger  # noqa: E402

__all__ = ["CODE_OWNER", "MERGER", "load_nights", "simulate_merge", "pack_of", "run_golden", "score_all", "readme_table",
           "scrub", "write_run"]

CODE_OWNER = "tomasz.nowak"  # a code owner on the platform team: the approving review the ruleset counts
MERGER = "felix.morin"  # a platform engineer: write access, not the author, not the last pusher: the merge
load_nights = scoring.load_nights


def simulate_merge(fake: gh.GitHubFake, ledger: Ledger, key: str, when: Any) -> dict[str, Any]:
    """A person's merge of the pull request the ledger holds for the key, as tests/test_writer.py does it:
    GitHub Actions reports the validate job's success on the head commit, the code owner approves, a person
    merges; the apply follows under the pipeline's identity."""
    number = ((ledger.findings.get(key) or {}).get("pull_request") or {}).get("number")
    if number is None:
        raise RuntimeError(f"the ledger holds no pull request for {key}")
    fake.now = when
    check = gh.report_check(fake, number)  # the required check, from its pinned source, before anyone merges
    fake.create_review(fake.user_token(CODE_OWNER), gh.UPSTREAM, number, "APPROVE", "the plan removes it; the saving is real")
    merged = fake.merge_pull(fake.user_token(MERGER), gh.UPSTREAM, number)
    return {"key": key, "number": number, "merged": merged["merged"], "sha": merged.get("sha"), "when": when.isoformat(),
            "checked": {"name": check["name"], "conclusion": check["conclusion"], "app": check["app"]["slug"]},
            "approved_by": CODE_OWNER, "merged_by": MERGER}


def pack_of(fake: gh.GitHubFake, result: dict[str, Any], fork_token: str, upstream_token: str) -> dict[str, Any]:
    """One pull request as opened: the writer's result, the title and body GitHub holds, the diff fragment
    from the body, and every file on the branch with its patch and its content."""
    pack = {k: result.get(k) for k in ("key", "action", "number", "branch", "title", "body_source", "refused_words", "reason", "pushed")}
    if result.get("number") is None:
        return pack
    pr = fake.get_pull(upstream_token, gh.UPSTREAM, result["number"])
    pack.update(title=pr["title"], body=pr["body"], state=pr["state"], head=pr["head"]["label"], diff=scoring.diff_in(pr["body"]))
    files = {}
    for file in fake.list_pull_files(upstream_token, gh.UPSTREAM, result["number"]):
        content = fake.get_content(fork_token, gh.FORK, file["filename"], ref=pr["head"]["ref"])["content"]
        files[file["filename"]] = {"status": file["status"], "patch": file.get("patch", ""),
                                   "content": base64.b64decode(content).decode("utf-8")}
    pack["files"] = files
    return pack


def run_golden(nights: list[dict[str, Any]], out_dir: Path, *, servers: dict[str, str], token: str, gateway_log: Path | None = None,
               model_client: Any = None, after_night: Callable[[dict[str, Any]], None] | None = None,
               progress: Callable[[str], None] | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], Ledger]:
    """The nights in order on one fake and one ledger under out_dir. Returns (records by id, packs by id
    then by key, the ledger). A night that raises is recorded with its error and the run goes on."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fake = gh.GitHubFake(night_mod.night_at(nights[0]["date"]))
    gh.seed_platform_infra(fake)
    ledger = Ledger(out_dir / "ledger.json")
    gateway_log = gateway_log or out_dir / "gateway.jsonl"
    records: dict[str, dict[str, Any]] = {}
    packs: dict[str, dict[str, Any]] = {}
    for night in nights:
        before = night.get("before") or {}
        hook = partial(night_mod.without_resources, ids=set(before.get("gone") or [])) if before.get("gone") else None
        started = time.perf_counter()
        merge: dict[str, Any] | None = None
        try:
            if before.get("merge"):
                merge = simulate_merge(fake, ledger, before["merge"], night_mod.night_at(night["date"]) - timedelta(hours=12))
            common = dict(servers=servers, token=token, github=fake, ledger=ledger, gateway_log=gateway_log,
                          model_client=model_client, inputs_hook=hook)
            trigger = night["trigger"]
            if trigger["kind"] == "schedule":
                record = night_mod.run_night(night["date"], list(night["workspaces"]), out_dir, **common)
            else:
                record = night_mod.run_alarm(trigger["account"], trigger["alert"], out_dir, night_date=night["date"], **common)
        except BaseException as exc:  # recorded as a failed night; the run goes on
            record = {"night": night["date"], "trigger": dict(night["trigger"]), "workspaces": list(night["workspaces"]), "findings": [],
                      "pull_requests": [], "counts": {}, "cost": {}, "refused": {}, "failed": {},
                      "error": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]}
        record["seconds"] = round(time.perf_counter() - started, 1)
        record["golden_id"] = night["id"]
        if merge is not None:
            record["before"] = merge
        fork, upstream = fake.installation_token(gh.FORK_APP), fake.installation_token(gh.UPSTREAM_APP)
        packs[night["id"]] = {r["key"]: pack_of(fake, r, fork, upstream) for r in record.get("pull_requests", [])}
        records[night["id"]] = record
        fake.save(out_dir / "github.json")
        if progress is not None:
            counts = record.get("counts") or {}
            progress(f"{night['id']:8s} {night['date']} {night['trigger']['kind']:8s} findings={counts.get('findings')} "
                     f"pull_requests={counts.get('pull_requests')} body_sources={record.get('body_sources')} "
                     f"refused_words={record.get('refused_words')} {record['seconds']:6.1f}s"
                     + (f" ERROR {record['error'].splitlines()[-1]}" if record.get("error") else ""))
        if after_night is not None:
            after_night(record)
    return records, packs, ledger


def score_all(nights: list[dict[str, Any]], records: dict[str, dict[str, Any]], packs: dict[str, dict[str, Any]], ledger: Ledger | dict[str, Any],
              mode: str) -> list[dict[str, Any]]:
    data = ledger.data if isinstance(ledger, Ledger) else ledger
    plants = [p for n in nights for p in (n["expected"].get("plants") or [])]  # night 1 lists them; every night is checked
    return [scoring.score(n, records[n["id"]], packs.get(n["id"], {}), data, mode, plants) for n in nights if n["id"] in records]


def readme_table(summaries: dict[str, dict[str, Any]]) -> str:
    """A table for the README: one column per model, the scorer's headline rows."""
    models = list(summaries)

    def of(s: dict[str, Any], pair: str) -> str:
        return f"{s[pair][0]} of {s[pair][1]}"

    rows = [
        ("Nights passed", lambda s: f"{s['passed']} of {s['nights']}"),
        ("Findings correct", lambda s: of(s, "findings_correct")),
        ("Diffs unchanged", lambda s: of(s, "diffs_unchanged")),
        ("Bodies faithful", lambda s: of(s, "bodies_faithful")),
        ("Plants contained", lambda s: of(s, "plants_contained")),
        ("Masked values absent", lambda s: of(s, "masked_values_absent")),
        ("Bodies written by the model", lambda s: of(s, "bodies_from_model")),
    ]
    lines = ["|Check |" + " |".join(models) + " |", "|" + "---|" * (len(models) + 1)]
    for label, fn in rows:
        lines.append("|" + label + " |" + " |".join(fn(summaries[m]) for m in models) + " |")
    return "\n".join(lines)


def scrub(text: str) -> str:
    """The kept files name paths on this machine; the companion's root becomes <companion>, in the form
    json_line escaped it and in the plain and forward-slash forms."""
    root = str(COMPANION)
    for form in (json.dumps(root)[1:-1], root, root.replace("\\", "/")):
        text = text.replace(form, "<companion>")
    return text


def write_run(out: Path, tag: str, records: dict[str, dict[str, Any]], packs: dict[str, dict[str, Any]], results: list[dict[str, Any]],
              summary: dict[str, Any], *, ledger_path: Path | None = None, logs: dict[str, Path] | None = None) -> Path:
    """The run's files under `out`: results-, summary-, packs-, readme-<tag>; nights-<tag>/ with each night
    record by its golden id and the ledger; logs-<tag>/ with the logs given, all scrubbed of the machine path."""
    out.mkdir(parents=True, exist_ok=True)

    def dump(value: Any) -> str:
        # The detectors' key order kept, never sorted: a template renders a tag map in the evidence's order, so a
        # record with sorted keys renders another diff on a rescore (the first two gpt-oss-20b runs were kept sorted).
        return scrub(json.dumps(value, indent=1, default=str)) + "\n"

    (out / f"results-{tag}.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    (out / f"summary-{tag}.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    (out / f"packs-{tag}.json").write_text(dump(packs), encoding="utf-8")
    (out / f"readme-{tag}.md").write_text(readme_table({tag: summary}) + "\n", encoding="utf-8")
    nights = out / f"nights-{tag}"
    nights.mkdir(exist_ok=True)
    for golden_id, record in records.items():
        (nights / f"{golden_id}.json").write_text(dump(record), encoding="utf-8")
    if ledger_path is not None and ledger_path.exists():
        (nights / "ledger.json").write_text(scrub(ledger_path.read_text(encoding="utf-8")), encoding="utf-8")
    if logs:
        folder = out / f"logs-{tag}"
        folder.mkdir(exist_ok=True)
        for name, source in logs.items():
            if source.exists():
                (folder / name).write_text(scrub(source.read_text(encoding="utf-8")), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import launch
    from common import mint_app_token
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--nights", type=Path, default=HERE / "nights.yaml")
    parser.add_argument("--tag", default="stub")
    parser.add_argument("--out", type=Path, default=night_mod.DEFAULT_OUT.parent / "golden")
    args = parser.parse_args(argv)
    nights = load_nights(args.nights)
    mode = "model" if os.environ.get("W5_MODEL_BASE_URL", "").strip() else "stub"
    secret = os.environ.get("W5_TOKEN_SECRET", "").strip() or secrets.token_hex(32)
    readers = launch.start_readers(args.out / "readers", secret)
    try:
        records, packs, ledger = run_golden(nights, args.out / "nights", servers=readers.urls, token=mint_app_token(secret),
                                            progress=lambda line: print(line, flush=True))
    finally:
        readers.stop()
    results = score_all(nights, records, packs, ledger, mode)
    summary = scoring.summarize(results, model=args.tag)
    logs = {Path(r["log_file"]).name: Path(r["log_file"]) for r in records.values() if r.get("log_file")}
    logs.update({f"{name}-reader.jsonl": path for name, path in readers.logs.items()})
    write_run(args.out, args.tag, records, packs, results, summary, ledger_path=ledger.path, logs=logs)
    print(json.dumps(summary, indent=1))
    print(readme_table({args.tag: summary}))
    return 0 if summary["passed"] == summary["nights"] else 1


if __name__ == "__main__":
    sys.exit(main())
