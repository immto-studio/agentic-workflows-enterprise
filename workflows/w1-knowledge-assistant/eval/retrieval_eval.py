"""Retrieval on the golden set, with no model in the loop: does the right document come back, for the right person?

Chapter 10. For each golden question the permitted persona is the on-call engineer, plus the
question's group for the five access questions. The script reports, per retriever and per chunking
variant, how often the source document is in the top k (hit@k), and, for the five stale pairs,
whether the current document ranks above the stale one when both come back. The access property
itself, that a restricted chunk never comes back to the wrong person, is a test, not a score
(tests/test_store.py).

The dense and hybrid rows need vectors, which `embed_index.py` writes; without them only BM25 runs.

Run: python retrieval_eval.py [--k 5] [--vectors ../index/qwen3-embedding-0.6b]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import yaml

W1 = Path(__file__).resolve().parents[1]
for folder in ("ingest", "store"):
    sys.path.insert(0, str(W1 / folder))

import ingest  # noqa: E402
from store import BM25, VectorStore, fuse  # noqa: E402

ON_CALL = frozenset({"lm-all-staff", "lm-eng-all", "lm-platform-oncall"})


def persona(q: dict) -> frozenset[str]:
    return ON_CALL | {q["required_access_group"]} if q["trap"] == "access" else ON_CALL


def rank_of(doc: str, hits) -> int | None:
    for i, hit in enumerate(hits):
        if hit.chunk.doc_id == doc:
            return i
    return None


def score(name: str, search, golden: list[dict], k: int) -> dict:
    hit, stale_ok, stale_total, misses = 0, 0, 0, []
    for q in golden:
        hits = search(q, max(k, 20))
        r = rank_of(q["source_document"], hits)
        if r is not None and r < k:
            hit += 1
        else:
            misses.append(q["id"])
        if q["trap"] == "stale":
            stale_total += 1
            s = rank_of(q["stale_document"], hits)
            if r is not None and (s is None or r < s):
                stale_ok += 1
    return {"retriever": name, "hit_at_k": hit, "questions": len(golden), "k": k,
            "current_above_stale": stale_ok, "stale_pairs": stale_total, "misses": misses}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--vectors", type=Path, default=W1 / "index" / "qwen3-embedding-0.6b")
    args = parser.parse_args(argv)
    golden = yaml.safe_load((W1 / "corpus" / "golden-questions.yaml").read_text(encoding="utf-8"))
    rows = []
    for variant in ("fixed", "heading"):
        chunks, _ = ingest.ingest(variant=variant)
        bm25 = BM25(chunks)
        rows.append({"variant": variant, **score("bm25", lambda q, n: bm25.search(q["question"], n, persona(q)), golden, args.k)})
        index = args.vectors / f"{variant}.npz"
        if index.exists():
            data = np.load(index, allow_pickle=False)
            if list(data["chunk_ids"]) != [c.chunk_id for c in chunks]:
                print(f"{index} is stale for the {variant} chunks; rerun embed_index.py", file=sys.stderr)
                continue
            store = VectorStore(chunks, data["vectors"])
            queries = dict(zip(data["question_ids"], data["questions"]))
            dense = lambda q, n: store.search(queries[q["id"]], n, persona(q))  # noqa: E731
            hybrid = lambda q, n: fuse([dense(q, n), bm25.search(q["question"], n, persona(q))], n)  # noqa: E731
            rows.append({"variant": variant, "model": str(data["model"]), **score("dense", dense, golden, args.k)})
            rows.append({"variant": variant, "model": str(data["model"]), **score("hybrid", hybrid, golden, args.k)})
    for row in rows:
        print(json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
