"""Embed W1's chunks and golden questions with one candidate model, for the retrieval comparison.

Chapter 10. The lab picks its embedding model by measurement: this script writes, for one model,
`<out>/<variant>.npz` with every chunk's vector and every golden question's, and
`retrieval_eval.py --vectors <out>` scores them. It calls Ollama directly (ingest/embedding.py
says why); the index the assistant serves is built through the gateway by ingest/build_index.py.

Run: python embed_index.py --model nomic-embed-text --out <scratch folder>/nomic-embed-text
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import yaml

W1 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(W1 / "ingest"))
import ingest  # noqa: E402
from embedding import ollama_embed, prefixes  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base", default="http://127.0.0.1:11434")
    args = parser.parse_args(argv)
    golden = yaml.safe_load((W1 / "corpus" / "golden-questions.yaml").read_text(encoding="utf-8"))
    query_prefix, doc_prefix = prefixes(args.model)
    questions = ollama_embed([query_prefix + q["question"] for q in golden], args.model, args.base)
    args.out.mkdir(parents=True, exist_ok=True)
    for variant in ("fixed", "heading"):
        chunks, _ = ingest.ingest(variant=variant)
        vectors = ollama_embed([doc_prefix.format(title=c.title) + c.text for c in chunks], args.model, args.base)
        np.savez_compressed(args.out / f"{variant}.npz", model=args.model, chunk_ids=[c.chunk_id for c in chunks],
                            vectors=vectors, question_ids=[q["id"] for q in golden], questions=questions)
        print(f"{args.model} {variant}: {len(chunks)} chunks, {vectors.shape[1]} dimensions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
