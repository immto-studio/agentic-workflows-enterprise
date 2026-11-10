"""A fake model for the live job's tests: one server on 127.0.0.1 that answers as three things.

  the gateway   POST /v1/chat/completions and /v1/embeddings in the OpenAI shape, the way chapter 5's gateway
                answers the harnesses, writing the `call` line its hooks write (the workflow and class from the
                request's tags, the trace id, the aliases, the Region, no fallback, the tokens) into the log of
                the gateway the live job asked for (`start_gateway`)
  Ollama        GET /api/version, /api/tags (each model's digest), /api/ps, POST /api/generate (an unload), and
                POST /api/chat and /api/embed, so the same fake can also stand behind chapter 5's real gateway
  the model     a reply by what the request is: the judge's verdict form for a judgement, W5's TITLE and BODY for
                a pull request's prose, and one plain sentence for every other question

No reply calls a tool, so each workflow's harness gets a final answer on its first turn.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections import Counter
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

RIGHT = "VERDICT: right\nREASON: The output meets every criterion."
ANSWER = "I could not find that in what I can read."
PROSE = "TITLE: Drift on a resource\nBODY: The drift agent found a change on this resource."
DIGESTS = {"gpt-oss:20b": "f" * 64, "gemma4:12b": "e" * 64, "qwen3-embedding:0.6b": "d" * 64}
WIDTH = 1024  # W1's embedding width (ingest/embedding.SERVED_DIMENSIONS)


def reply_for(body: dict[str, Any]) -> str:
    system = next((m.get("content") or "" for m in body.get("messages") or [] if m.get("role") == "system"), "")
    if "VERDICT: right" in system:  # the judge's prompt asks for its two lines
        return RIGHT
    if "the title and the body of a pull request" in system:  # W5's prose seam
        return PROSE
    return ANSWER


def vector(text: str) -> list[float]:
    """A unit vector from the text's hash, the same for the same text."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    values = [(seed[i % 32] - 127.5) / 127.5 + (i % 7) / 100 for i in range(WIDTH)]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


class FakeModel:
    def __init__(self, reply: Callable[[dict[str, Any]], str] = reply_for, version: str = "0.0.0-fake") -> None:
        self.reply, self.version = reply, version
        self.digests = dict(DIGESTS)
        self.log: Path | None = None
        self.lock = threading.Lock()
        self.requests: Counter[str] = Counter()
        self.unloaded: list[str] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    # The live job's seam: where it would start chapter 5's gateway, the fake answers itself.
    def start_gateway(self, name: str, config: Path, manifests: Path, hooks: Path, out: Path) -> tuple[str, Path, Callable[[], None]]:
        self.log = out / f"gateway-{name}.jsonl"
        self.requests[f"gateway {name}"] += 1
        return self.url, self.log, lambda: None

    def write(self, line: dict[str, Any]) -> None:
        if self.log is None:
            return
        with self.lock, self.log.open("a", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps(line) + "\n")

    def call_line(self, body: dict[str, Any], prompt: int, completion: int) -> dict[str, Any]:
        metadata = body.get("metadata") or {}
        tags = dict(t.split(":", 1) for t in metadata.get("tags") or [] if ":" in t)
        alias = body.get("model")
        return {"ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), "event": "call",
                "trace_id": metadata.get("trace_id"), "workflow": tags.get("workflow"), "data_class": tags.get("data_class"),
                "requested_alias": alias, "served_alias": alias, "fallback": False, "fallbacks_disabled": False,
                "deployment": f"fake-{alias}", "region": "ca-central-1", "served_model": "fake", "prompt_tokens": prompt,
                "completion_tokens": completion, "cost_usd": 0.0, "latency_ms": 1}


def _handler(fake: FakeModel) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args: Any) -> None:
            return None

        def _send(self, payload: Any, code: int = 200) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            fake.requests[f"GET {self.path}"] += 1
            if self.path == "/api/version":
                return self._send({"version": fake.version})
            if self.path == "/api/tags":
                return self._send({"models": [{"name": n, "model": n, "digest": d} for n, d in fake.digests.items()]})
            if self.path == "/api/ps":
                return self._send({"models": [{"name": "gpt-oss:20b", "context_length": 16384, "size_vram": 1}]})
            return self._send({"status": "ok"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            fake.requests[f"POST {self.path}"] += 1
            path = self.path.rstrip("/")
            if path.endswith("/chat/completions"):
                text = fake.reply(body)
                prompt = sum(len(str(m.get("content") or "")) for m in body.get("messages") or []) // 4 + 1
                completion = len(text) // 4 + 1
                fake.write(fake.call_line(body, prompt, completion))
                return self._send({"id": "fake", "object": "chat.completion", "created": int(time.time()), "model": body.get("model"),
                                   "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                                "finish_reason": "stop"}],
                                   "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                                             "total_tokens": prompt + completion}})
            if path.endswith("/embeddings"):
                texts = body.get("input")
                texts = [texts] if isinstance(texts, str) else list(texts or [])
                fake.write(fake.call_line(body, sum(len(t) // 4 + 1 for t in texts), 0))
                return self._send({"object": "list", "model": body.get("model"), "usage": {"prompt_tokens": 1, "total_tokens": 1},
                                   "data": [{"object": "embedding", "index": i, "embedding": vector(t)} for i, t in enumerate(texts)]})
            if path == "/api/generate":
                fake.unloaded.append(body.get("model"))
                return self._send({"model": body.get("model"), "done": True, "done_reason": "unload"})
            if path == "/api/show":
                return self._send({"modelfile": "", "parameters": "", "template": "", "details": {"family": "fake"},
                                   "model_info": {}, "capabilities": ["completion", "tools"]})
            if path == "/api/chat":  # Ollama's own API, as LiteLLM's ollama_chat provider calls it
                text = fake.reply(body)
                return self._send({"model": body.get("model"), "created_at": "2026-11-03T00:00:00Z",
                                   "message": {"role": "assistant", "content": text}, "done": True, "done_reason": "stop",
                                   "total_duration": 1000, "prompt_eval_count": 50, "eval_count": len(text) // 4 + 1})
            if path in ("/api/embed", "/api/embeddings"):
                texts = body.get("input") or body.get("prompt")
                texts = [texts] if isinstance(texts, str) else list(texts or [])
                return self._send({"model": body.get("model"), "embeddings": [vector(t) for t in texts],
                                   "prompt_eval_count": 1})
            return self._send({"error": f"no such path {self.path}"}, 404)

    return Handler
