"""Make the lab's modules importable from the tests, and keep the workflows' folders free of caches.

The lab folders are plain directories, not packages, so the tests add them to `sys.path` the way the
scripts do when run directly. A test that calls a workflow's code does it inside `registry.loaded`, as the
replay does, because three workflows name their scorer score.py.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
LAB = Path(__file__).resolve().parents[1]
for folder in (LAB / "layers", LAB / "cases", LAB, LAB / "judge", LAB / "labels"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import pytest  # noqa: E402

import registry  # noqa: E402


@pytest.fixture(scope="session")
def cases() -> dict[str, dict[str, dict]]:
    """The committed converted sets, by workflow and case id."""
    return {w: {c["id"]: c for c in registry.read_jsonl(registry.CASES / f"{w}.jsonl")} for w in registry.ORDER}


def kept(workflow: str, model: str, label: str) -> dict:
    """One kept run's outputs, by case id, as the replay reads them; a deep copy a test may change."""
    run = next(r for r in registry.kept_runs(workflow) if r.model == model and r.label == label)
    return copy.deepcopy(registry.outputs(run))
