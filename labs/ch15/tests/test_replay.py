"""The replay over every kept run: the same bytes from two runs, the committed results reproduced, and the
differences the README lists, no more and no fewer."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import registry
import run_replay

LAB = Path(__file__).resolve().parents[1]
RUNS = {"skeleton": 2, "w1": 3, "w2": 5, "w3": 1, "w4": 4, "w5": 11}
# The differences the README lists: the trajectory layer fails these outputs, which the scorer passes or
# doesn't judge on its calls. W2's run 1 read what the cases don't name; W3 read logs before other reads.
TRAJECTORY_DIFFERENCES = {
    ("w2", "gpt-oss-20b", "2026-11-02 run1"): {"w2-01", "w2-04", "w2-05", "w2-08", "w2-09", "w2-16", "w2-18"},
    ("w2", "gpt-oss-20b", "2026-11-02 run3"): {"w2-04"},
    ("w3", "gpt-oss-20b", "2026-11-02"): {"w3-01", "w3-13", "w3-14"},
}


@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[dict]]:
    out = tmp_path_factory.mktemp("replay")
    return out, run_replay.replay(out)


def documents(folder: Path) -> list[dict]:
    return [registry.read_json(p) for p in sorted(folder.glob("replay-*.json"))]


def test_every_kept_run_is_replayed(replayed) -> None:
    _, table = replayed
    for workflow, count in RUNS.items():
        assert len([r for r in table if r["workflow"] == workflow]) == count == len(registry.kept_runs(workflow))


def test_the_deterministic_layer_agrees_with_every_scorer_and_no_stored_verdict_is_stale(replayed) -> None:
    out, _ = replayed
    for document in documents(out):
        for run in document["runs"]:
            for case in run["cases"]:
                layers = {d["layer"] for d in case["differences"]}
                assert "deterministic" not in layers and "stored" not in layers, (document["workflow"], case["id"])


def test_the_trajectory_differences_are_the_ones_the_readme_lists(replayed) -> None:
    out, _ = replayed
    found = {}
    for document in documents(out):
        for run in document["runs"]:
            ids = {c["id"] for c in run["cases"] if any(d["layer"] == "trajectory" for d in c["differences"])}
            if ids:
                found[(document["workflow"], document["model"], run["run"])] = ids
    assert found == TRAJECTORY_DIFFERENCES


def test_the_committed_results_are_what_the_replay_writes(replayed) -> None:
    """The replay's own files; the judge's (judge-*) sit beside them and have their own test."""
    out, _ = replayed
    committed = sorted(p for p in (LAB / "results").iterdir() if p.is_dir())[-1]
    names = sorted(p.name for p in out.iterdir())
    assert names == sorted(p.name for p in committed.iterdir() if p.name.startswith("replay-"))
    for name in names:
        fresh = (out / name).read_text(encoding="utf-8")
        assert fresh == (committed / name).read_text(encoding="utf-8").replace("\r\n", "\n"), name


def test_two_replays_write_the_same_bytes(tmp_path: Path) -> None:
    """Two processes, each with its own hash seed, so no set's iteration order reaches a file."""
    outs = []
    for seed in ("1", "2"):
        out = tmp_path / f"run-{seed}"
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, str(LAB / "run_replay.py"), "--out", str(out)], check=True, env=env,
                       capture_output=True, cwd=str(LAB))
        outs.append(out)
    first, second = outs
    names = sorted(p.name for p in first.iterdir())
    assert names == sorted(p.name for p in second.iterdir()) and "replay-summary.md" in names
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
