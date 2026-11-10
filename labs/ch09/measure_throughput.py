"""Measure what one local GPU does with one model: load time, prompt and decode speed.

Chapter 9, part 1. Vendors publish throughput for data-center GPUs at high concurrency; the chapter
needs the number for the machine in front of you. This script asks Ollama's native API, which
reports exact token counts and durations per request, for the same task several times and prints
the medians. It talks to the model server directly, not through the gateway, because the gateway
adds its own latency and the point here is the model.

With --concurrency, several requests run at once and the script reports the aggregate decode
speed (all output tokens divided by wall time) and the median time per request. That is the
number a cost comparison needs: tokens per GPU-hour at a latency people will accept. Ollama
serves one request at a time unless it is started with OLLAMA_NUM_PARALLEL above 1.

Run:  python measure_throughput.py --model gpt-oss:20b --runs 5
      python measure_throughput.py --model gpt-oss:20b --concurrency 1 2 4 --num-predict 256
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

PROMPT = ("Write a short runbook, about 300 words, for restarting a stuck Kubernetes deployment safely: "
          "checks before, the command, checks after, and when to escalate.")


def one_run(base: str, model: str, prompt: str, num_predict: int) -> dict[str, float]:
    response = httpx.post(f"{base}/api/chat", timeout=600, json={
        "model": model, "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0, "num_predict": num_predict},
    })
    response.raise_for_status()
    body = response.json()
    ns = 1e9
    return {
        "load_s": body.get("load_duration", 0) / ns,
        "prompt_tokens": body.get("prompt_eval_count", 0),
        "prompt_tok_s": body.get("prompt_eval_count", 0) / max(body.get("prompt_eval_duration", 1) / ns, 1e-9),
        "output_tokens": body.get("eval_count", 0),
        "output_tok_s": body.get("eval_count", 0) / max(body.get("eval_duration", 1) / ns, 1e-9),
        "total_s": body.get("total_duration", 0) / ns,
    }


def concurrent_run(base: str, model: str, prompt: str, num_predict: int, n: int) -> dict[str, float]:
    """n requests at once, each its own prompt variant so no response is shared."""
    prompts = [f"{prompt} (Variant {i + 1}: a different service name each time.)" for i in range(n)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(lambda text: one_run(base, model, text, num_predict), prompts))
    wall = time.perf_counter() - started
    tokens = sum(r["output_tokens"] for r in results)
    return {
        "concurrency": n,
        "aggregate_output_tok_s": round(tokens / wall, 1),
        "median_request_s": round(statistics.median(r["total_s"] for r in results), 2),
        "median_per_request_tok_s": round(statistics.median(r["output_tok_s"] for r in results), 1),
        "wall_s": round(wall, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="gpt-oss:20b")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--num-predict", type=int, default=512)
    parser.add_argument("--concurrency", type=int, nargs="+", help="run these numbers of requests at once")
    parser.add_argument("--repeat", type=int, default=3, help="repetitions per concurrency level; medians reported")
    args = parser.parse_args(argv)

    if args.concurrency:
        version = httpx.get(f"{args.base}/api/version", timeout=10).json().get("version")
        # Warm up at the highest level, outside the timing: the first concurrent batch makes the
        # server allocate its parallel slots, and that one-off cost is not throughput.
        concurrent_run(args.base, args.model, PROMPT, 32, max(args.concurrency))
        rows = []
        for n in args.concurrency:
            reps = [concurrent_run(args.base, args.model, PROMPT, args.num_predict, n) for _ in range(args.repeat)]
            rows.append({"concurrency": n, "repeats": args.repeat,
                         **{key: statistics.median(r[key] for r in reps)
                            for key in ("aggregate_output_tok_s", "median_request_s", "median_per_request_tok_s")}})
        print(json.dumps({"server": f"ollama {version}", "model": args.model, "num_predict": args.num_predict,
                          "results": rows}))
        return 0

    version = httpx.get(f"{args.base}/api/version", timeout=10).json().get("version")
    runs = [one_run(args.base, args.model, PROMPT, args.num_predict) for _ in range(args.runs)]
    first, warm = runs[0], runs[1:] or runs
    summary = {
        "server": f"ollama {version}", "model": args.model, "runs": args.runs,
        "cold_load_s": round(first["load_s"], 2),
        "median_prompt_tok_s": round(statistics.median(r["prompt_tok_s"] for r in warm), 1),
        "median_output_tok_s": round(statistics.median(r["output_tok_s"] for r in warm), 1),
        "median_output_tokens": int(statistics.median(r["output_tokens"] for r in warm)),
        "median_total_s": round(statistics.median(r["total_s"] for r in warm), 2),
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
