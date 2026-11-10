"""Retrieval with the lab's real vectors: what the chapter reports, pinned so a change in chunking shows.

The vectors are qwen3-embedding:0.6b's (Ollama 0.22.1, 2026-10-29), written by
`eval/embed_index.py` for the fixed chunks and the golden questions. They are committed so this
test needs no model. If the chunking changes, the chunk IDs stop matching and the test says so:
rerun embed_index.py with Ollama running, then this test.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from conftest import ON_CALL, member
from store import VectorStore

INDEX = Path(__file__).resolve().parents[1] / "index" / "qwen3-embedding-0.6b" / "fixed.npz"


@pytest.fixture(scope="module")
def dense(fixed):
    data = np.load(INDEX, allow_pickle=False)
    ids = [str(i) for i in data["chunk_ids"]]
    assert ids == [c.chunk_id for c in fixed], (
        f"{INDEX.name} no longer matches the chunks; rerun eval/embed_index.py --model qwen3-embedding:0.6b "
        f"--out index/qwen3-embedding-0.6b")
    queries = {str(q): v for q, v in zip(data["question_ids"], data["questions"])}
    return VectorStore(fixed, data["vectors"]), queries


def test_dense_retrieval_finds_every_source_in_the_top_five(dense, golden):
    store, queries = dense
    for q in golden:
        groups = member(q) if q["trap"] == "access" else ON_CALL
        returned = [h.chunk.doc_id for h in store.search(queries[q["id"]], 5, groups)]
        assert q["source_document"] in returned, q["id"]


def test_real_vectors_leak_nothing_either(dense, golden, restricted_docs):
    store, queries = dense
    for q in golden:
        returned = {h.chunk.doc_id for h in store.search(queries[q["id"]], 10_000, ON_CALL)}
        assert not returned & restricted_docs, q["id"]
