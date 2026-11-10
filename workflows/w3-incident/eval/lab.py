"""The live wiring for W3's model runs: start the servers, the approval service, and the gateway, run each
golden incident through the harness on a local model, score, and record (step 5b, part 2).

Mirrors W2's eval/answer_eval.py main(): the three W2 read servers, the writer, and the ServiceNow server run
as subprocesses under their identities over a fresh membership table; the approval service runs behind its HTTP
layer in-process; the gateway (litellm) runs as a subprocess, started with PYTHONUTF8=1. For each incident the
harness opens the five MCP sessions, triages as the persona, and when it proposes a write, a second eligible
person from the approvers group approves it so the write executes; the cluster-state and ServiceNow-state files
are reset between incidents. eval/score.py scores the records, and the results and a README table are written.
Each server's log and the harness's log, `harness.jsonl`, go to the run folder (`_lab/run/`): the logs server's
line keeps `contains` only as an HMAC, and the harness's log keeps the text (companion #126).

An incident is one trace (chapter 16's lab, companion #14; a follow-up to step 3b, which found W3's spans
scattered). Its `invoke_agent w3-incident` span opens before the five sessions and closes after the record is
made, with the incident's trace id; the sessions' set-up, every read and every write sit under it through the
bridges, and every model call through the `traceparent` the model puts in the gateway request. A process with
no tracer provider records none of it, so a run here, which installs none, sends what it sent before.

Run (from workflows/w3-incident):  python eval/lab.py --model-tag gpt-oss-20b
Needs Ollama and the models pulled. If a server or the gateway will not start, it records what ran and stops.
`run_all(..., gateway_url=...)` uses a gateway that is already running instead of starting one (the trace test).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
W3 = HERE.parent
W2 = W3.parent / "w2-ops-assistant"
W1 = W3.parent / "w1-knowledge-assistant"
CH05 = W3.parents[1] / "labs" / "ch05"
SCRATCH = Path(os.environ.get("W3_LAB_SCRATCH", HERE / "_lab"))
for folder in (W3 / "state", W3 / "harness", W3 / "approval", W3 / "servers", HERE, W2 / "servers",
               W1 / "knowledge-server", W1 / "knowledge-server" / "membership", CH05 / "harness", CH05 / "tracing"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import yaml  # noqa: E402
from mcp import Client  # noqa: E402
from opentelemetry import context as otel_context  # noqa: E402

import score as scoring  # noqa: E402
import run_incidents as runner  # noqa: E402
import trace_setup as tracing  # noqa: E402
from access import MembershipTable, issue  # noqa: E402
from actor_transport import ActorMCP  # noqa: E402
from approval_client import ApprovalClient  # noqa: E402
from approval_service import Service, load_approvers, serve as serve_approvals  # noqa: E402
from client import bridge  # noqa: E402
from common import W3_RUNTIME, load_service_map  # noqa: E402
from loop import CHAT_ALIAS, W3GatewayModel  # noqa: E402
from machine import Machine  # noqa: E402
from triage import Harness, Services  # noqa: E402
from w3_server import W3_SCOPE, W3_SERVERS_APP  # noqa: E402
from writer import Writer  # noqa: E402

SECRET = "w3-lab-secret-for-tests-at-least-32-bytes"
SERVICE_KEY = "w3-lab-approval-service-key"
GATEWAY_KEY = "sk-w3-lab"
WORKFLOW = "w3-incident"
MANIFEST = yaml.safe_load((W3 / "manifest" / "w3-incident.yaml").read_text(encoding="utf-8"))
CATALOG = yaml.safe_load((W2 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
W3CATALOG = yaml.safe_load((W3 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
READ_TOOLS = {t for t, spec in MANIFEST["tools"].items() if not spec.get("writes")}
WRITE_TOOLS = {t for t, spec in MANIFEST["tools"].items() if spec.get("writes")}
# The two writes the model may propose; record_change is the harness's own, written after an
# approval, not something the model calls, so it is not in the model's tools or its writes.
MODEL_WRITES = {"restart_deployment", "scale_deployment"}
READ_ALLOWED = {t: set(spec["args"]) for t, spec in MANIFEST["tools"].items() if not spec.get("writes")}

# Which server serves each tool. The reads are on the three W2 servers plus the ServiceNow read; the writes
# on the writer; record_change on the ServiceNow server.
SERVER_OF = {t: spec["server"] for t, spec in CATALOG["tools"].items()}  # W2's six reads
SERVER_OF.update({t: ("servicenow-mcp" if t in ("get_recent_changes", "record_change") else "writer-mcp")
                  for t in W3CATALOG["tools"]})
LOCKS = {
    "kubernetes-mcp": W2 / "servers" / "kubernetes.lock.json",
    "metrics-mcp": W2 / "servers" / "metrics.lock.json",
    "logs-mcp": W2 / "servers" / "logs.lock.json",
    "writer-mcp": W3 / "servers" / "writer.lock.json",
    "servicenow-mcp": W3 / "servers" / "servicenow.lock.json",
}
SERVER_IDENTITY = {
    "kubernetes-mcp": "larkspur-ops-kubernetes-reader", "metrics-mcp": "larkspur-ops-metrics-reader",
    "logs-mcp": "larkspur-ops-logs-reader", "writer-mcp": "larkspur-ops-restarter",
    "servicenow-mcp": "larkspur-ops-change-writer",
}
SERVER_SCRIPT = {
    "kubernetes-mcp": W2 / "servers" / "kubernetes_server.py", "metrics-mcp": W2 / "servers" / "metrics_server.py",
    "logs-mcp": W2 / "servers" / "logs_server.py", "writer-mcp": W3 / "servers" / "writer_server.py",
    "servicenow-mcp": W3 / "servers" / "servicenow_server.py",
}
PERSONA_GROUPS = {
    "oncall.engineer": {"lm-all-staff", "lm-eng-all"},
    "incident.responder": {"lm-all-staff", "lm-eng-all", "lm-sec-incident-response"},
    "pci.operator": {"lm-all-staff", "lm-eng-all", "lm-pci-cde-operators"},
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port: int, deadline_s: float = 60.0) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def fresh_table_path() -> Path:
    sys.path.insert(0, str(W2 / "tests"))
    import conftest as w2c  # noqa: E402
    import sync  # noqa: E402
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "table.json"
    sync.write_table(w2c.fresh_table(), path)
    return path


# The three read servers are W2's and want a W2-app token (they accept W3's runtime as a client, step 3b);
# the writer and the ServiceNow server are W3's and want a W3-app token. W3's runtime holds both, as chapter 11
# said W2's runtime holds a second token for the knowledge server.
W2_SERVERS = {"kubernetes-mcp", "metrics-mcp", "logs-mcp"}


def persona_token(persona: str, *, w2: bool) -> str:
    from common import W2_SCOPE, W2_SERVERS_APP
    oid, upn = OIDS[persona], f"{persona}@larkspur.example"
    if w2:
        return issue(SECRET, oid, upn, scope=W2_SCOPE, client=W3_RUNTIME, audience=W2_SERVERS_APP)
    return issue(SECRET, oid, upn, scope=W3_SCOPE, client=W3_RUNTIME, audience=W3_SERVERS_APP)


def approver_token_for(user: str) -> str:
    from approval_service import APPROVAL_APP, APPROVAL_SCOPE, TEAMS_BOT
    return issue(SECRET, OIDS[user], f"{user}@larkspur.example", scope=APPROVAL_SCOPE, client=TEAMS_BOT,
                 audience=APPROVAL_APP)


EXPORT = json.loads((W1 / "knowledge-server" / "membership" / "graph-export.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(W1 / "knowledge-server" / "membership"))
import sync as _sync  # noqa: E402
OIDS = {upn.split("@")[0]: oid for upn, oid in _sync.users(EXPORT).items()}
SERVICE_MAP = load_service_map()
APPROVERS = load_approvers()
EVERY = {s for team in SERVICE_MAP.teams.values() for s in team} | set(SERVICE_MAP.broad)


def members_by_user(table_path: Path) -> dict[str, set[str]]:
    table = MembershipTable.from_dict(json.loads(table_path.read_text(encoding="utf-8")))
    return {user: set(table.members.get(oid, set())) for user, oid in OIDS.items()}


# --- a write bridge: like chapter 5's read bridge, but the approval's number travels in _meta ---------

def write_bridge(client: Client, name: str, loop: asyncio.AbstractEventLoop, log: io.StringIO,
                 span_context: otel_context.Context | None = None):
    """One `execute_tool` span a write, under the incident's span (`span_context`), as chapter 5's bridge
    opens one a read; the MCP SDK's client span and the writer's spans sit under it."""
    def tool(args: dict[str, Any], approval_id: str) -> dict[str, Any]:
        async def go():
            trace = TRACE.get("id", "")
            attributes = {tracing.GEN_AI_OPERATION_NAME: tracing.OP_EXECUTE_TOOL, tracing.GEN_AI_TOOL_NAME: name,
                          tracing.GEN_AI_TOOL_TYPE: tracing.TOOL_TYPE_FUNCTION, tracing.LARKSPUR_COMPONENT: "harness",
                          tracing.LARKSPUR_TRACE_ID: trace}
            with tracing.start_span(f"{tracing.OP_EXECUTE_TOOL} {name}", context=span_context,
                                    attributes=attributes) as span:
                result = await client.call_tool(name, {**args}, meta={"trace_id": trace, "approval_id": approval_id})
                if result.is_error:
                    span.set_attribute(tracing.ERROR_TYPE, "tool_error")
            from client import json_line
            json_line(log, event="tool_call", tool=name, args=args, ok=not result.is_error)
            if result.is_error:
                return {"error": "".join(getattr(b, "text", "") for b in result.content)}
            return result.structured_content
        return asyncio.run_coroutine_threadsafe(go(), loop).result(timeout=120)
    return tool


TRACE: dict[str, str] = {}  # the current incident's trace id, read by the write bridge


class KeptLog(io.StringIO):
    """The harness's log for one incident: in memory for the record, and each line appended to a file beside the
    servers' logs as it is written. The logs server's line keeps `contains` only as an HMAC (W2's common.py), so
    the text of every read's arguments stays here, where an auditor who holds the key matches the two through the
    HMAC (chapter 17's rule, companion #126). Without a path it is the StringIO the run used before."""

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self.path = path

    def write(self, text: str) -> int:
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as out:
                out.write(text)
        return super().write(text)


async def run_incident(incident: dict[str, Any], gateway_url: str, servers: dict[str, int], table_path: Path,
                       approval_url: str, state_file: Path, snow_file: Path, members: dict[str, set[str]],
                       harness_log: Path | None = None) -> dict[str, Any]:
    persona = incident.get("persona", "oncall.engineer")
    token_for = {server: persona_token(persona, w2=server in W2_SERVERS) for server in servers}
    trace_id = uuid.uuid4().hex
    TRACE["id"] = trace_id
    state_file.write_text("{}", encoding="utf-8")
    snow_file.write_text("{}", encoding="utf-8")
    log = KeptLog(harness_log)
    loop = asyncio.get_running_loop()
    hidden = EVERY - SERVICE_MAP.visible(frozenset(members.get(persona, set())))
    approvals = ApprovalClient(approval_url, SERVICE_KEY, requester_upn=f"{persona}@larkspur.example")
    writer = Writer(approvals, state_file)
    attributes = {
        tracing.GEN_AI_OPERATION_NAME: tracing.OP_INVOKE_AGENT, tracing.GEN_AI_AGENT_NAME: WORKFLOW,
        tracing.GEN_AI_PROVIDER_NAME: "larkspur.gateway", tracing.GEN_AI_REQUEST_MODEL: CHAT_ALIAS,
        tracing.LARKSPUR_COMPONENT: "harness", tracing.LARKSPUR_TRACE_ID: trace_id, "larkspur.transport": "http",
    }

    # The incident's span, with the incident's trace id: the root of everything below, as W2's question and W5's
    # night are. Before it, each read and each session's set-up was a trace of its own, and each model call a root.
    with tracing.start_span(f"{tracing.OP_INVOKE_AGENT} {WORKFLOW}", trace_id=trace_id, attributes=attributes):
        span_context = otel_context.get_current()  # handed to the bridges: tool spans nest under this one
        # The span's traceparent goes in every model request beside the trace id, so the gateway's chat span lands
        # under this one; a bare trace id would make each call a root of its own.
        model = W3GatewayModel(gateway_url=gateway_url, alias="larkspur-chat", tools=_tool_specs(), api_key=GATEWAY_KEY,
                               trace_id=trace_id, traceparent=tracing.current_traceparent())
        async with AsyncExitStack() as stack:
            clients: dict[str, Client] = {}
            for server, port in servers.items():
                client = await stack.enter_async_context(Client(ActorMCP(f"http://127.0.0.1:{port}/mcp", token_for[server])))
                await client.list_tools()
                clients[server] = client
            reads: dict[str, Any] = {}
            for name in READ_TOOLS:
                client = clients[SERVER_OF[name]]
                reads[name] = bridge(client, name, trace_id, "http", log, loop, span_context)
            writes: dict[str, Any] = {name: write_bridge(clients[SERVER_OF[name]], name, loop, log, span_context)
                                      for name in MODEL_WRITES}

            def approve(approval_id: str) -> bool:
                record = approvals.get(approval_id)
                who = runner.eligible_approver(members, record["approvers"], OIDS[persona], OIDS)
                if who is None:
                    return False
                import httpx
                httpx.post(f"{approval_url}/requests/{approval_id}/decisions", json={"approved": True},
                           headers={"X-Larkspur-Actor": approver_token_for(who)}, timeout=10).raise_for_status()
                return True

            def drive() -> dict[str, Any]:
                # The machine's SQLite store is created and used in this worker thread (sqlite objects do not
                # cross threads); the bridged tools reach the loop thread through run_coroutine_threadsafe.
                machine = Machine(Machine_store(state_file.parent / f"machine-{trace_id}.sqlite"))
                services = Services(model=model, tools=reads, allowed=READ_ALLOWED, writes=writes, verify=writer.verify,
                                    approvals=approvals, rollback=writer.rollback, max_reads=8)
                harness = Harness(machine, services)
                return runner.run_one(incident, harness, model, trace_id=trace_id, requester_oid=OIDS[persona],
                                      read_log=_events(log), hidden=hidden, approve=approve)

            record = await asyncio.to_thread(drive)
    record["persona"] = persona
    record["labels"] = [[c, a] for c, a in model.labels]
    record["reads"], record["hidden_reads"] = _reads_from(log, hidden)
    return record


def Machine_store(path: Path):
    from store import Store
    return Store(path)


def _events(log: io.StringIO) -> list[dict[str, Any]]:
    out = []
    for line in log.getvalue().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _reads_from(log: io.StringIO, hidden: set[str]) -> tuple[list[str], list[str]]:
    events = _events(log)
    reads = [e["tool"] for e in events if e.get("event") == "tool_call" and e.get("ok") and e.get("tool") in READ_TOOLS]
    hidden_reads = sorted({runner._service_of(e) for e in events
                           if e.get("event") == "tool_call" and e.get("ok") and runner._service_of(e) in hidden})
    return reads, [h for h in hidden_reads if h]


def _tool_specs() -> list[dict[str, Any]]:
    from gateway_model import tool_specs
    specs: list[dict[str, Any]] = []
    for server, lock in LOCKS.items():
        here = {t for t in MANIFEST["tools"] if SERVER_OF.get(t) == server and t != "record_change"}
        if not here:
            continue
        data = json.loads(Path(lock).read_text(encoding="utf-8"))
        specs += tool_specs([e["definition"] for e in data["tools"].values()], here)
    return specs


def start_servers(table_path: Path, state_file: Path, snow_file: Path, approval_url: str,
                  out_dir: Path) -> tuple[dict[str, int], list[subprocess.Popen]]:
    procs: list[subprocess.Popen] = []
    ports: dict[str, int] = {}
    for server, script in SERVER_SCRIPT.items():
        port = free_port()
        env = {**os.environ, "TOOL_IDENTITY": SERVER_IDENTITY[server], "W2_TOKEN_SECRET": SECRET,
               "MEMBERSHIP_TABLE": str(table_path), "TOOL_LOG_FILE": str(out_dir / f"{server}.log"),
               "APPROVAL_URL": approval_url, "APPROVAL_KEY": SERVICE_KEY,
               "CLUSTER_STATE_FILE": str(state_file), "SERVICENOW_STATE_FILE": str(snow_file)}
        stderr = (out_dir / f"{server}.stderr").open("w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(script), "--port", str(port)], env=env,
                                stdout=subprocess.DEVNULL, stderr=stderr, text=True)
        procs.append(proc)
        ports[server] = port
    for server, port in ports.items():
        if not wait_port(port):
            raise RuntimeError(f"{server} did not come up on {port}; see {out_dir / f'{server}.stderr'}")
    return ports, procs


def start_gateway(config: Path, out_dir: Path) -> tuple[int, subprocess.Popen]:
    port = free_port()
    # Point the gateway's manifest loader at W3's manifest, so the grid knows w3-incident; W2's hooks
    # default MANIFEST_DIR with setdefault, so an explicit value here wins.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "LITELLM_MASTER_KEY": GATEWAY_KEY,
           "MANIFEST_DIR": str(W3 / "manifest"), "GATEWAY_LOG_FILE": str(out_dir / "gateway.jsonl")}
    # litellm sits beside the running venv's python (venv-gw/Scripts), or is named by W3_LITELLM.
    beside = Path(sys.executable).parent / "litellm.exe"
    exe = os.environ.get("W3_LITELLM") or (str(beside) if beside.exists() else "litellm")
    stderr = (out_dir / "gateway.stderr").open("w", encoding="utf-8")
    proc = subprocess.Popen([exe, "--config", str(config), "--host", "127.0.0.1", "--port", str(port)],
                            env=env, stdout=stderr, stderr=subprocess.STDOUT, text=True, cwd=str(config.parent))
    if not wait_port(port, 120):
        raise RuntimeError(f"the gateway did not come up on {port}; see {out_dir / 'gateway.stderr'}")
    return port, proc


def run_all(incidents: list[dict[str, Any]], model_tag: str = "gpt-oss-20b",
            config: Path | None = None, gateway_url: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every incident, scored. With `gateway_url` the run uses that gateway and starts none (the trace test's fake)."""
    out_dir = SCRATCH / "run"
    out_dir.mkdir(parents=True, exist_ok=True)
    table_path = fresh_table_path()
    members = members_by_user(table_path)
    state_file = SCRATCH / "cluster.json"
    snow_file = SCRATCH / "servicenow.json"
    log = io.StringIO()
    approvals_service = Service(SCRATCH / "approvals.sqlite", lambda: MembershipTable.from_dict(
        json.loads(table_path.read_text(encoding="utf-8"))), SECRET, APPROVERS, log)
    http = serve_approvals(approvals_service, SERVICE_KEY, port=free_port())
    import threading
    threading.Thread(target=http.serve_forever, daemon=True).start()
    approval_url = f"http://127.0.0.1:{http.server_address[1]}"

    gateway: subprocess.Popen | None = None
    if gateway_url is None:
        config = config or (W2 / "gateway" / "litellm.config.yaml")
        gateway_port, gateway = start_gateway(config, out_dir)
        gateway_url = f"http://127.0.0.1:{gateway_port}"
    ports, procs = start_servers(table_path, state_file, snow_file, approval_url, out_dir)
    records: list[dict[str, Any]] = []
    try:
        for incident in incidents:
            started = time.perf_counter()
            try:
                record = asyncio.run(run_incident(incident, gateway_url, ports, table_path, approval_url,
                                                  state_file, snow_file, members, out_dir / "harness.jsonl"))
            except BaseException as exc:  # recorded as a failed case; the run goes on
                import traceback
                detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]
                record = {"id": incident["id"], "triage": "", "proposal": None, "executed": False, "approved": False,
                          "labels": [], "reads": [], "hidden_reads": [], "state": "error", "error": detail}
            record["seconds"] = round(time.perf_counter() - started, 1)
            records.append(record)
            verdict = scoring.score(incident, record)
            print(f"{'PASS' if verdict['pass'] else 'FAIL'} {incident['id']} {record.get('persona',''):18s} "
                  f"{record['seconds']:6.1f}s {record['state']}", flush=True)
    finally:
        running = procs + ([gateway] if gateway is not None else [])
        for proc in running:
            proc.terminate()
        for proc in running:
            try:
                proc.wait(timeout=20)
            except Exception:
                proc.kill()
        http.shutdown()
    by_id = {c["id"]: c for c in incidents}
    results = [scoring.score(by_id[r["id"]], r) for r in records]
    return records, scoring.summarize(results)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model-tag", default="gpt-oss-20b")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--only", help="comma-separated incident IDs")
    parser.add_argument("--out", type=Path, default=HERE / "results" / "2026-11-02")
    args = parser.parse_args(argv)
    incidents = scoring.load_incidents(HERE / "incidents.yaml")
    if args.only:
        wanted = set(args.only.split(","))
        incidents = [c for c in incidents if c["id"] in wanted]
    records, summary = run_all(incidents, model_tag=args.model_tag, config=args.config)
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (args.out / f"runs-{args.model_tag}.json").write_text(
        json.dumps({"model": args.model_tag, "run_at": stamp, "summary": summary, "records": records}, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
