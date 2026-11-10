"""Build W1's serving index through the gateway, as the ingestion job, one class at a time.

Chapter 10. The ingestion job embeds every chunk under its own manifest (`w1-ingest`, the embedding
alias and nothing else), and each call carries the class of the chunks in it, so the gateway's grid
decides where Restricted text may be embedded. The golden questions are embedded the way the
assistant embeds a question: as `w1-knowledge`, with the model's query prefix, as Internal text.

The output is the index the knowledge server loads and the retrieval tests pin:
index/qwen3-embedding-0.6b/fixed.npz. A page the ingestion gate refuses stays out of it and goes
into refusals.json beside it, with its owner team and the reason, which is what the pipeline sends
the owners; the other pages are indexed all the same.

Run, with W1's gateway up (gateway/litellm.config.yaml):
  GATEWAY_URL=http://127.0.0.1:4012 GATEWAY_KEY=<the local key> python build_index.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
W1 = HERE.parent
sys.path.insert(0, str(HERE))
import ingest  # noqa: E402
from embedding import SERVED_MODEL, GatewayEmbedder, prefixes  # noqa: E402

OUT = W1 / "index" / "qwen3-embedding-0.6b" / "fixed.npz"
REFUSALS = OUT.parent / "refusals.json"


def main() -> int:
    base = os.environ.get("GATEWAY_URL", "http://127.0.0.1:4012")
    key = os.environ["GATEWAY_KEY"]
    chunks, refusals = ingest.ingest(variant="fixed")
    report = ingest.refusals_report(refusals)
    for row in report:
        print(f"refused {row['page']} (owner {row['owner_team']}): {row['reason']}", file=sys.stderr)
    REFUSALS.parent.mkdir(parents=True, exist_ok=True)
    REFUSALS.write_text(json.dumps({"built": time.strftime("%Y-%m-%d"), "refused": report}, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    trace_id = uuid.uuid4().hex
    query_prefix, doc_prefix = prefixes(SERVED_MODEL)
    job = GatewayEmbedder(base, key, "w1-ingest")
    by_class: dict[str, list[int]] = defaultdict(list)
    for i, chunk in enumerate(chunks):
        by_class[chunk.classification].append(i)
    vectors: np.ndarray | None = None
    for data_class, indices in sorted(by_class.items()):
        batch = job.embed([doc_prefix.format(title=chunks[i].title) + chunks[i].text for i in indices], data_class, trace_id)
        if vectors is None:
            vectors = np.zeros((len(chunks), batch.shape[1]), dtype=np.float32)
        vectors[indices] = batch
        print(f"{data_class}: {len(indices)} chunks")
    golden = yaml.safe_load((W1 / "corpus" / "golden-questions.yaml").read_text(encoding="utf-8"))
    assistant = GatewayEmbedder(base, key, "w1-knowledge")
    questions = assistant.embed([query_prefix + q["question"] for q in golden], "internal", trace_id)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, model=SERVED_MODEL, chunk_ids=[c.chunk_id for c in chunks], vectors=vectors,
                        question_ids=[q["id"] for q in golden], questions=questions)
    print(f"wrote {OUT.relative_to(W1)}: {len(chunks)} chunks, {vectors.shape[1]} dimensions; trace {trace_id}")
    print(f"wrote {REFUSALS.relative_to(W1)}: {len(report)} pages refused")
    return 0


if __name__ == "__main__":
    sys.exit(main())
