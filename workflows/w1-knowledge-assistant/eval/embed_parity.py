"""Does another Ollama embed W1's golden questions as the one that built the index did?

The index (index/qwen3-embedding-0.6b/fixed.npz) stores the twenty golden questions' vectors from the
Ollama it was built on, 0.22.1 on 29 October 2026. This embeds the same questions, with the same query
prefix, on the Ollama at --ollama and compares them by cosine, and compares the top five chunks each
retrieves from the stored chunk vectors. gemma4:12b needs the portable Ollama 0.40.13, which serves the
embedding model too in its run, so the check says whether that run's retrieval is the first run's.

  python eval/embed_parity.py [--ollama http://127.0.0.1:11435]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import yaml

W1 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(W1 / "ingest"))
from embedding import SERVED_MODEL, prefixes  # noqa: E402


def unit(m: np.ndarray) -> np.ndarray:
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ollama", default="http://127.0.0.1:11435")
    base = parser.parse_args(argv).ollama.rstrip("/")

    query_prefix, _ = prefixes(SERVED_MODEL)
    data = np.load(W1 / "index" / "qwen3-embedding-0.6b" / "fixed.npz", allow_pickle=True)
    ids = [str(x) for x in data["question_ids"]]
    stored, chunks, chunk_ids = data["questions"], data["vectors"], [str(x) for x in data["chunk_ids"]]
    golden = {q["id"]: q for q in yaml.safe_load((W1 / "corpus" / "golden-questions.yaml").read_text(encoding="utf-8"))}
    texts = [query_prefix + golden[i]["question"] for i in ids]

    request = urllib.request.Request(base + "/api/embed", data=json.dumps({"model": SERVED_MODEL, "input": texts}).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        now = np.array(json.load(response)["embeddings"], dtype=np.float32)
    with urllib.request.urlopen(base + "/api/version", timeout=10) as response:
        version = json.load(response)["version"]

    cosine = (unit(stored) * unit(now)).sum(axis=1)
    top_stored = np.argsort(-unit(stored) @ unit(chunks).T, axis=1)[:, :5]
    top_now = np.argsort(-unit(now) @ unit(chunks).T, axis=1)[:, :5]
    same_top1 = sum(int(a[0] == b[0]) for a, b in zip(top_stored, top_now))
    same_top5 = sum(int(list(a) == list(b)) for a, b in zip(top_stored, top_now))
    print(f"ollama {version}: {len(ids)} questions; cosine to the stored vectors min {cosine.min():.6f}, "
          f"median {np.median(cosine):.6f}; same top chunk {same_top1}/{len(ids)}; "
          f"same top five in order {same_top5}/{len(ids)}")
    for i, (a, b) in enumerate(zip(top_stored, top_now)):
        if list(a) != list(b):
            print(f"  {ids[i]}: {[chunk_ids[x] for x in a]} -> {[chunk_ids[x] for x in b]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
