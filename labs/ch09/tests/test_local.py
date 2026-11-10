"""Part 1 integration tests: the local model behind the chapter 5 gateway, driven by the harness.

They need Ollama on 127.0.0.1:11434 with the model pulled (`ollama pull gpt-oss:20b`), and they
start the gateway themselves on a free port. Without Ollama or the model they skip, so the suite
stays green on a machine without a GPU. A real model is not deterministic; the assertions are the
ones the chapter relies on, not exact wording.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

OLLAMA = os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434")
MODEL = os.environ.get("LOCAL_MODEL", "gpt-oss:20b")
ALIAS = "larkspur-chat-restricted"
MASTER_KEY = "sk-larkspur-lab-test"  # a test value, set in the proxy's environment, not a secret


def ollama_has_model() -> bool:
    try:
        tags = httpx.get(f"{OLLAMA}/api/tags", timeout=3).json()
    except httpx.HTTPError:
        return False
    return any(m.get("name") == MODEL or m.get("model") == MODEL for m in tags.get("models", []))


pytestmark = pytest.mark.skipif(not ollama_has_model(), reason=f"Ollama with {MODEL} is not running")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    exe = shutil.which("litellm", path=str(Path(sys.executable).parent))
    if not exe:
        pytest.skip("litellm console script not found next to the interpreter")
    log = tmp_path_factory.mktemp("gw") / "gateway.log"
    env = dict(os.environ, GATEWAY_LOG_FILE=str(log), GATEWAY_CONFIG=str(LAB / "gateway" / "litellm.config.yaml"),
               LITELLM_MASTER_KEY=MASTER_KEY, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    port = free_port()
    proc = subprocess.Popen([exe, "--config", "litellm.config.yaml", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=str(LAB / "gateway"), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                if httpx.get(f"{url}/health/liveliness", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("gateway did not start")
        yield {"url": url, "log": log}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_the_harness_drives_the_local_model_to_the_right_tool(gateway) -> None:
    import run_local_golden as rlg

    case = next(c for c in rlg.run_golden.load_cases() if c["id"] == "pods-claims-api")
    os.environ["LITELLM_MASTER_KEY"] = MASTER_KEY  # the adapter sends the key it finds there
    result = asyncio.run(rlg.run_case(case, gateway["url"], ALIAS, rlg.advertised_tools()))
    assert result.calls == [["get_pod_status", {"service": "claims-api"}]]
    assert "2" in result.answer and "3" in result.answer
    entries = [json.loads(line) for line in gateway["log"].read_text(encoding="utf-8").splitlines()]
    served = [e for e in entries if e["event"] == "call"]
    assert served and all(e["served_alias"] == ALIAS and e["deployment"] == "local-gpt-oss-20b" for e in served)
    assert all(e["fallback"] is False and e["region"] == "ca-central-1" for e in served)


def test_restricted_data_reaches_the_local_alias(gateway) -> None:
    body = {"model": ALIAS, "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
            "metadata": {"tags": ["workflow:w3-incident", "data_class:restricted"],
                         "trace_id": "2af7651916cd43dd8448eb211c80319c"}}
    r = httpx.post(f"{gateway['url']}/chat/completions", json=body, timeout=300,
                   headers={"Authorization": f"Bearer {MASTER_KEY}"})
    assert r.status_code == 200, r.text
    # A self-hosted deployment is priced at zero per token; LiteLLM omits the cost header then.
    assert float(r.headers.get("x-litellm-response-cost", "0")) == 0.0
