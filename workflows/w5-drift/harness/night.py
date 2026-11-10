"""The night: W5's harness, one scheduled run over the workspaces or one alarm's run over an account.

Chapter 14, W5-D2 and W5-D11. W5 is one harness on W2's read loop over the four read servers, with one
write at the end. A night:

1. connects to the four readers under the agent's own token (w5_access), lists each one's tools, and
   verifies every definition against that server's lock before any description could reach a model
   (chapter 5's rule, as W2's and W3's harnesses do), logging `tools_verified` per server;
   then checks GitHub itself (harness/github_check.py): the upstream App's token must carry no Contents,
   Workflows, or Administration write, and the active rules on main must require a code owner's review,
   dismiss stale approvals, and require the validate check from GitHub Actions; otherwise the night stops
   before any read, with the reasons in the record (`stopped`, `github_check`);
2. reads, through the readers' tools and nothing else, what detect/fixture_night.gather reads from the
   fakes: the state, the six describes, the tag mapping per required key, the seven-day CPU series per
   instance, the cost export of the last complete month, the standard, and the approved exceptions, and
   hands the attribution the trail lookup as a tool;
3. runs the detectors (fixture_night.findings_from, the same composition) and decides nothing itself;
4. observes the findings in the ledger, syncs the pull requests' states, realizes the savings of merged
   pull requests whose finding is gone, calls the writer with the prose seam, records the night's own
   cost from the gateway log, and saves the ledger;
5. writes the night record (out_dir/night-<date>.json) and one JSON log line per step with the trace id
   (out_dir/night-<date>.jsonl), the bridge's tool_call lines among them.

A workspace the listing does not show gets the readers' fixed refusal and no read; a read a server refused
ends that workspace with the refusal recorded; a read that failed ends it as failed; nothing is opened for
either. `run_alarm` scopes a night to the account a budget alert or an anomaly names (W5-D11, C.4): the
workspaces behind that account, with the alert's current state read through the cost reader first.

A night is one trace (chapter 16's lab, companion #14, step 3b). Its `invoke_agent w5-night` span opens
after the `night_start` line and closes before `night_done`, with the night's trace id; every read sits
under it through the bridge, as in chapter 5's harness, and every model call through the `traceparent` the
prose seam puts in the gateway request. The commands install chapter 5's tracer provider: spans go to
OTEL_EXPORTER_OTLP_ENDPOINT when it is set, and otherwise to TRACE_FILE, by default traces.jsonl in --out.

Two commands (the readers started here, as W4's eval/lab.py starts its servers):

  python -m harness.night --date 2026-11-02 --workspaces network-live,claims-api-prod,sandbox-quill
  python -m harness.night --alarm --account lm-claims-prod --alert budget:claims-monthly:FORECASTED:100

With W5_MODEL_BASE_URL set the prose seam asks chapter 5's gateway; without it the stub writes (eval/lab.py
runs the golden nights through the gateway on the two local models). W5_SERVERS (a JSON object of server
name to URL) uses readers already running.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import secrets
import sys
import time
from collections import Counter
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, TextIO

import yaml

HERE = Path(__file__).resolve().parent
W5 = HERE.parent
W1 = W5.parent / "w1-knowledge-assistant"
CH05 = W5.parents[1] / "labs" / "ch05"
for folder in (HERE, W5 / "servers", W5 / "detect", W5 / "writer", CH05 / "harness", CH05 / "tracing",
               W1 / "knowledge-server", W1 / "knowledge-server" / "membership"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import trace_setup as tracing  # noqa: E402
from actor_transport import ActorMCP  # noqa: E402
from client import LockMismatch, UnexpectedServer, bridge, json_line, read_lock, verify_tools  # noqa: E402
from mcp import Client  # noqa: E402
from opentelemetry import context as otel_context  # noqa: E402

import github_check  # noqa: E402
import github_fake  # noqa: E402
import launch  # noqa: E402
import prose  # noqa: E402
from common import NIGHT, REFUSALS, W5_AGENT_NAME, W5_AGENT_OID, mint_app_token  # noqa: E402
from drift import KIND_TYPES, live_items  # noqa: E402
from findings import Finding  # noqa: E402
from fixture_night import PAIRS, Inputs, billing_period_before, findings_from  # noqa: E402
from ledger import Ledger  # noqa: E402
from pull_requests import write_findings  # noqa: E402
from waste import IDLE_WINDOW_DAYS  # noqa: E402

__all__ = ["WORKFLOW", "READS", "WRITES", "SERVER_OF", "LOCKS", "READ_SERVERS", "DEFAULT_SERVERS", "ReadRefused", "ReadFailed",
           "night_at", "without_resources", "read_workspace", "run_night", "run_alarm", "parse_alert", "install_tracing", "main"]

MANIFEST = yaml.safe_load((W5 / "manifest" / "w5-drift.yaml").read_text(encoding="utf-8"))
CATALOG = yaml.safe_load((W5 / "catalog" / "tools.yaml").read_text(encoding="utf-8"))
WORKFLOW = MANIFEST["workflow"]
REGION = MANIFEST["regions"][0]  # the lab's one Region, where every call is served
READS: dict[str, set[str]] = {tool: set(spec["args"]) for tool, spec in MANIFEST["tools"].items() if not spec.get("writes")}
WRITES: set[str] = {tool for tool, spec in MANIFEST["tools"].items() if spec.get("writes")}
SERVER_OF: dict[str, str] = {tool: spec["server"] for tool, spec in CATALOG["tools"].items()}
READ_SERVERS = ("state-mcp", "cloud-mcp", "cost-mcp", "policy-mcp")
LOCKS = {server: W5 / "servers" / f"{server.removesuffix('-mcp')}.lock.json" for server in READ_SERVERS}
DEFAULT_SERVERS = {"state-mcp": "http://127.0.0.1:8781/mcp", "cloud-mcp": "http://127.0.0.1:8782/mcp",
                   "cost-mcp": "http://127.0.0.1:8783/mcp", "policy-mcp": "http://127.0.0.1:8784/mcp"}
KINDS = tuple(KIND_TYPES)  # the describe kinds, the cloud reader's fixed set
_ID_FIELDS = {"instances": "InstanceId", "volumes": "VolumeId", "snapshots": "SnapshotId", "security_groups": "GroupId",
              "route_tables": "RouteTableId", "load_balancers": "LoadBalancerArn"}
# What a server says when it refuses a read rather than failing one: the map's fixed sentences and the token
# check's words (W2's REFUSED_BY_SERVER, with W5's sentences).
REFUSED_BY_SERVER = tuple(sentence.lower() for sentence in REFUSALS.values()) + ("token refused", "x-larkspur-actor")
# The commands' default output: under eval/_lab, the scratch folder the repository ignores for every lab's live
# runs (W4's eval/lab.py writes there too); step 5's results go to eval/results/<date>/.
DEFAULT_OUT = Path(os.environ.get("W5_NIGHT_OUT", "").strip() or W5 / "eval" / "_lab" / "night")


class ReadRefused(Exception):
    """A server refused the read: the map, or the token. Nothing is opened for the workspace."""


class ReadFailed(Exception):
    """A read failed for a reason that is not a refusal: the night records an outage, not findings."""


def _checked(tool: Callable[..., Any], **args: Any) -> Any:
    """A bridged tool's result, or the refusal or the failure it carried, raised."""
    result = tool(**args)
    if isinstance(result, dict) and set(result) == {"error"} and isinstance(result["error"], str):
        text = result["error"]
        if any(mark in text.lower() for mark in REFUSED_BY_SERVER):
            raise ReadRefused(text)
        raise ReadFailed(text)
    return result


def night_at(day: date | str | datetime) -> datetime:
    """The night's moment: 02:00 ET on the day, the lab's fixed hour (common.NIGHT's time of day)."""
    if isinstance(day, datetime):
        return day
    when = date.fromisoformat(day) if isinstance(day, str) else day
    return datetime.combine(when, NIGHT.timetz())


def without_resources(inputs: Inputs, ids: set[str]) -> Inputs:
    """The same inputs with the named resources gone from the inventory, the tag mappings, the CPU series,
    and the state: what a later night reads after a person merged the removal and the pipeline applied it
    (the tests' second night, through a parameter rather than a second fixture)."""
    inventory = copy.deepcopy(inputs.inventory)
    for kind, result in inventory.items():
        top = next(iter(result["response"]))
        items = result["response"][top]
        if kind == "instances":
            for reservation in items:
                reservation["Instances"] = [i for i in reservation["Instances"] if i.get("InstanceId") not in ids]
        else:
            result["response"][top] = [i for i in items if i.get(_ID_FIELDS[kind]) not in ids]
    tags = copy.deepcopy(inputs.tags)
    for mapping in tags:
        entries = mapping["response"]["ResourceTagMappingList"]
        mapping["response"]["ResourceTagMappingList"] = [m for m in entries if not any(rid in m["ResourceARN"] for rid in ids)]
    state = copy.deepcopy(inputs.state)

    def strip(module: dict[str, Any]) -> None:
        module["resources"] = [r for r in module.get("resources", []) if r.get("values", {}).get("id") not in ids]
        for child in module.get("child_modules", []):
            strip(child)

    strip((state.get("state") or state)["values"]["root_module"])
    return replace(inputs, inventory=inventory, tags=tags, state=state, cpu={k: v for k, v in inputs.cpu.items() if k not in ids})


# --- the reads, through the tools ---------------------------------------------------------------------------------------

def read_workspace(tools: dict[str, Callable[..., Any]], workspace: str, account: str, night: datetime) -> Inputs:
    """What fixture_night.gather reads from the fakes, read through the readers' tools."""
    standard = _checked(tools["get_tagging_standard"])
    exceptions = _checked(tools["list_policy_exceptions"], state="approved")
    state = _checked(tools["get_state"], workspace=workspace)
    inventory = {kind: _checked(tools["describe_resources"], account=account, region=REGION, kind=kind) for kind in KINDS}
    tags = [_checked(tools["get_resources_by_tag"], account=account, region=REGION, tag_key=key) for key in standard["required_tags"]]
    cpu = {i["InstanceId"]: _checked(tools["get_cpu_utilization"], account=account, region=REGION, instance_id=i["InstanceId"],
                                     days=IDLE_WINDOW_DAYS) for i in live_items(inventory, "instances")}
    export = _checked(tools["read_cost_export"], account=account, billing_period=billing_period_before(night))
    return Inputs(workspace=workspace, account=account, state=state, inventory=inventory, tags=tags, cpu=cpu, export=export,
                  standard=standard, exceptions=exceptions, lookup=partial(_checked, tools["lookup_events"]))


def _alarm_state(tools: dict[str, Callable[..., Any]], trigger: dict[str, Any]) -> dict[str, Any]:
    """The alert's current state as the cost reader has it: the budget's notification, or the anomaly."""
    account = trigger["account"]
    try:
        if trigger["kind"] == "budget":
            budgets = _checked(tools["describe_budgets"], account=account)["response"]["Budgets"]
            named = [b for b in budgets if b["BudgetName"] in (trigger["budget"], f"{account}-{trigger['budget']}")]
            budget = named[0] if named else budgets[0] if len(budgets) == 1 else None
            if budget is None:
                return {"found": False}
            notification = next((n for n in budget["Notifications"] if n["NotificationType"] == trigger["notification_type"]
                                 and float(n["Threshold"]) == trigger["threshold"]), None)
            return {"found": True, "budget": budget["BudgetName"], "matched_by": "name" if named else "the account's one budget",
                    "notification": notification, "actual": budget["CalculatedSpend"]["ActualSpend"]["Amount"],
                    "forecasted": budget["CalculatedSpend"]["ForecastedSpend"]["Amount"], "limit": budget["BudgetLimit"]["Amount"]}
        anomalies = _checked(tools["get_anomalies"], account=account, days=90)["response"]["Anomalies"]
        hit = next((a for a in anomalies if a["AnomalyId"] == trigger["anomaly_id"]), None)
        return {"found": hit is not None, "anomaly": hit}
    except ReadRefused as exc:
        return {"found": False, "refused": str(exc)}
    except ReadFailed as exc:
        return {"found": False, "failed": str(exc)}


# --- the night ---------------------------------------------------------------------------------------------------------

@dataclass
class Config:
    servers: dict[str, str]
    token: str
    github: github_fake.GitHubFake
    ledger: Ledger
    gateway_log: Path | None
    model_client: Any = None  # an httpx.Client for the prose seam (the tests' mock transport); None for the real one
    inputs_hook: Callable[[Inputs], Inputs] | None = None


def _work(cfg: Config, tools: dict[str, Callable[..., Any]], night: datetime, workspaces: list[str], trace_id: str,
          fields: dict[str, Any], log: TextIO, record: dict[str, Any], started: float) -> None:
    """The synchronous part, in a worker thread: GitHub's check, the reads, the detectors, the ledger, the writer."""
    checked, tokens = github_check.check(cfg.github)
    record["github_check"] = checked
    json_line(log, event="github_checked", trace_id=trace_id, **fields, ok=checked["ok"], permissions=checked["permissions"],
              rules=checked["rules"], can_bypass=checked["can_bypass"], reasons=checked["reasons"])
    if not checked["ok"]:  # fail closed: nothing read, nothing written, the reasons in the record
        record["stopped"] = "the check of GitHub refused the night: " + "; ".join(checked["reasons"])
        return
    if record["trigger"].get("kind") in ("budget", "anomaly"):
        record["trigger"]["state"] = _alarm_state(tools, record["trigger"])
        json_line(log, event="alarm_read", trace_id=trace_id, **fields, **{k: v for k, v in record["trigger"].items() if k != "state"},
                  found=record["trigger"]["state"].get("found"))
    listed = _checked(tools["list_workspaces"])
    names = {w["workspace"] for w in listed["workspaces"]}
    findings: list[Finding] = []
    spend: dict[str, float] = {}
    read_ok: list[str] = []
    for workspace in workspaces:
        account = PAIRS.get(workspace)
        if workspace not in names or account is None:
            record["refused"][workspace] = REFUSALS["workspace"]
            json_line(log, event="workspace_refused", trace_id=trace_id, **fields, workspace=workspace, reason=REFUSALS["workspace"])
            continue
        try:
            inputs = read_workspace(tools, workspace, account, night)
            if cfg.inputs_hook is not None:
                inputs = cfg.inputs_hook(inputs)
            found = findings_from(inputs, night)
        except ReadRefused as exc:
            record["refused"][workspace] = str(exc)
            json_line(log, event="workspace_refused", trace_id=trace_id, **fields, workspace=workspace, reason=str(exc))
            continue
        except (ReadFailed, TimeoutError, KeyError, TypeError, ValueError) as exc:
            record["failed"][workspace] = f"{type(exc).__name__}: {exc}"[:300]
            json_line(log, event="workspace_failed", trace_id=trace_id, **fields, workspace=workspace, error=type(exc).__name__)
            continue
        spend[account] = round(sum(float(r.get("line_item_unblended_cost") or 0.0) for r in inputs.export["rows"]), 4)
        read_ok.append(workspace)
        findings += found
        json_line(log, event="workspace_findings", trace_id=trace_id, **fields, workspace=workspace, account=account,
                  findings=len(found), by_kind=dict(Counter(f.kind for f in found)))
    ledger = cfg.ledger
    ledger.observe(findings, night)
    fork_token, upstream_token = tokens[github_fake.FORK_APP], tokens[github_fake.UPSTREAM_APP]  # the checked tokens
    states = ledger.sync_pull_requests(cfg.github, upstream_token)
    realized = ledger.realize({f.key for f in findings}, night, read_ok)
    json_line(log, event="ledger_synced", trace_id=trace_id, **fields, pull_requests=len(states), realized=realized)
    # This thread runs in a copy of the night span's context, so the traceparent is the night's: the gateway puts
    # each call's span under it, where a bare trace id would make the span a root of its own.
    results = write_findings(findings, cfg.github, night=night, trace_id=trace_id,
                             prose_for=partial(prose.write, trace_id=trace_id, client=cfg.model_client,
                                               traceparent=tracing.current_traceparent()),
                             fork_token=fork_token, upstream_token=upstream_token, log=log)
    ledger.record_writes(results, night)
    duration = time.perf_counter() - started
    row = ledger.record_night(night, trace_id=trace_id, duration_s=duration, gateway_log=cfg.gateway_log, findings=findings,
                              results=results, spend=spend, workspaces=read_ok, trigger=record["trigger"], realized=realized)
    ledger.save()
    json_line(log, event="night_cost", trace_id=trace_id, **fields, gateway_calls=row["gateway_calls"],
              prompt_tokens=row["prompt_tokens"], completion_tokens=row["completion_tokens"], duration_s=row["duration_s"])
    record.update(
        findings=[asdict(f) for f in findings],
        counts={"findings": len(findings), "by_kind": row["by_kind"], "pull_requests": row["pull_requests"]},
        pull_requests=[{**asdict(r), "refused_words": list(r.refused_words)} for r in results],
        body_sources=row["body_sources"], refused_words=row["refused_words"],
        ledger={"realized": realized, "pull_request_states": states, "file": str(ledger.path)},
        cost={k: row[k] for k in ("gateway_calls", "prompt_tokens", "completion_tokens", "refused", "failed")},
        spend=spend, duration_s=round(duration, 3), workspaces_read=read_ok,
    )


async def _night(cfg: Config, night: datetime, workspaces: list[str], trace_id: str, trigger: dict[str, Any],
                 log: TextIO) -> dict[str, Any]:
    fields = {"workflow": WORKFLOW, "night": night.date().isoformat()}
    started = time.perf_counter()
    record: dict[str, Any] = {
        "night": night.date().isoformat(), "trace_id": trace_id, "trigger": trigger, "workspaces": list(workspaces),
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "agent": {"name": W5_AGENT_NAME, "oid": W5_AGENT_OID},
        "locks": {}, "refused": {}, "failed": {}, "findings": [], "pull_requests": [], "counts": {}, "cost": {},
    }
    json_line(log, event="night_start", trace_id=trace_id, **fields, trigger=trigger, workspaces=list(workspaces),
              agent=W5_AGENT_NAME, caller=W5_AGENT_OID)
    attributes = {
        tracing.GEN_AI_OPERATION_NAME: tracing.OP_INVOKE_AGENT, tracing.GEN_AI_AGENT_NAME: "w5-night",
        tracing.GEN_AI_PROVIDER_NAME: "larkspur.gateway", tracing.GEN_AI_REQUEST_MODEL: prose.ALIAS,
        tracing.LARKSPUR_COMPONENT: "harness", tracing.LARKSPUR_TRACE_ID: trace_id, "larkspur.transport": "http",
    }
    loop = asyncio.get_running_loop()
    refusal: Exception | None = None
    with tracing.start_span(f"{tracing.OP_INVOKE_AGENT} w5-night", trace_id=trace_id, attributes=attributes) as span:
        span_context = otel_context.get_current()
        async with AsyncExitStack() as stack:
            tools: dict[str, Callable[..., Any]] = {}
            for server in READ_SERVERS:  # every lock verified before any read, and before any description could reach a model
                client = await stack.enter_async_context(Client(ActorMCP(cfg.servers[server], cfg.token)))
                listing = await client.list_tools()
                allowed_here = {tool: args for tool, args in READS.items() if SERVER_OF[tool] == server}
                try:
                    hashes = verify_tools(listing.tools, read_lock(LOCKS[server]), allowed_here)
                except (LockMismatch, UnexpectedServer) as exc:
                    # Remembered and raised after the sessions close: an exception escaping `async with Client`
                    # comes back wrapped in an ExceptionGroup, and the caller should see the plain refusal.
                    refusal = exc
                    span.set_attribute(tracing.LARKSPUR_REFUSED, True)
                    json_line(log, event="refused", trace_id=trace_id, **fields, server=server, reason=str(exc))
                    break
                json_line(log, event="tools_verified", trace_id=trace_id, **fields, server=server, tools=hashes, lock=str(LOCKS[server]))
                record["locks"][server] = hashes
                for name in allowed_here:
                    tools[name] = bridge(client, name, trace_id, "http", log, loop, span_context, fields)
            if refusal is None:
                await asyncio.to_thread(_work, cfg, tools, night, workspaces, trace_id, fields, log, record, started)
    if refusal is not None:
        raise refusal
    json_line(log, event="night_done", trace_id=trace_id, **fields, duration_s=record.get("duration_s"),
              findings=record["counts"].get("findings"), pull_requests=record["counts"].get("pull_requests"))
    return record


def run_night(night_date: date | str | datetime, workspaces: list[str], out_dir: Path, *, servers: dict[str, str], token: str,
              github: github_fake.GitHubFake | None = None, ledger: Ledger | None = None, gateway_log: Path | None = None,
              model_client: Any = None, inputs_hook: Callable[[Inputs], Inputs] | None = None, trace_id: str | None = None,
              trigger: dict[str, Any] | None = None, name: str | None = None) -> dict[str, Any]:
    """One night over the workspaces. Returns the night record, also written to out_dir/<name>.json, the
    name `night-<date>` unless given (the alarm path names its own)."""
    night = night_at(night_date)
    out_dir.mkdir(parents=True, exist_ok=True)
    if github is None:
        github = github_fake.open_store(Path(os.environ.get("GITHUB_STATE_FILE", "").strip() or out_dir / "github.json"), now=night)
    github.now = night
    ledger = ledger or Ledger(Path(os.environ.get("LEDGER_FILE", "").strip() or out_dir / "ledger.json"))
    if gateway_log is None:
        gateway_log = Path(os.environ.get("GATEWAY_LOG_FILE", "").strip() or out_dir / "gateway.jsonl")
    trace_id = trace_id or tracing.new_trace_id()
    cfg = Config(servers=servers, token=token, github=github, ledger=ledger, gateway_log=gateway_log, model_client=model_client,
                 inputs_hook=inputs_hook)
    stem = name or f"night-{night.date().isoformat()}"
    with (out_dir / f"{stem}.jsonl").open("a", encoding="utf-8") as log:
        record = asyncio.run(_night(cfg, night, list(workspaces), trace_id, dict(trigger or {"kind": "schedule"}), log))
    record["record_file"] = str(out_dir / f"{stem}.json")
    record["log_file"] = str(out_dir / f"{stem}.jsonl")
    (out_dir / f"{stem}.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return record


def parse_alert(alert: str) -> dict[str, Any]:
    """`budget:<name>:<ACTUAL|FORECASTED>:<threshold>` (the aws-budget-alarm module's SNS message, C.4) or `anomaly:<id>`."""
    parts = alert.split(":")
    if parts[0] == "budget" and len(parts) == 4 and parts[2].upper() in ("ACTUAL", "FORECASTED"):
        return {"kind": "budget", "budget": parts[1], "notification_type": parts[2].upper(), "threshold": float(parts[3])}
    if parts[0] == "anomaly" and len(parts) == 2 and parts[1]:
        return {"kind": "anomaly", "anomaly_id": parts[1]}
    raise ValueError("alert must be budget:<name>:<ACTUAL|FORECASTED>:<threshold> or anomaly:<id>")


def run_alarm(account: str, alert: str, out_dir: Path, *, night_date: date | str | datetime | None = None, **kwargs: Any) -> dict[str, Any]:
    """A night scoped to the account the alert names: its workspaces, with the alert's state read first."""
    trigger = {"account": account, "alert": alert, **parse_alert(alert)}
    workspaces = [workspace for workspace, acct in PAIRS.items() if acct == account]
    night = night_at(night_date or NIGHT)
    return run_night(night, workspaces, out_dir, trigger=trigger, name=f"alarm-{night.date().isoformat()}-{account}", **kwargs)


# --- the commands -------------------------------------------------------------------------------------------------------

def install_tracing(out: Path) -> tracing.TracingSetup:
    """Chapter 5's tracer provider for the night's process, under the agent's name, so the night's span and the
    spans under it are recorded: OTLP when OTEL_EXPORTER_OTLP_ENDPOINT is set, else TRACE_FILE, by default
    traces.jsonl beside the night's record. The first call in a process wins (trace_setup.configure)."""
    environ = dict(os.environ)
    environ.setdefault(tracing.TRACE_FILE_ENV, str(out / "traces.jsonl"))
    return tracing.configure("w5-night", W5_AGENT_NAME, environ=environ)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--date", default=NIGHT.date().isoformat(), help="the night's date (the fakes are fixed at 2026-11-02)")
    parser.add_argument("--workspaces", default=",".join(PAIRS), help="comma-separated workspace names")
    parser.add_argument("--alarm", action="store_true", help="the alarm path: --account and --alert")
    parser.add_argument("--account")
    parser.add_argument("--alert")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the record, the logs, the stores, and the readers' logs go")
    args = parser.parse_args(argv)
    if args.alarm and not (args.account and args.alert):
        parser.error("--alarm needs --account and --alert")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    install_tracing(out)
    secret = os.environ.get("W5_TOKEN_SECRET", "").strip() or secrets.token_hex(32)
    readers: launch.Readers | None = None
    servers = json.loads(os.environ["W5_SERVERS"]) if os.environ.get("W5_SERVERS") else None
    if servers is None:
        readers = launch.start_readers(out / "readers", secret)
        servers = readers.urls
    token = os.environ.get("W5_TOKEN", "").strip() or mint_app_token(secret)
    try:
        if args.alarm:
            record = run_alarm(args.account, args.alert, out, night_date=args.date, servers=servers, token=token)
        else:
            record = run_night(args.date, [w.strip() for w in args.workspaces.split(",") if w.strip()], out, servers=servers, token=token)
    finally:
        if readers is not None:
            readers.stop()
    print(json.dumps({k: record.get(k) for k in ("night", "trace_id", "trigger", "workspaces", "stopped", "refused", "failed", "counts",
                                                    "body_sources", "refused_words", "cost", "duration_s", "record_file")},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
