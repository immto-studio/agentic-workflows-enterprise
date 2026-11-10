"""The pull-request job (E-D9): its replay step, its rubric-hash step, and the workflow file itself. Each step is run
on the committed files, where it passes, and on a copy changed by hand, where it names what changed."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "ci"))

import actionlint  # noqa: E402
import judge_hashes  # noqa: E402
import measure  # noqa: E402
import registry  # noqa: E402
import replay_check  # noqa: E402

import judge as judging  # noqa: E402

WORKFLOW = LAB / "ci" / "regression.yml"


# --- the replay ---------------------------------------------------------------------------------------------------------

def test_the_replay_matches_the_committed_results_check_by_check() -> None:
    assert replay_check.check() == []


def test_a_check_that_moved_is_named_by_file_run_case_and_check(tmp_path: Path) -> None:
    committed = replay_check.latest_results()
    for path in committed.glob("replay-*"):
        shutil.copyfile(path, tmp_path / path.name)
    edited = registry.read_json(tmp_path / "replay-w2-gpt-oss-20b.json")
    run = next(r for r in edited["runs"] if r["run"] == "2026-11-02")
    case = next(c for c in run["cases"] if c["id"] == "w2-07")
    case["trajectory"]["checks"]["order"]["ok"] = False
    measure.write_json(tmp_path / "replay-w2-gpt-oss-20b.json", edited)
    (tmp_path / "replay-w9-gpt-oss-20b.json").write_text("{}", encoding="utf-8")
    problems = replay_check.check(tmp_path)
    assert problems == [
        "replay-w9-gpt-oss-20b.json: committed and no longer written by the replay",
        "replay-w2-gpt-oss-20b.json runs[2026-11-02].cases[w2-07].trajectory.checks.order.ok: committed False, now True",
    ]


# --- the rubrics' and the prompt's hashes -------------------------------------------------------------------------

def test_every_current_judge_result_was_made_with_the_rubrics_as_they_are() -> None:
    assert judge_hashes.check() == []


def test_a_rubric_changed_without_the_judge_running_again_fails(tmp_path: Path) -> None:
    rubrics = tmp_path / "rubrics"
    shutil.copytree(judging.RUBRICS, rubrics)
    with (rubrics / "w2.yaml").open("a", encoding="utf-8") as f:
        f.write("# a comment is a change: the judge read the file as it was\n")
    problems = judge_hashes.check(rubrics=rubrics)
    named = sorted(p.split(":")[0] for p in problems)
    results = registry.rel(replay_check.latest_results())
    assert named == sorted([f"{results}/judge-w2-gemma4-12b.json", f"{results}/judge-w2-gpt-oss-20b.json",
                            f"{results}/redteam-w2-gemma4-12b.json (gpt-oss-20b)",
                            f"{results}/redteam-w2-gpt-oss-20b.json (gemma4-12b)", "labs/ch15/baseline/baseline.json"])
    assert all(" w2 judged with judge/rubrics/w2.yaml " in p for p in problems)
    assert "python judge/run_judge.py --judge gemma4-12b --workflows w2" in "\n".join(problems)


def test_a_changed_prompt_fails_every_result(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text(judging.PROMPT.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    problems = judge_hashes.check(prompt=prompt)
    results = replay_check.latest_results()
    # Step 3's ten files, step 6's ten (one judge each), and the baseline; no live run is committed yet.
    files = len(list(results.glob("judge-w*-*.json"))) + len(list(results.glob("redteam-w*-*.json"))) + 1
    assert files == 21 and len(problems) == files and all("judge/prompt.txt" in p for p in problems)


# --- the workflow file --------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_job_runs_on_every_pull_request_with_read_only_permissions(workflow) -> None:
    triggers = workflow[True]  # YAML 1.1 reads the key `on` as true
    assert "pull_request" in triggers and "paths" not in (triggers["pull_request"] or {})
    assert workflow["permissions"] == {"contents": "read"}
    (job,) = workflow["jobs"].values()
    assert job["runs-on"] == "ubuntu-24.04" and job["defaults"]["run"]["working-directory"] == "labs/ch15"


def test_every_action_is_pinned_to_a_commit(workflow) -> None:
    (job,) = workflow["jobs"].values()
    uses = [s["uses"] for s in job["steps"] if "uses" in s]
    assert uses and all(re.fullmatch(r"[\w-]+/[\w-]+@[0-9a-f]{40}", u) for u in uses)


def test_the_job_runs_the_five_checks_the_plan_names(workflow) -> None:
    """E-D9: the tests, the conversion check, the replay, the rubric hashes, and the gate, each once the
    environment is in, so a pull request sees every check that fails."""
    (job,) = workflow["jobs"].values()
    runs = {s["run"]: s for s in job["steps"] if "run" in s}
    checks = ["python -m pytest tests -q", "python cases/convert.py --check", "python ci/replay_check.py",
              "python ci/judge_hashes.py", "python ci/gate.py"]
    assert [r for r in runs if r in checks] == checks
    for command in checks:
        assert runs[command]["if"] == "${{ !cancelled() && steps.environment.outcome == 'success' }}"
        script = command.split()[1]
        assert script == "-m" or (LAB / script).is_file(), script
    assert "python -m pip install -r ../ch05/requirements.txt" in runs


def test_the_header_says_how_to_turn_it_on_with_one_copy() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "cp labs/ch15/ci/regression.yml .github/workflows/regression.yml" in text


def test_actionlint_is_pinned_to_its_releases_digests() -> None:
    assert actionlint.VERSION == "1.7.12"
    for name, digest in actionlint.ASSETS.values():
        assert name.startswith(f"actionlint_{actionlint.VERSION}_") and re.fullmatch(r"[0-9a-f]{64}", digest)


@pytest.mark.skipif(not (actionlint.BIN).is_dir(), reason="the pinned actionlint is not fetched (python ci/actionlint.py)")
def test_the_workflow_passes_the_pinned_actionlint() -> None:
    exe = actionlint.verified()
    done = actionlint.lint(exe)
    assert done.returncode == 0, done.stdout + done.stderr


def test_nothing_here_reads_a_secrets_folder() -> None:
    for path in (LAB / "ci").glob("*.py"):
        assert "secrets/" not in path.read_text(encoding="utf-8").replace("\\", "/"), path.name
    assert json.dumps(registry.read_yaml(WORKFLOW)).count("secrets.") == 0
