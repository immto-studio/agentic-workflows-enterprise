"""The exit drill: the index restored into sqlite-vec answers as the original does, and leaks nothing."""

from __future__ import annotations

import importlib.util
import sys

import numpy as np
import pytest

from conftest import ON_CALL, W1

pytest.importorskip("sqlite_vec")

from sqlite_store import SqliteVecStore  # noqa: E402
from store import VectorStore  # noqa: E402

_spec = importlib.util.spec_from_file_location("w1_exit_drill", W1 / "eval" / "exit_drill.py")
exit_drill = importlib.util.module_from_spec(_spec)
sys.modules["w1_exit_drill"] = exit_drill
_spec.loader.exec_module(exit_drill)


def test_the_drill_passes():
    result = exit_drill.drill()
    assert result["passed"], result
    assert result["hit_at_5_sqlite_vec"] == result["hit_at_5_numpy"] == result["questions"]


def test_the_restored_store_filters_before_it_ranks(tmp_path, fixed):
    rng = np.random.default_rng(8)
    first = VectorStore(fixed, rng.normal(size=(len(fixed), 16)))
    dump = tmp_path / "index.jsonl"
    first.dump(dump)
    second = SqliteVecStore.restore(dump)
    query = rng.normal(size=16)
    for k in (1, 5, 50):
        assert [h.chunk.chunk_id for h in second.search(query, k, ON_CALL)] == \
            [h.chunk.chunk_id for h in first.search(query, k, ON_CALL)]
    assert second.search(query, 5, {"lm-nobody"}) == []
    capped = second.search(query, 4096, {g for c in fixed for g in c.access_groups}, max_class="Internal")
    assert capped and {h.chunk.classification for h in capped} <= {"Public", "Internal"}
