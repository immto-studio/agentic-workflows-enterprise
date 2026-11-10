"""The access filter holds for every question, every persona and every retriever; the exit format round-trips."""

from __future__ import annotations

import numpy as np
import pytest

from conftest import ON_CALL, member
from store import BM25, VectorStore, allowed, fuse

EVERYTHING = 10_000  # a k larger than the index, so a leak can't hide below the cut


def random_store(chunks, seed=8):
    rng = np.random.default_rng(seed)
    return VectorStore(chunks, rng.normal(size=(len(chunks), 64)))


@pytest.fixture(scope="module")
def bm25(fixed):
    return BM25(fixed)


def test_no_restricted_chunk_reaches_the_on_call_engineer(fixed, golden, restricted_docs, bm25):
    vectors = random_store(fixed)
    rng = np.random.default_rng(1)
    for q in golden:
        lexical = bm25.search(q["question"], EVERYTHING, ON_CALL)
        dense = vectors.search(rng.normal(size=64), EVERYTHING, ON_CALL)
        returned = {h.chunk.doc_id for h in lexical + dense}
        assert not returned & restricted_docs, q["id"]


def test_the_required_group_opens_its_document_and_no_other(fixed, golden, restricted_docs, bm25):
    for q in (q for q in golden if q["trap"] == "access"):
        returned = {h.chunk.doc_id for h in bm25.search(q["question"], EVERYTHING, member(q))}
        assert q["source_document"] in returned, q["id"]
        others = {d for d in restricted_docs if d != q["source_document"]}
        opened = {c.doc_id for c in fixed if c.doc_id in others and allowed(c, member(q), "Restricted")}
        assert returned & others <= opened, q["id"]  # only documents the same group opens


def test_the_manifests_class_cap_applies_before_ranking(fixed):
    everyone = frozenset({g for c in fixed for g in c.access_groups})
    store = random_store(fixed)
    hits = store.search(np.ones(64), EVERYTHING, everyone, max_class="Internal")
    assert hits and {h.chunk.classification for h in hits} <= {"Public", "Internal"}


def test_a_caller_with_no_matching_group_gets_nothing(fixed, bm25):
    assert bm25.search("vault unseal", EVERYTHING, {"lm-nobody"}) == []
    assert random_store(fixed).search(np.ones(64), EVERYTHING, {"lm-nobody"}) == []


def test_fusion_keeps_only_what_both_filters_passed(fixed, golden, restricted_docs, bm25):
    vectors = random_store(fixed)
    q = golden[0]
    fused = fuse([bm25.search(q["question"], 20, ON_CALL), vectors.search(np.ones(64), 20, ON_CALL)], 10)
    assert fused and not {h.chunk.doc_id for h in fused} & restricted_docs


def test_dump_and_load_round_trip(tmp_path, fixed):
    store = random_store(fixed)
    path = tmp_path / "index.jsonl"
    assert store.dump(path) == len(fixed)
    restored = VectorStore.load(path)
    query = np.random.default_rng(3).normal(size=64)
    before = [h.chunk.chunk_id for h in store.search(query, 10, ON_CALL)]
    after = [h.chunk.chunk_id for h in restored.search(query, 10, ON_CALL)]
    assert before == after
    assert restored.chunks == store.chunks
