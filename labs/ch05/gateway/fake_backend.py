"""A fake OpenAI-compatible model endpoint, so the gateway lab runs without a model or a key.

Chapter 5, part 3. The gateway (LiteLLM, see `litellm.config.yaml`) routes an alias to this
server. It answers `POST /v1/chat/completions` in one of two ways. A request without `tools` gets
the last user message echoed back behind a tag that names the backend, so a reader can see which
deployment served it. A request with `tools` is answered by the rule-based model of part 2,
speaking the Chat Completions tool-call format, so the harness's loop runs through the gateway
and gets the same answers it gets in-process. Token usage is reported the way a real endpoint
reports it, so the gateway can price the call.

Three of them run in the lab, `--name primary`, `--name fallback` and `--name self-hosted`, on
the ports the config names. A backend can be told to fail at run time (`POST /control
{"fail": true}`), which is how the fallback test makes the primary return 503 without
restarting anything.

Run:  python fake_backend.py --name primary --port 8801
Binds 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

HOST = "127.0.0.1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
from gateway_model import from_chat_messages  # noqa: E402
from rule_model import rule_based_model  # noqa: E402


def rule_reply(messages: list[dict]) -> dict:
    """The rule-based model's decision as a Chat Completions assistant message."""
    decision = rule_based_model(from_chat_messages(messages))
    if "tool_call" in decision:
        call = decision["tool_call"]
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
            "function": {"name": call["name"], "arguments": json.dumps(call["args"])}}]}
    return {"role": "assistant", "content": decision["answer"]}


def build_app(name: str) -> Starlette:
    state = {"fail": False, "calls": 0, "cache_salt": None}

    async def chat_completions(request: Request) -> JSONResponse:
        state["calls"] += 1
        if state["fail"]:
            return JSONResponse({"error": {"message": f"{name} is failing on purpose",
                                           "type": "server_error"}}, status_code=503)
        body = await request.json()
        state["cache_salt"] = body.get("cache_salt")  # what vLLM would key its prefix cache on
        messages = body.get("messages") or []
        if body.get("tools"):
            message = rule_reply(messages)
        else:
            last_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
            if not isinstance(last_user, str):  # content can be a list of parts
                last_user = " ".join(p.get("text", "") for p in last_user if isinstance(p, dict))
            message = {"role": "assistant", "content": f"[{name}] {last_user}"}
        prompt_tokens = sum(len(str(m.get("content", "")).split()) for m in messages)
        completion_tokens = len((message.get("content") or json.dumps(message.get("tool_calls"))).split())
        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", f"fake-{name}"),
            "choices": [{"index": 0, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                         "message": message}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens},
        })

    async def control(request: Request) -> JSONResponse:
        body = await request.json()
        if "fail" in body:
            state["fail"] = bool(body["fail"])
        return JSONResponse({"name": name, "fail": state["fail"], "calls": state["calls"]})

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"name": name, "fail": state["fail"], "calls": state["calls"],
                             "cache_salt": state["cache_salt"]})

    return Starlette(routes=[
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        Route("/control", control, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", required=True, help="tag written into every answer, e.g. primary")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    uvicorn.run(build_app(args.name), host=HOST, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
