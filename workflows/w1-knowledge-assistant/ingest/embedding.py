"""Embedding calls for W1: through the gateway for the index and the queries, direct to Ollama for model selection.

Every call the workflow makes goes through the model gateway with its workflow and data-class tags,
so the gateway's manifest check and grid apply to embeddings as they do to chat: the ingestion job
(`w1-ingest`) may call only the embedding alias, and a Restricted chunk may reach only a
self-hosted embedding model. `ollama_embed` skips the gateway and exists only for
`eval/embed_index.py`, which compares candidate models on a workstation, as chapter 9 measured
throughput against Ollama directly.

Each model expects its own prefixes on queries and documents, from its model card; without them
retrieval is measurably worse, so the table is part of the configuration. Checked on 2026-10-29:
Nomic's card for nomic-embed-text-v1.5 ("the text prompt must include a task instruction prefix"),
Google's EmbeddingGemma model card (the Retrieval query and document rows), and Qwen's card for
Qwen3-Embedding ("Instruct: {task_description}\nQuery:{query}", and no instruction for documents).

Every call asks Ollama not to truncate, so a chunk over the model's context is an error rather than
a shorter vector, and every vector's width is checked: Ollama answers a request for more dimensions
than the model has with the model's own width and a 200 (LINKS.md, chapter 10,
sections F.3 and F.4).
"""

from __future__ import annotations

import json
import urllib.request
import uuid

import numpy as np

# (query prefix, document prefix); "{title}" is the chunk's document title.
PREFIXES = {
    "nomic-embed-text": ("search_query: ", "search_document: "),
    "embeddinggemma": ("task: search result | query: ", "title: {title} | text: "),
    "qwen3-embedding": ("Instruct: Given an engineer's question, retrieve the wiki passage that answers it\nQuery:", ""),
}
SERVED_MODEL = "qwen3-embedding:0.6b"  # behind larkspur-embed in gateway/litellm.config.yaml
SERVED_DIMENSIONS = 1024
EMBED_ALIAS = "larkspur-embed"
BATCH = 32


def _checked(vectors: list[list[float]], expected: int | None) -> np.ndarray:
    widths = {len(v) for v in vectors}
    if len(widths) > 1 or (expected is not None and widths != {expected}):
        raise ValueError(f"embedding widths {sorted(widths)}, expected {expected or 'one width'}")
    return np.asarray(vectors, dtype=np.float32)


def prefixes(model: str = SERVED_MODEL) -> tuple[str, str]:
    return PREFIXES.get(model.split(":")[0], ("", ""))


def _post(url: str, body: dict, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.load(response)


def ollama_embed(texts: list[str], model: str, base: str = "http://127.0.0.1:11434") -> np.ndarray:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        body = {"model": model, "input": texts[start:start + BATCH], "truncate": False}
        vectors.extend(_post(f"{base}/api/embed", body, {})["embeddings"])
    return _checked(vectors, None)


class GatewayEmbedder:
    """Embeds through the model gateway as one workflow, one data class per call."""

    def __init__(self, base: str, key: str, workflow: str, alias: str = EMBED_ALIAS,
                 dimensions: int | None = SERVED_DIMENSIONS):
        self.base, self.key, self.workflow, self.alias = base.rstrip("/"), key, workflow, alias
        self.dimensions = dimensions

    def embed(self, texts: list[str], data_class: str, trace_id: str | None = None) -> np.ndarray:
        trace_id = trace_id or uuid.uuid4().hex
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            body = {"model": self.alias, "input": texts[start:start + BATCH], "truncate": False,
                    "metadata": {"tags": [f"workflow:{self.workflow}", f"data_class:{data_class.lower()}"],
                                 "trace_id": trace_id}}
            data = _post(f"{self.base}/v1/embeddings", body, {"Authorization": f"Bearer {self.key}"})["data"]
            vectors.extend(item["embedding"] for item in sorted(data, key=lambda item: item["index"]))
        return _checked(vectors, self.dimensions)
