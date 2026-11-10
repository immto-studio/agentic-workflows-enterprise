"""Start three fake backends and the LiteLLM proxy, make six calls, print the gateway log, stop.

Chapter 5, part 3. The calls show what the gateway decides before a model sees a request:
route an alias to a deployment and price the call; serve the call from the fallback when the
primary fails, and log the Region that served it; refuse to fail over out of the Regions a
workflow's manifest allows; refuse a request that carries no workflow, data class or trace id;
refuse Restricted data for a managed model; send it to the self-hosted one. Nothing here needs
a key or a cloud.

Run:  python gateway/run_demo.py            (from labs/ch05, in the lab's virtual environment)
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

LAB = Path(__file__).resolve().parent.parent
GATEWAY = LAB / "gateway"
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY") or "sk-larkspur-lab-demo"  # a local demo value
TRACE = "0af7651916cd43dd8448eb211c80319c"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"{url} did not come up")


def call(url: str, text: str, model: str = "larkspur-chat", tags: list[str] | None = None,
         trace_id: str | None = TRACE) -> httpx.Response:
    metadata: dict = {}
    if tags is not None:
        metadata["tags"] = tags
    if trace_id:
        metadata["trace_id"] = trace_id
    return httpx.post(f"{url}/chat/completions", timeout=30,
                      headers={"Authorization": f"Bearer {MASTER_KEY}"},
                      json={"model": model, "messages": [{"role": "user", "content": text}],
                            "metadata": metadata})


def show(label: str, r: httpx.Response) -> None:
    if r.status_code == 200:
        content = r.json()["choices"][0]["message"]["content"]
        print(f"{label:<10} {r.status_code}  {content}  cost=${float(r.headers.get('x-litellm-response-cost', 0)):.6f}")
    else:
        error = r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {}
        print(f"{label:<10} {r.status_code}  {(error.get('message') or r.text)[:110]}")


def main() -> int:
    log = LAB / "gateway.log"
    if log.exists():
        log.unlink()
    env = dict(os.environ, GATEWAY_LOG_FILE=str(log), LITELLM_MASTER_KEY=MASTER_KEY,
               PYTHONUNBUFFERED="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    litellm = shutil.which("litellm", path=str(Path(sys.executable).parent)) or "litellm"
    port = free_port()
    backends = (("primary", 8801), ("fallback", 8802), ("self-hosted", 8803))
    procs = [subprocess.Popen([sys.executable, str(GATEWAY / "fake_backend.py"), "--name", name,
                               "--port", str(port)], env=env) for name, port in backends]
    try:
        for _, backend_port in backends:
            wait_for(f"http://127.0.0.1:{backend_port}/health", 20)
        procs.append(subprocess.Popen([litellm, "--config", "litellm.config.yaml", "--port", str(port),
                                       "--host", "127.0.0.1"], cwd=str(GATEWAY), env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        url = f"http://127.0.0.1:{port}"
        wait_for(f"{url}/health/liveliness", 120)
        print(f"gateway up on {url}; cost log at {log}\n")

        w2 = ["workflow:w2-ops-assistant", "data_class:internal", "owner:platform-team"]
        w3 = ["workflow:w3-incident", "data_class:confidential"]
        show("routed", call(url, "Is claims-api healthy?", tags=w2))
        httpx.post("http://127.0.0.1:8801/control", json={"fail": True}, timeout=5)
        show("fallback", call(url, "Is policy-admin healthy?", tags=w2, trace_id="1af7651916cd43dd8448eb211c80319c"))
        show("no-exit", call(url, "Summarize the claims-api incident", tags=w3, trace_id="2af7651916cd43dd8448eb211c80319c"))
        httpx.post("http://127.0.0.1:8801/control", json={"fail": False}, timeout=5)
        show("untagged", call(url, "Is claims-api healthy?", tags=None, trace_id=None))
        restricted = ["workflow:w3-incident", "data_class:restricted"]
        show("managed", call(url, "Summarize this claim file", tags=restricted))
        show("self-host", call(url, "Summarize this claim file", model="larkspur-chat-restricted",
                               tags=restricted, trace_id="3af7651916cd43dd8448eb211c80319c"))
        time.sleep(1.5)
        print("\ngateway.log:")
        for line in log.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            rec.pop("ts", None)
            print(" ", json.dumps(rec))
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
