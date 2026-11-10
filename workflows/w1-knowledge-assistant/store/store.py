"""The W1 index: a store that filters before it ranks.

Chapter 10. The access filter is the hard part of a knowledge assistant, and the rule this module
keeps is that a chunk the caller can't read is never a candidate: the filter runs first and the
ranking sees only what passed it, as a metadata filter does inside the Knowledge Base's query.
Filtering after ranking, or after generation, is how a retriever leaks.

`allowed()` is the filter, and both retrievers use it:

- `VectorStore` ranks by cosine similarity over normalized vectors. It is NumPy brute force, which
  is what an index of a few hundred chunks needs; S3 Vectors does the same job behind `Retrieve`.
- `BM25` ranks by words. It needs no model, so the access tests run with nothing else installed,
  and the chapter measures it against the vectors and in a hybrid with them.

A caller may read a chunk when the chunk's access_groups share at least one group with the
caller's, and the chunk's class is no higher than the workflow's manifest allows. The caller's
groups come from the knowledge server, which takes them from the delegated identity; nothing in a
query or a tool argument can widen them.

`dump()` and `load()` write and read the index as JSON lines, one chunk with its vector a line:
the format the exit drill of chapter 3 restores into a store of another kind.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ingest"))
from ingest import CLASSES, Chunk  # noqa: E402

RANK = {name: i for i, name in enumerate(CLASSES)}


def allowed(chunk: Chunk, groups: frozenset[str], max_class: str) -> bool:
    """The access filter: a shared group, and a class the workflow may handle."""
    return bool(groups.intersection(chunk.access_groups)) and RANK[chunk.classification] <= RANK[max_class]


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


class VectorStore:
    """Chunks and their embeddings; `search` filters, then ranks by cosine similarity."""

    def __init__(self, chunks: Sequence[Chunk], vectors: np.ndarray):
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        self.chunks = list(chunks)
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self.vectors = matrix / np.where(norms == 0, 1, norms)

    def groups(self) -> frozenset[str]:
        """Every group some chunk names: the only groups a filter ever needs to carry."""
        return frozenset(g for chunk in self.chunks for g in chunk.access_groups)

    def search(self, query: np.ndarray, k: int, groups: Iterable[str], max_class: str = "Restricted") -> list[Hit]:
        caller = frozenset(groups)
        candidates = [i for i, chunk in enumerate(self.chunks) if allowed(chunk, caller, max_class)]
        if not candidates or k <= 0:
            return []
        q = np.asarray(query, dtype=np.float32)
        q = q / (np.linalg.norm(q) or 1)
        scores = self.vectors[candidates] @ q
        order = np.argsort(-scores, kind="stable")[:k]
        return [Hit(self.chunks[candidates[i]], float(scores[i])) for i in order]

    def dump(self, path: Path) -> int:
        """The index as JSON lines, each chunk with its metadata, text and vector."""
        with path.open("w", encoding="utf-8", newline="\n") as out:
            for chunk, vector in zip(self.chunks, self.vectors):
                out.write(json.dumps({**chunk.metadata(), "text": chunk.text,
                                      "vector": [round(float(x), 6) for x in vector]}) + "\n")
        return len(self.chunks)

    @classmethod
    def load(cls, path: Path) -> "VectorStore":
        chunks, vectors = [], []
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            vectors.append(row.pop("vector"))
            row["access_groups"] = tuple(row["access_groups"])
            chunks.append(Chunk(**row))
        return cls(chunks, np.asarray(vectors, dtype=np.float32))


TOKEN = re.compile(r"[a-z0-9][a-z0-9_.-]*[a-z0-9]|[a-z0-9]")


def words(text: str) -> list[str]:
    """Lowercased terms; identifiers such as fnol-intake-worker and lm-dbctl stay whole."""
    return TOKEN.findall(text.lower())


class BM25:
    """Okapi BM25 over the chunks' text, with the same filter as the vectors."""

    def __init__(self, chunks: Sequence[Chunk], k1: float = 1.2, b: float = 0.75):
        self.chunks = list(chunks)
        self.k1, self.b = k1, b
        self.terms = [Counter(words(f"{c.title}\n{c.text}")) for c in self.chunks]
        self.lengths = [sum(t.values()) for t in self.terms]
        self.avg = sum(self.lengths) / max(len(self.lengths), 1)
        df = Counter(term for t in self.terms for term in t)
        n = len(self.chunks)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    def score(self, i: int, query: list[str]) -> float:
        tf, length = self.terms[i], self.lengths[i]
        total = 0.0
        for term in query:
            if term in tf:
                f = tf[term]
                total += self.idf[term] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg))
        return total

    def search(self, query: str, k: int, groups: Iterable[str], max_class: str = "Restricted") -> list[Hit]:
        caller = frozenset(groups)
        q = words(query)
        scored = [(self.score(i, q), i) for i, chunk in enumerate(self.chunks) if allowed(chunk, caller, max_class)]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [Hit(self.chunks[i], s) for s, i in scored[:k] if s > 0]


def fuse(rankings: Sequence[Sequence[Hit]], k: int, c: int = 60) -> list[Hit]:
    """Reciprocal rank fusion of several filtered rankings; the inputs are already filtered."""
    scores: dict[str, float] = {}
    best: dict[str, Chunk] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking):
            scores[hit.chunk.chunk_id] = scores.get(hit.chunk.chunk_id, 0.0) + 1 / (c + rank + 1)
            best[hit.chunk.chunk_id] = hit.chunk
    order = sorted(scores, key=lambda cid: (-scores[cid], cid))[:k]
    return [Hit(best[cid], scores[cid]) for cid in order]
