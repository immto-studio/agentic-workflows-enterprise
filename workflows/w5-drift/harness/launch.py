"""The four readers as processes under their identities, for the night command and the tests.

Chapter 14. W4's eval/lab.py starts its servers as subprocesses the way the scripts run; W5's night does
the same with its four readers (servers/<name>_reader.py), each with its identity, its lock, its own log,
a fresh copy of the membership table with the sync's stamps set to now (W1's rule grants only a table's
broad groups once its rebuild is 36 hours old, and W5's table has none), and the shared token secret.
tests/conftest.py builds its fixture on `start_readers`.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
TABLE_PATH = W5 / "catalog" / "membership.json"
READERS = ("state", "cloud", "cost", "policy")
IDENTITY = "larkspur-drift-{}-reader"


def fresh_table(now: datetime | None = None) -> dict:
    """W5's committed table with the sync's two stamps set to now, as the nightly sync leaves it."""
    now = now or datetime.now(timezone.utc)
    table = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
    table["synced_at"] = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    table["delta_applied_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return table


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Readers:
    """What is running: the catalog's server names to their URLs, each reader's log, the processes."""
    urls: dict[str, str]
    logs: dict[str, Path]
    folder: Path
    procs: list[tuple[str, subprocess.Popen, IO[str], Path]] = field(default_factory=list)

    def stop(self) -> None:
        for _, proc, stderr, _ in self.procs:
            proc.terminate()
        for _, proc, stderr, _ in self.procs:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
            stderr.close()


def start_readers(folder: Path, secret: str, table_path: Path | None = None, *, deadline_s: float = 60.0,
                  python: str = sys.executable) -> Readers:
    """Start the four readers on free ports and wait until each listens; stop them with `Readers.stop`."""
    folder.mkdir(parents=True, exist_ok=True)
    if table_path is None:
        table_path = folder / "membership.json"
        table_path.write_text(json.dumps(fresh_table(), indent=2), encoding="utf-8")
    readers = Readers(urls={}, logs={}, folder=folder)
    for name in READERS:
        port = free_port()
        log = folder / f"{name}.log"
        env = {**os.environ, "TOOL_IDENTITY": IDENTITY.format(name), "W5_TOKEN_SECRET": secret, "TOOL_LOG_FILE": str(log),
               "MEMBERSHIP_TABLE": str(table_path), "TRACE_FILE": str(folder / "traces.jsonl"), "PYTHONUTF8": "1"}
        env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)  # the lab never talks to a collector
        stderr_path = folder / f"{name}.stderr"
        stderr = stderr_path.open("w", encoding="utf-8")
        proc = subprocess.Popen([python, "-X", "utf8", str(W5 / "servers" / f"{name}_reader.py"), "--port", str(port)],
                                env=env, stdout=subprocess.DEVNULL, stderr=stderr, text=True)
        readers.procs.append((name, proc, stderr, stderr_path))
        readers.urls[f"{name}-mcp"] = f"http://127.0.0.1:{port}/mcp"
        readers.logs[name] = log
    deadline = time.time() + deadline_s
    for name, proc, stderr, stderr_path in readers.procs:
        port = int(readers.urls[f"{name}-mcp"].rsplit(":", 1)[1].split("/")[0])
        while True:
            if proc.poll() is not None:
                stderr.close()
                text = stderr_path.read_text(encoding="utf-8")
                readers.stop()
                raise RuntimeError(f"the {name} reader exited with {proc.returncode}: {text[-2000:]}")
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            if time.time() > deadline:
                readers.stop()
                raise TimeoutError(f"the {name} reader did not listen on {port} within {deadline_s} s")
            time.sleep(0.2)
    return readers
