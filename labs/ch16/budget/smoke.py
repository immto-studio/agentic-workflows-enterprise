"""The Prisma smoke test: LiteLLM's proxy with a database on native Windows, two calls, a key, a block.

Chapter 16, step 4 (companion #14, O-D7 as amended on 3 November 2026). Every LiteLLM feature the monthly
budget needs (key budgets with a reset, soft-budget alerts, `/key/block`) reads and writes LiteLLM's
PostgreSQL database through Prisma. Fact sheet 8.1 found an open defect: on Windows the proxy's watcher
checks that Prisma's query engine is alive with `os.kill(pid, 0)`, and two open pull requests say that call
kills the engine there. This script runs the proxy against PostgreSQL 16.15 from `budget/postgres.py` and
records what happens:

1. `prisma generate` for LiteLLM's schema, timed;
2. a fresh cluster on 127.0.0.1, chapter 5's fake backend, and the proxy with `DATABASE_URL`, given a console
   of its own with its window hidden, as a terminal would give it;
3. the query engine's processes, each held open from the moment it appears so that its exit code can be
   read after it ends;
4. two calls with the master key, a virtual key made for W2 and a call with it, `/key/block`, a call with
   the blocked key, `/key/unblock`, a last call, and the key's row read from the database;
5. the watcher's call alone: `os.kill(child, 0)` against a sleeping child, from a process with a console of
   its own and from one with no console at all, under this interpreter and any given with --probe-python.

Run it in a scratch environment made from chapter 5's requirements plus `prisma`, from labs/ch16:

    pip install -r ../ch05/requirements.txt "prisma>=0.11.0,<1.0"
    python budget/postgres.py           # once: the pinned PostgreSQL, checked, into budget/pg/
    python budget/smoke.py --out results/<date>/budget [--prisma-home <short folder>]

`prisma generate` fetches the Prisma CLI from npm and its engines on first use, into Prisma's home (the home
folder's `.cache` unless --prisma-home says otherwise). npm runs about 110 characters below that home, and
Windows refuses a working directory of 260 characters or more, so the home must be short. The raw records
(the proxy's log, PostgreSQL's log, the cluster) stay in `budget/_lab/<stamp>/`; the result, with no path,
password or key of this machine in it, goes to `<out>/smoke.json`.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
CH05 = LAB.parent / "ch05"
sys.path.insert(0, str(HERE))

import postgres  # noqa: E402
import record  # noqa: E402
from procs import new_console, stop_tree  # noqa: E402

MASTER_KEY = "sk-larkspur-lab-smoke"  # a local value for a proxy on 127.0.0.1, as chapter 5's demo has
ENGINE_NAME = re.compile(r"query[-_]engine", re.IGNORECASE)
WATCHER_LINE = re.compile(r"prisma-query-engine|Watching engine|engine poll|reconnect|Prisma Client Exception|"
                          r"migrations found|toolchain|health watchdog", re.IGNORECASE)


# --- Windows processes ---------------------------------------------------------------------------

SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


class Held:
    """A handle opened on a process while it lives, so its exit code can be read after it ends."""

    def __init__(self, pid: int, name: str, seen: float) -> None:
        self.pid, self.name, self.seen = pid, name, seen
        self.ended: float | None = None
        self.exit_code: int | None = None
        self.handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)

    def poll(self, now: float) -> None:
        if self.ended is not None or not self.handle:
            return
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code))
        if code.value != STILL_ACTIVE:
            self.ended, self.exit_code = now, code.value

    def close(self) -> None:
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


def processes() -> list[dict]:
    """Every process on the machine: pid, parent pid and image name (Win32_Process)."""
    script = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name "
              "| ConvertTo-Json -Compress")
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=60)
    rows = json.loads(done.stdout or "[]")
    return [{"pid": r["ProcessId"], "ppid": r["ParentProcessId"], "name": r["Name"]} for r in rows]


def descendants(root: int, rows: list[dict]) -> list[dict]:
    found, frontier = [], {root}
    while frontier:
        children = [r for r in rows if r["ppid"] in frontier and r not in found]
        found += children
        frontier = {r["pid"] for r in children}
    return found




# --- the watcher's call, alone ---------------------------------------------------------------------

# The prober runs on a base interpreter, never a virtual environment's: on Windows a venv's python.exe is a
# launcher that starts the real interpreter as its child, and that child would get a console of its own. The
# snippet needs the standard library only. It starts a sleeping child the way the proxy starts its engine and
# calls os.kill(child, 0) as LiteLLM's watcher does. With no console, the child gets one of its own and no
# window (CREATE_NO_WINDOW); a console program started from a process without one would open a window.
PROBE = """
import ctypes, json, os, subprocess, sys, time
mode, out = sys.argv[1], sys.argv[2]
flags = subprocess.CREATE_NO_WINDOW if mode == "no-console" else 0
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.0)
attempts = []
for _ in range(3):
    try:
        os.kill(child.pid, 0)
        call = "returned"
    except KeyboardInterrupt:
        call = "a Ctrl+C reached the prober itself"
    except OSError as exc:
        call = "raised %s (winerror %s)" % (type(exc).__name__, getattr(exc, "winerror", None))
    except SystemError as exc:
        call = "raised SystemError (%s)" % str(exc)[:80]
    time.sleep(0.5)
    attempts.append({"call": call, "child_alive": child.poll() is None, "child_exit_code": child.poll()})
    if child.poll() is not None:
        break
if child.poll() is None:
    child.kill()
buffer = (ctypes.c_uint * 16)()
on_console = ctypes.windll.kernel32.GetConsoleProcessList(buffer, 16)
with open(out, "w", encoding="utf-8") as stream:
    json.dump({"mode": mode, "python": sys.version.split()[0], "processes_on_prober_console": on_console,
               "attempts": attempts}, stream)
"""


def probe_os_kill(work: Path, interpreter: str) -> list[dict]:
    """The watcher's call from a prober with a console of its own, and from one with no console at all."""
    results = []
    for mode in ("console", "no-console"):
        out = work / f"probe-{abs(hash(interpreter))}-{mode}.json"
        flags = new_console() if mode == "console" else {"creationflags": subprocess.DETACHED_PROCESS}
        prober = subprocess.Popen([interpreter, "-I", "-c", PROBE, mode, str(out)], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        try:
            prober.wait(timeout=60)
        except subprocess.TimeoutExpired:
            prober.kill()
        results.append(json.loads(out.read_text(encoding="utf-8")) if out.exists()
                       else {"mode": mode, "error": f"the prober wrote nothing (exit {prober.poll()})"})
    return results


# --- the run ---------------------------------------------------------------------------------------

class Recorder:
    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.steps: list[dict] = []
        self.engines: dict[int, Held] = {}
        self.proxy_pid: int | None = None

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    def watch(self) -> None:
        """Look for new engine processes under the proxy, and poll the ones already held."""
        if self.proxy_pid is None:
            return
        try:
            tree = descendants(self.proxy_pid, processes())
        except (json.JSONDecodeError, subprocess.SubprocessError):
            tree = []
        for row in tree:
            if ENGINE_NAME.search(row["name"]) and row["pid"] not in self.engines:
                self.engines[row["pid"]] = Held(row["pid"], row["name"], self.now())
        for held in self.engines.values():
            held.poll(self.now())

    def alive(self) -> int:
        return sum(1 for held in self.engines.values() if held.ended is None)

    def step(self, name: str, **fields: Any) -> dict:
        self.watch()
        entry = {"step": name, "t": self.now(), **fields, "engines_alive": self.alive(),
                 "engines_seen": len(self.engines)}
        self.steps.append(entry)
        print(json.dumps(entry), flush=True)
        return entry


def call(url: str, key: str, text: str) -> dict:
    started = time.monotonic()
    try:
        r = httpx.post(f"{url}/chat/completions", timeout=60, headers={"Authorization": f"Bearer {key}"},
                       json={"model": "larkspur-chat", "messages": [{"role": "user", "content": text}]})
    except httpx.HTTPError as exc:
        return {"status": None, "error": type(exc).__name__, "seconds": round(time.monotonic() - started, 2)}
    out: dict[str, Any] = {"status": r.status_code, "seconds": round(time.monotonic() - started, 2)}
    if r.status_code == 200:
        out["answer"] = r.json()["choices"][0]["message"]["content"]
    else:
        out["error"] = _message(r)
    return out


def admin(url: str, path: str, body: dict) -> dict:
    started = time.monotonic()
    try:
        r = httpx.post(f"{url}{path}", timeout=60, headers={"Authorization": f"Bearer {MASTER_KEY}"}, json=body)
    except httpx.HTTPError as exc:
        return {"status": None, "error": type(exc).__name__, "seconds": round(time.monotonic() - started, 2)}
    out: dict[str, Any] = {"status": r.status_code, "seconds": round(time.monotonic() - started, 2)}
    if r.status_code != 200:
        out["error"] = _message(r)
        return out
    out["body"] = r.json()
    return out


def _message(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return r.text[:300]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message"))[:300]
    return json.dumps(body)[:300]


def key_row(cluster: postgres.Cluster, alias: str) -> dict | None:
    import psycopg

    try:
        with psycopg.connect(cluster.url("litellm"), connect_timeout=5) as conn:
            row = conn.execute('SELECT key_alias, blocked, spend, max_budget, budget_duration, metadata '
                               'FROM "LiteLLM_VerificationToken" WHERE key_alias = %s', (alias,)).fetchone()
    except psycopg.Error as exc:
        return {"error": type(exc).__name__, "message": str(exc)[:200]}
    if row is None:
        return None
    return {"key_alias": row[0], "blocked": row[1], "spend": row[2], "max_budget": row[3],
            "budget_duration": row[4], "metadata": row[5]}


def wait_http(url: str, seconds: float, rec: Recorder) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        rec.watch()
        time.sleep(0.5)
    return False


def versions() -> dict:
    found = {}
    for name in ("litellm", "litellm-proxy-extras", "prisma", "nodeenv", "psycopg"):
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = None
    node = shutil.which("node")
    found["node"] = (subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
                     if node else None)
    found["python"] = platform.python_version()
    found["os"] = f"{platform.system()} {platform.release()} {platform.version()}"
    return found


def config_text(backend_port: int) -> str:
    return f"""# The smoke test's proxy: one alias on chapter 5's fake backend, and the database. No callback.
model_list:
  - model_name: larkspur-chat
    litellm_params:
      model: openai/fake-primary
      api_base: http://127.0.0.1:{backend_port}/v1
      api_key: not-used-by-the-fake
      input_cost_per_token: 0.000003
      output_cost_per_token: 0.000015
    model_info: {{id: primary}}
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
"""


def run(out: Path, settle: float, prisma_home: Path | None, probe_pythons: list[str]) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = HERE / "_lab" / f"smoke-{stamp}"
    work.mkdir(parents=True)
    rec = Recorder()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               LITELLM_LOCAL_MODEL_COST_MAP="True", LITELLM_MASTER_KEY=MASTER_KEY, LITELLM_LOG="INFO")
    # As in an activated environment: the Prisma CLI spawns the `prisma-client-py` generator by name.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    if prisma_home is not None:
        env |= {"PRISMA_HOME_DIR": str(prisma_home), "PRISMA_NODEENV_CACHE_DIR": str(prisma_home / "nodeenv")}
    result: dict[str, Any] = {"date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}", "versions": versions(),
                              "postgres": postgres.VERSION, "proxy_console": "a console of its own, hidden"}
    procs: list[subprocess.Popen] = []
    cluster = postgres.Cluster(data=work / "pgdata")
    schema = Path(metadata.distribution("litellm").locate_file("litellm/proxy/schema.prisma"))
    try:
        started = time.monotonic()
        generate = subprocess.run([sys.executable, "-m", "prisma", "generate", f"--schema={schema}"],
                                  capture_output=True, encoding="utf-8", errors="replace", env=env, timeout=900)
        (work / "prisma-generate.log").write_text(generate.stdout + generate.stderr, encoding="utf-8")
        said = [line.strip() for line in (generate.stdout + generate.stderr).splitlines() if line.strip()]
        rec.step("prisma generate", exit=generate.returncode, seconds=round(time.monotonic() - started, 1),
                 said=said[-2:])
        if generate.returncode:
            return result | {"steps": rec.steps, "verdict": "prisma generate failed"}

        postgres.verified()
        cluster.init()
        cluster.start()
        cluster.wait()
        cluster.create_database("litellm")
        rec.step("postgres up", listen="127.0.0.1")

        backend_port, proxy_port = postgres.free_port(), postgres.free_port()
        procs.append(subprocess.Popen([sys.executable, str(CH05 / "gateway" / "fake_backend.py"), "--name",
                                       "primary", "--port", str(backend_port)], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if not wait_http(f"http://127.0.0.1:{backend_port}/health", 30, rec):
            raise RuntimeError("the fake backend did not come up")
        config = work / "litellm.smoke.yaml"
        config.write_text(config_text(backend_port), encoding="utf-8", newline="\n")
        litellm = shutil.which("litellm", path=str(Path(sys.executable).parent)) or "litellm"
        log = (work / "proxy.log").open("w", encoding="utf-8")
        proxy = subprocess.Popen([litellm, "--config", str(config), "--host", "127.0.0.1", "--port",
                                  str(proxy_port)], cwd=str(work), stdout=log, stderr=subprocess.STDOUT,
                                 env=dict(env, DATABASE_URL=cluster.url("litellm")), **new_console())
        procs.append(proxy)
        rec.proxy_pid = proxy.pid
        url = f"http://127.0.0.1:{proxy_port}"
        up = wait_http(f"{url}/health/liveliness", 300, rec)
        rec.step("proxy up" if up else "proxy never answered", proxy_exit=proxy.poll())
        if not up:
            return result | {"steps": rec.steps, "verdict": "the proxy never came up"}
        try:
            readiness = httpx.get(f"{url}/health/readiness", timeout=10).json()
        except (httpx.HTTPError, ValueError) as exc:
            readiness = {"error": type(exc).__name__}
        rec.step("readiness", db=readiness.get("db"), status=readiness.get("status"))

        rec.step("call 1, master key", **call(url, MASTER_KEY, "Is claims-api healthy?"))
        rec.step("call 2, master key", **call(url, MASTER_KEY, "Is policy-admin healthy?"))
        made = admin(url, "/key/generate", {"key_alias": "w2-ops-assistant", "max_budget": 200.0,
                                            "metadata": {"workflow": "w2-ops-assistant"}})
        key = (made.get("body") or {}).get("key")
        rec.step("key generate", status=made.get("status"), error=made.get("error"), got_key=bool(key))
        if key:
            rec.step("call 3, the virtual key", **call(url, key, "Is claims-api healthy?"))
            blocked = admin(url, "/key/block", {"key": key})
            rec.step("key block", status=blocked.get("status"), error=blocked.get("error"),
                     blocked=(blocked.get("body") or {}).get("blocked"))
            rec.step("call 4, the blocked key", **call(url, key, "Is claims-api healthy?"))
            unblocked = admin(url, "/key/unblock", {"key": key})
            rec.step("key unblock", status=unblocked.get("status"), error=unblocked.get("error"))
            rec.step("call 5, the key unblocked", **call(url, key, "Is claims-api healthy?"))
        rec.step("key row in the database", row=key_row(cluster, "w2-ops-assistant"))
        deadline = time.monotonic() + settle
        while time.monotonic() < deadline:
            rec.watch()
            time.sleep(1)
        rec.step("after settling", seconds=settle, proxy_exit=proxy.poll())
    finally:
        rec.watch()
        alive_at_stop = {pid for pid, held in rec.engines.items() if held.ended is None}
        stopped_at = rec.now()
        for p in reversed(procs):  # the proxy's whole tree: its launcher, the proxy, the query engines
            stop_tree(p)
        rec.watch()
        try:
            cluster.stop()
        except RuntimeError as exc:
            print(f"stopping PostgreSQL: {exc}", file=sys.stderr)
    engines = [{"seen_at": h.seen, "alive_when_the_script_stopped_the_proxy": pid in alive_at_stop,
                "stopped_at": stopped_at, "ended_at": h.ended, "exit_code": h.exit_code, "name": h.name}
               for pid, h in rec.engines.items()]
    for held in rec.engines.values():
        held.close()
    lines = [line.rstrip() for line in (work / "proxy.log").read_text(encoding="utf-8", errors="replace")
             .splitlines() if WATCHER_LINE.search(line)] if (work / "proxy.log").exists() else []
    interpreters = [getattr(sys, "_base_executable", sys.executable), *probe_pythons]
    result |= {"steps": rec.steps, "engines": engines, "proxy_log_watcher_lines": lines,
               "os_kill_probe": [r for py in interpreters for r in probe_os_kill(work, py)]}
    record.write_json(out / "smoke.json", result, secrets=(cluster.password, MASTER_KEY))
    print(f"raw records in {work}; result in {out / 'smoke.json'}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=LAB / "results" / "smoke")
    parser.add_argument("--settle", type=float, default=20.0, help="seconds to watch the engine after the calls")
    parser.add_argument("--prisma-home", type=Path, default=None,
                        help="Prisma's home for its CLI and engines (PRISMA_HOME_DIR); keep the path short")
    parser.add_argument("--probe-python", action="append", default=[],
                        help="another interpreter to run the os.kill probe under; repeat for several")
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("the smoke test is for native Windows", file=sys.stderr)
        return 2
    run(args.out, args.settle, args.prisma_home, args.probe_python)
    return 0


if __name__ == "__main__":
    sys.exit(main())
