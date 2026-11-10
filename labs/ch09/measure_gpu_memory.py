"""GPU memory a model takes in Ollama, read from nvidia-smi before and after the model loads.

Unloads every model, reads the card's memory in use (the desktop and other processes), loads the
model with one short request, reads again, then unloads it. The difference is what the model takes
at Ollama's settings for the run (OLLAMA_NUM_PARALLEL and the default context length), which is
what the golden-set runs used.

Run:  python measure_gpu_memory.py --model gpt-oss:20b --model gemma4:12b --json gpu-memory.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

OLLAMA = "http://127.0.0.1:11434"


def used_mib() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, check=True).stdout.strip().splitlines()[0]
    return int(out)


def card() -> dict:
    out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, check=True).stdout.strip().splitlines()[0]
    name, total, driver = (part.strip() for part in out.split(","))
    return {"gpu": name, "memory_total_mib": int(total), "driver": driver}


def unload(model: str) -> None:
    httpx.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)


def settle(seconds: float = 3.0) -> None:
    time.sleep(seconds)


def measure(model: str, others: list[str]) -> dict:
    for m in others + [model]:
        unload(m)
    settle()
    before = used_mib()
    httpx.post(f"{OLLAMA}/api/generate", json={"model": model, "prompt": "Say OK.", "stream": False,
                                               "keep_alive": "5m", "options": {"num_predict": 4}}, timeout=300)
    settle()
    loaded = used_mib()
    ps = httpx.get(f"{OLLAMA}/api/ps", timeout=10).json()
    entry = next((m for m in ps.get("models", []) if m.get("name") == model), {})
    unload(model)
    return {"model": model, "used_before_mib": before, "used_loaded_mib": loaded,
            "model_takes_mib": loaded - before,
            "context_length": entry.get("context_length")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    version = httpx.get(f"{OLLAMA}/api/version", timeout=10).json()["version"]
    result = {"ollama": version, **card(), "runs": [measure(m, args.model) for m in args.model]}
    text = json.dumps(result, indent=2)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
