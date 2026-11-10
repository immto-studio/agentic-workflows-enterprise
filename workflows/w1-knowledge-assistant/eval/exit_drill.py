"""Chapter 3's exit drill for W1's index: dump it, restore it into another kind of store, rerun the golden set.

Chapter 10 (W1-D11). The NumPy store dumps itself as JSON lines; SqliteVecStore restores the dump
into a sqlite-vec table; both answer every golden question for its permitted persona, and the on-call
engineer's every question with k as large as the store allows. The drill passes when the restored
store returns the same five pages for every question and nothing restricted to the wrong person.

Chapter 3 has the workflow's manifest state the tolerance. Chapter 5's manifest schema has no field
for it yet, so the drill uses none: identical results, and no leak.

Run: python exit_drill.py [--json results/<date>/exit-drill.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import yaml

W1 = Path(__file__).resolve().parents[1]
for folder in ("ingest", "store"):
    sys.path.insert(0, str(W1 / folder))
import ingest  # noqa: E402
from sqlite_store import MAX_K, SqliteVecStore  # noqa: E402
from store import VectorStore  # noqa: E402

INDEX = W1 / "index" / "qwen3-embedding-0.6b" / "fixed.npz"
ON_CALL = frozenset({"lm-all-staff", "lm-eng-all", "lm-platform-oncall"})


def drill() -> dict:
    golden = yaml.safe_load((W1 / "corpus" / "golden-questions.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((W1 / "corpus" / "manifest.yaml").read_text(encoding="utf-8"))
    restricted = set(manifest["traps"]["access"])
    chunks, _ = ingest.ingest(variant="fixed")
    data = np.load(INDEX, allow_pickle=False)
    first = VectorStore(chunks, data["vectors"])
    queries = {str(i): v for i, v in zip(data["question_ids"], data["questions"])}
    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / "index.jsonl"
        started = time.perf_counter()
        dumped = first.dump(dump)
        second = SqliteVecStore.restore(dump)
        restore_s = round(time.perf_counter() - started, 2)
    same, hits_first, hits_second, leaks, differing = 0, 0, 0, 0, []
    for q in golden:
        persona = ON_CALL | {q["required_access_group"]} if q["trap"] == "access" else ON_CALL
        a = [h.chunk.doc_id for h in first.search(queries[q["id"]], 5, persona)]
        b = [h.chunk.doc_id for h in second.search(queries[q["id"]], 5, persona)]
        same += a == b
        if a != b:
            differing.append(q["id"])
        hits_first += q["source_document"] in a
        hits_second += q["source_document"] in b
        everything = {h.chunk.doc_id for h in second.search(queries[q["id"]], MAX_K, ON_CALL)}
        leaks += bool(everything & restricted)
    return {"chunks_dumped": dumped, "dump_and_restore_s": restore_s, "questions": len(golden),
            "same_top_five": same, "differing": differing, "hit_at_5_numpy": hits_first,
            "hit_at_5_sqlite_vec": hits_second, "leaks": leaks,
            "passed": same == len(golden) and leaks == 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    result = drill()
    print(json.dumps(result))
    if args.json:
        import sqlite3

        import sqlite_vec
        db = sqlite3.connect(":memory:")
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        meta = {"measured": time.strftime("%Y-%m-%d"), "sqlite": sqlite3.sqlite_version,
                "sqlite_vec": db.execute("select vec_version()").fetchone()[0], "index": INDEX.relative_to(W1).as_posix()}
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"meta": meta, **result}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
