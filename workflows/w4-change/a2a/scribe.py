"""scribe: the orchestrator. Owned by the platform team. Calls the analyst, then the risk scorer, over A2A.

Chapter 13, W4-D3. The scribe is the calling workflow of chapter 5 grown up: it discovers each agent
through its Agent Card, hands it a task, follows the task to a terminal state, and keeps the artifact.
It runs under its own identity (`AGENT_IDENTITY`) and its own token (`AGENT_TOKEN`), which it sends only
to an agent whose card declares a bearer scheme and only to the origin the card came from. It calls the
analyst for the evidence, then the risk scorer with that evidence as a structured-data part, and
assembles an evidence pack. In step 3 the scribe writes the pack to ServiceNow and a pull-request
comment; in step 2 it returns the pack object. The scribe writes nothing to infrastructure and approves
nothing (W4-D6): the pack is evidence for the change advisory board.

Run:  AGENT_IDENTITY=larkspur-scribe AGENT_TOKEN=<the token the agents know> \
      python scribe.py --change claims-api#482 --out pack.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse

os.environ.setdefault("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED", "false")

import httpx  # noqa: E402
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory  # noqa: E402
from a2a.helpers import (  # noqa: E402
    get_data_parts, get_text_parts, new_data_part, new_message, new_text_message, new_text_part,
)
from a2a.types import AgentCard, GetTaskRequest, Message, Role, SendMessageRequest, Task, TaskState  # noqa: E402
from opentelemetry.trace import SpanKind  # noqa: E402

from agent_common import (  # noqa: E402
    CALLER_IDENTITY_KEY, TRACE_ID_KEY, TRACEPARENT_KEY, json_line, open_log, require_agent_identity,
    require_token, whole_numbers,
)
import trace_setup as tracing  # noqa: E402
import policy  # noqa: E402  (sibling in a2a/)

_SERVERS = Path(__file__).resolve().parents[1] / "servers"
if str(_SERVERS) not in sys.path:
    sys.path.insert(0, str(_SERVERS))
import github_fake  # noqa: E402
import servicenow_fake  # noqa: E402

AGENT_NAME = "scribe"
DEFAULT_ANALYST_URL = "http://127.0.0.1:8770"
DEFAULT_RISK_SCORER_URL = "http://127.0.0.1:8771"
REQUEST_TIMEOUT_SECONDS = 60.0


@dataclass
class TaskRun:
    task_id: str = ""
    context_id: str = ""
    states: list[str] = field(default_factory=list)
    status_messages: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    final: Task | None = None

    @property
    def final_state(self) -> str:
        return TaskState.Name(self.final.status.state) if self.final else "unknown"


def artifact_record(artifact: Any) -> dict[str, Any]:
    data = [whole_numbers(d) for d in get_data_parts(artifact.parts)]
    return {
        "artifact_id": artifact.artifact_id,
        "name": artifact.name,
        "text": "\n".join(get_text_parts(artifact.parts)),
        "data": data[0] if len(data) == 1 else data,
    }


class NoBearerScheme(Exception):
    """The agent's card declares no bearer scheme, so the scribe will not send it a token."""


class ForeignInterface(Exception):
    """The card names an interface on another origin; the token would leave for a host nobody chose."""


def same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    port = {"http": 80, "https": 443}
    return ((pa.scheme, pa.hostname, pa.port or port.get(pa.scheme))
            == (pb.scheme, pb.hostname, pb.port or port.get(pb.scheme)))


def bearer_schemes(card: AgentCard) -> list[str]:
    return [name for name, scheme in card.security_schemes.items()
            if scheme.HasField("http_auth_security_scheme")
            and scheme.http_auth_security_scheme.scheme.lower() == "bearer"]


async def discover(http: httpx.AsyncClient, url: str, log: TextIO) -> AgentCard:
    """Fetch the Agent Card from the well-known path, without credentials: the card is public."""
    card = await A2ACardResolver(http, url).get_agent_card()
    json_line(log, event="agent_card", name=card.name, version=card.version,
              skills=[skill.id for skill in card.skills],
              interfaces=[(i.protocol_binding, i.url) for i in card.supported_interfaces],
              bearer_schemes=bearer_schemes(card))
    return card


def connect(card: AgentCard, token: str, *, origin: str, traceparent: str | None = None,
            timeout: float = REQUEST_TIMEOUT_SECONDS) -> tuple[Client, httpx.AsyncClient]:
    """An A2A client whose every request carries the token, sent only to the card's own origin."""
    if not bearer_schemes(card):
        raise NoBearerScheme(f"{card.name!r} declares no bearer scheme; not sending it a token")
    foreign = [i.url for i in card.supported_interfaces if not same_origin(i.url, origin)]
    if foreign:
        raise ForeignInterface(f"{card.name!r} names interfaces outside {origin}: {foreign}")
    headers = {"Authorization": f"Bearer {token}"}
    if traceparent:
        headers["traceparent"] = traceparent
    http = httpx.AsyncClient(timeout=httpx.Timeout(timeout), headers=headers)
    return ClientFactory(ClientConfig(httpx_client=http, streaming=True)).create(card), http


async def send_task(client: Client, message: Message, metadata: dict[str, Any], log: TextIO) -> TaskRun:
    """Send one message (text, or text and a data part), follow its task to a terminal state."""
    request = SendMessageRequest(message=message)
    request.metadata.update(metadata)
    run = TaskRun()
    json_line(log, event="task_sent", **metadata)
    async for event in client.send_message(request):
        if event.HasField("task"):
            run.task_id, run.context_id = event.task.id, event.task.context_id
            run.states.append(TaskState.Name(event.task.status.state))
        elif event.HasField("status_update"):
            status = event.status_update.status
            run.states.append(TaskState.Name(status.state))
            if status.HasField("message"):
                run.status_messages.append("\n".join(get_text_parts(status.message.parts)))
        elif event.HasField("artifact_update"):
            run.artifacts.append(artifact_record(event.artifact_update.artifact))
    if run.task_id:
        run.final = await client.get_task(GetTaskRequest(id=run.task_id))
    return run


async def call_agent(url: str, message: Message, identity: str, token: str, trace_id: str,
                     traceparent: str | None, log: TextIO) -> tuple[TaskRun, AgentCard]:
    """Discover an agent, authenticate, send one task, return the run and the card."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS)) as plain:
        card = await discover(plain, url, log)
    metadata = {TRACE_ID_KEY: trace_id, CALLER_IDENTITY_KEY: identity}
    if traceparent:
        metadata[TRACEPARENT_KEY] = traceparent
    client, http = connect(card, token, origin=url, traceparent=traceparent)
    async with http:
        run = await send_task(client, message, metadata, log)
    return run, card


def _artifact_named(run: TaskRun, name: str) -> dict[str, Any] | None:
    artifacts = [artifact_record(a) for a in run.final.artifacts] if run.final else run.artifacts
    return next((a for a in artifacts if a["name"] == name), None)


async def run_scribe(change_ref: str, out: Path | None, identity: str, token: str, *,
                     analyst_url: str = DEFAULT_ANALYST_URL, risk_scorer_url: str = DEFAULT_RISK_SCORER_URL,
                     trace_id: str | None = None, log: TextIO = sys.stderr) -> dict[str, Any]:
    """Call the analyst for the evidence, the risk scorer for the class, and assemble the evidence pack."""
    attributes = {tracing.GEN_AI_OPERATION_NAME: tracing.OP_INVOKE_AGENT,
                  tracing.LARKSPUR_COMPONENT: AGENT_NAME, tracing.LARKSPUR_IDENTITY: identity}
    with tracing.start_span(f"{tracing.OP_INVOKE_AGENT} change-management", kind=SpanKind.CLIENT,
                            trace_id=trace_id, attributes=attributes) as span:
        trace_id = tracing.current_trace_id() or trace_id or tracing.new_trace_id()
        span.set_attribute(tracing.LARKSPUR_TRACE_ID, trace_id)
        traceparent = tracing.current_traceparent()

        analyst_msg = new_text_message(f"assess {change_ref}", role=Role.ROLE_USER)
        analyst_run, analyst_card = await call_agent(analyst_url, analyst_msg, identity, token,
                                                     trace_id, traceparent, log)
        evidence_rec = _artifact_named(analyst_run, "change-evidence")
        pack: dict[str, Any] = {
            "change_ref": change_ref,
            "trace_id": trace_id,
            "requested_by": identity,
            "analyst": {"name": analyst_card.name, "version": analyst_card.version, "url": analyst_url,
                        "final_state": analyst_run.final_state},
            "evidence": evidence_rec["data"] if evidence_rec else None,
            "risk_scorer": None,
            "risk": None,
            "written": False,  # step 3 writes the pack to ServiceNow and a PR comment
        }
        if evidence_rec is None or analyst_run.final_state != "TASK_STATE_COMPLETED":
            pack["status_messages"] = analyst_run.status_messages
            span.set_attribute(tracing.ERROR_TYPE, "analyst:" + analyst_run.final_state)
            json_line(log, event="pack_incomplete", trace_id=trace_id, stage="analyst",
                      final_state=analyst_run.final_state)
            return _write(pack, out, log)

        evidence = evidence_rec["data"]
        score_msg = new_message([new_data_part(evidence, media_type="application/json"),
                                 new_text_part(f"score {change_ref}")], role=Role.ROLE_USER)
        risk_run, risk_card = await call_agent(risk_scorer_url, score_msg, identity, token,
                                               trace_id, traceparent, log)
        risk_rec = _artifact_named(risk_run, "risk-score")
        pack["risk_scorer"] = {"name": risk_card.name, "version": risk_card.version, "url": risk_scorer_url,
                               "final_state": risk_run.final_state}
        pack["risk"] = risk_rec["data"] if risk_rec else None
        if risk_rec is None or risk_run.final_state != "TASK_STATE_COMPLETED":
            pack["status_messages"] = risk_run.status_messages
            span.set_attribute(tracing.ERROR_TYPE, "risk-scorer:" + risk_run.final_state)
            json_line(log, event="pack_incomplete", trace_id=trace_id, stage="risk-scorer",
                      final_state=risk_run.final_state)
            return _write(pack, out, log)

        span.set_attribute("larkspur.risk_class", pack["risk"]["risk_class"])
        json_line(log, event="pack_assembled", trace_id=trace_id, change_ref=change_ref,
                  risk_class=pack["risk"]["risk_class"], service=pack["evidence"].get("service"))
    pack["policy"] = policy.check(pack["evidence"])
    _write_pack(pack, log)
    return _write(pack, out, log)


def _write_pack(pack: dict[str, Any], log: TextIO) -> None:
    """Write the evidence pack to ServiceNow and a pull-request comment,
    when both stores are configured (W4-D7, W4-D8). W4 writes only these
    two, a ticket and a comment: never infrastructure, never a merge or
    an approval. The record is left in New/Assess for the board."""
    if not (os.environ.get("SERVICENOW_STATE_FILE", "").strip()
            and os.environ.get("GITHUB_COMMENTS_FILE", "").strip()):
        return  # no stores configured (a dry run): the pack is unwritten
    evidence, risk = pack["evidence"], pack["risk"]
    ref = pack["change_ref"]
    record = servicenow_fake.write_evidence_pack(
        change_ref=ref, service=evidence["service"],
        title=evidence["title"], pr_url=evidence.get("pr_url", ""),
        risk_class=risk["risk_class"], rationale=risk["rationale"],
        reasons=risk["reasons"],
        justification=f"Pull request {ref}: {evidence['title']}",
        implementation_plan=(f"Merge and deploy {ref} through the "
                             "production environment."),
        backout_plan=("named in the pull request"
                      if evidence.get("rollback_plan_present")
                      else "none named in the pull request"),
        assignment_group=f"{evidence['service']}-owners",
        change_class=evidence["change_class"], trace_id=pack["trace_id"],
        requested_by=pack["requested_by"], evidence=evidence,
        policy=pack["policy"])
    flags = pack["policy"]["flags"]
    comment = github_fake.upsert_pr_comment(
        ref,
        "Evidence for the change advisory board, not an approval. "
        f"Risk: {risk['risk_class']}. {risk['rationale']} "
        f"ServiceNow: {record['number']} ({record['state']}). "
        + ("Policy flags: " + "; ".join(flags) + "."
           if flags else "No policy flags."))
    pack["servicenow"] = {"number": record["number"],
                          "state": record["state"]}
    pack["pr_comment"] = {"comment_id": comment["comment_id"],
                          "updated": comment["updated"]}
    pack["written"] = True
    json_line(log, event="pack_written_to_systems",
              trace_id=pack["trace_id"], change_ref=ref,
              servicenow=record["number"])


def _write(pack: dict[str, Any], out: Path | None, log: TextIO) -> dict[str, Any]:
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
        json_line(log, event="pack_written", trace_id=pack.get("trace_id"), path=str(out))
    return pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--analyst-url", default=DEFAULT_ANALYST_URL)
    parser.add_argument("--risk-scorer-url", default=DEFAULT_RISK_SCORER_URL)
    parser.add_argument("--change", default="claims-api#482", help="a change reference, repo#number")
    parser.add_argument("--out", type=Path, default=Path("pack.json"))
    parser.add_argument("--trace-id", help="32 hex characters; generated when omitted")
    args = parser.parse_args(argv)

    identity = require_agent_identity()
    token = require_token()
    if args.trace_id and not tracing.is_trace_id(args.trace_id):
        print("refusing to run: --trace-id must be 32 lowercase hex characters", file=sys.stderr)
        return 2
    log = open_log()
    setup = tracing.configure(AGENT_NAME, identity)
    json_line(log, event="agent_start", agent=AGENT_NAME, identity=identity, tracing=setup.destination)
    pack = asyncio.run(run_scribe(args.change, args.out, identity, token, analyst_url=args.analyst_url,
                                  risk_scorer_url=args.risk_scorer_url, trace_id=args.trace_id, log=log))
    risk = pack.get("risk") or {}
    print(json.dumps({"trace_id": pack["trace_id"], "change_ref": pack["change_ref"],
                      "risk_class": risk.get("risk_class"), "written": pack["written"], "out": str(args.out)}))
    return 0 if pack.get("risk") else 1


if __name__ == "__main__":
    sys.exit(main())
