"""What one drill runs on 127.0.0.1: fake providers, PostgreSQL when the config needs it, and the LiteLLM proxy.

Chapter 16, step 5. The pieces are step 4's: `budget/postgres.py` for the pinned PostgreSQL and its cluster,
`budget/procs.py` to give the proxy a console of its own and to stop its whole tree, `budget/keys.py` for the
admin calls. The fake providers are `fake_provider.py`, one process each, so a drill can stop one and its port
refuses connections. Every port is chosen free, and everything a run writes stays in its folder under
`capacity/_lab/`. Step 5b adds the shared store, `garnet.py`'s Garnet, started before the proxy when the config
needs it and named to the proxy by CAPACITY_STORE_HOST, CAPACITY_STORE_PORT and CAPACITY_STORE_PASSWORD; a drill
can stop it and start it again on the same port, empty.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
BUDGET = LAB / "budget"
CH05 = LAB.parent / "ch05"
for folder in (HERE, BUDGET):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

MANIFESTS = CH05 / "manifest"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, seconds: float) -> float:
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return round(time.monotonic() - started, 2)
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{url} did not come up in {seconds} s")


@dataclass
class Fake:
    name: str
    args: list[str] = field(default_factory=list)
    port: int = field(default_factory=free_port)
    process: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class Stack:
    """Fakes, an optional database, a webhook receiver when the config sends alerts, and the proxy."""

    def __init__(self, work: Path, config: Path, fakes: dict[str, list[str]], urls: dict[str, str], *,
                 database: bool = False, receiver: bool = False, store: bool = False,
                 env: dict[str, str] | None = None) -> None:
        self.work = work
        self.work.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.fakes = {name: Fake(name, args) for name, args in fakes.items()}
        self.urls = urls  # environment variable -> fake name
        self.database = database
        self.receiver = receiver
        self.store: Any = None
        if store:
            import garnet

            self.store = garnet.Server(self.work / "garnet")
        self.extra_env = env or {}
        self.master_key = "sk-" + secrets.token_hex(16)
        self.proxy_port = free_port()
        self.receiver_port = free_port()
        self.procs: dict[str, subprocess.Popen] = {}
        self.cluster: Any = None
        self.proxy_starts: list[float] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.proxy_port}"

    def env(self) -> dict[str, str]:
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
                   LITELLM_LOCAL_MODEL_COST_MAP="True", LITELLM_MASTER_KEY=self.master_key,
                   GATEWAY_CONFIG=str(self.config), GATEWAY_LOG_FILE=str(self.work / "gateway.log"),
                   TRACE_FILE=str(self.work / "traces.jsonl"), MANIFEST_DIR=str(MANIFESTS),
                   BUDGET_STATE_DIR=str(self.work / "state"),
                   WEBHOOK_URL=f"http://127.0.0.1:{self.receiver_port}/budget-alert")
        if self.cluster is not None:
            env["DATABASE_URL"] = self.cluster.url("litellm")
        if self.store is not None:
            env.update(CAPACITY_STORE_HOST=self.store.host, CAPACITY_STORE_PORT=str(self.store.port),
                       CAPACITY_STORE_PASSWORD=self.store.password)
        for variable, name in self.urls.items():
            env[variable] = f"{self.fakes[name].url}/v1"
        env.update(self.extra_env)
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        return env

    # --- the fakes ------------------------------------------------------------------------------------

    def start_fake(self, name: str) -> None:
        fake = self.fakes[name]
        fake.process = subprocess.Popen(
            [sys.executable, str(HERE / "fake_provider.py"), "--name", name, "--port", str(fake.port), *fake.args],
            env=self.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(f"{fake.url}/health", 30)

    def stop_fake(self, name: str) -> None:
        from procs import stop_tree

        fake = self.fakes[name]
        if fake.process is not None:
            stop_tree(fake.process)
            fake.process = None

    def control(self, name: str, **body: Any) -> dict[str, Any]:
        return httpx.post(f"{self.fakes[name].url}/control", json=body, timeout=10).json()

    def provider_log(self, name: str) -> list[dict[str, Any]]:
        return httpx.get(f"{self.fakes[name].url}/log", timeout=30).json()["records"]

    # --- the database, the receiver and the proxy ----------------------------------------------------

    def start(self) -> None:
        for name in self.fakes:
            self.start_fake(name)
        if self.store is not None:
            import garnet

            garnet.verified()
            self.store.start()
        if self.database:
            import postgres

            postgres.verified()
            self.cluster = postgres.Cluster(data=self.work / "pgdata")
            self.cluster.init()
            self.cluster.start()
            self.cluster.wait()
            self.cluster.create_database("litellm")
        if self.receiver:
            self.procs["receiver"] = subprocess.Popen(
                [sys.executable, str(BUDGET / "receiver.py"), "--port", str(self.receiver_port),
                 "--outbox", str(self.work / "alerts.jsonl"), "--manifest-dir", str(MANIFESTS)],
                env=self.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_for(f"http://127.0.0.1:{self.receiver_port}/health", 30)
        self.start_proxy()

    def start_proxy(self) -> float:
        from procs import new_console

        litellm = shutil.which("litellm", path=str(Path(sys.executable).parent)) or "litellm"
        log = (self.work / "proxy.log").open("a", encoding="utf-8")
        self.procs["proxy"] = subprocess.Popen(
            [litellm, "--config", str(self.config), "--host", "127.0.0.1", "--port", str(self.proxy_port)],
            cwd=str(self.config.parent), env=self.env(), stdout=log, stderr=subprocess.STDOUT, **new_console())
        seconds = wait_for(f"{self.url}/health/liveliness", 300)
        self.proxy_starts.append(seconds)
        return seconds

    def stop_proxy(self) -> None:
        from procs import stop_tree

        if "proxy" in self.procs:
            stop_tree(self.procs.pop("proxy"))

    def restart_proxy(self, config: Path | None = None) -> float:
        self.stop_proxy()
        if config is not None:
            self.config = config
        return self.start_proxy()

    def stop_store(self) -> None:
        self.store.stop()

    def start_store(self) -> float:
        """The store again, on the same port with the same password, holding nothing."""
        return self.store.start()

    def pids(self) -> dict[str, int]:
        """The process id of everything this stack has running, for the record of what was stopped."""
        found = {name: proc.pid for name, proc in self.procs.items() if proc.poll() is None}
        found |= {f"fake {name}": fake.process.pid for name, fake in self.fakes.items()
                  if fake.process is not None and fake.process.poll() is None}
        if self.store is not None and self.store.pid is not None:
            found["store"] = self.store.pid
        return found

    def stop(self) -> None:
        from procs import stop_tree

        for proc in reversed(list(self.procs.values())):
            stop_tree(proc)
        self.procs.clear()
        for name in list(self.fakes):
            self.stop_fake(name)
        if self.store is not None:
            self.store.stop()
        if self.cluster is not None:
            try:
                self.cluster.stop()
            except RuntimeError as exc:
                print(f"stopping PostgreSQL: {exc}", file=sys.stderr)

    def gateway_lines(self) -> list[dict[str, Any]]:
        import json

        path = self.work / "gateway.log"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        return [json.loads(line) for line in lines if line.strip()]
