"""The hourly probe: one golden case's first model call, through the gateway, for each low-volume workflow.

Chapter 16, step 6 (companion #14, O-D12). The workbook's answer to a service with too few requests for a burn rate
to mean anything is "artificial traffic" (fact sheet 8.9). alerts.yaml names a golden case for W1, W3 and W4; once an
hour the probe sends that case's first model call through the gateway with the workflow's key and tags, as the
workflow's own model client does, and counts it good when the gateway answers 200 with a reply within the probe's
limit. It tests the model path only: the gateway, the alias and the model behind it. A workflow's tools, its
Restricted route, and the systems it writes to are outside it, which is the caution that goes with it: "if an issue
affects real users but doesn't affect artificial traffic, the successful artificial requests hide the real user
signal" (fact sheet 8.9).

The request is the case's system prompt, imported from the workflow's harness, and its question from chapter 15's
golden set (W4's: the class, reasons and change of its kept pack, in the shape its rationale seam sends), at the
class and alias the case's first call carried in the kept runs. It carries no tool definitions, so it is smaller than
the kept call; the month's cost lines carry the kept call's measured tokens (`month_cost_lines`), and a live probe's
lines carry what the gateway counted (`cost_line`). Each probe's line has the ledger's cost-line shape, with
kept_run "probe", so ledger/price.py prices it like any other line, and its trace id is new each hour and written to
the probe's log, which is how the gateway's own lines for it are told from the workflow's.

Run (from labs/ch16): python slo/probe.py w3 --gateway http://127.0.0.1:4000 --key-env W3_KEY [--every 3600]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "ledger", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import costlines  # noqa: E402
import registry  # noqa: E402

ALERTS = HERE / "alerts.yaml"
CASES = LAB.parent / "ch15" / "cases"
SOURCE = "labs/ch16/slo/probe.py"


@dataclass(frozen=True)
class ProbeCase:
    workflow: str
    gateway_workflow: str
    case: str
    kept_run: str
    alias: str
    data_class: str
    system: str
    user: str
    max_tokens: int
    input_tokens: int        # the kept first call's, measured
    output_tokens: int
    seconds: float | None
    limit_s: float


@dataclass(frozen=True)
class ProbeResult:
    workflow: str
    case: str
    trace_id: str
    ok: bool
    status: int | None
    seconds: float
    input_tokens: int | None
    output_tokens: int | None
    served_model: str | None
    reason: str


def _system(workflow: str) -> str:
    """The system prompt the workflow's first call carries, imported from its own code."""
    folders = {"w1": "workflows/w1-knowledge-assistant/harness", "w3": "workflows/w3-incident/harness",
               "w4": "workflows/w4-change/a2a"}
    with registry.isolated((folders[workflow],)):
        if workflow == "w4":
            import rationale_model
            return rationale_model.SYSTEM
        if workflow == "w3":
            import loop
            return loop.SYSTEM_PROMPT
        import answer
        return answer.SYSTEM_PROMPT


def _user(workflow: str, case: str, kept: costlines.Run) -> str:
    if workflow == "w4":
        packs = registry.read_json(registry.path(next(r for r in costlines.traced_runs("w4")
                                                      if r.model == kept.model).main))
        pack = packs[case]
        reasons = "; ".join(pack["risk"].get("reasons") or []) or "none"
        evidence = pack.get("evidence") or {}
        return (f"CLASS: {pack['risk']['risk_class']}\nREASONS: {reasons}\n"
                f"CHANGE: {pack.get('change_ref') or evidence.get('change_ref')} on {evidence.get('service')}.")
    golden = [json.loads(line) for line in (CASES / f"{workflow}.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    return next(c for c in golden if c["id"] == case)["input"]["question"]


def cases(alerts: dict[str, Any] | None = None, runs: list[costlines.Run] | None = None) -> dict[str, ProbeCase]:
    """The probe's case for each workflow alerts.yaml names, from the first kept run on the reference model that kept
    the case's first call with its tokens and time."""
    alerts = alerts or yaml.safe_load(ALERTS.read_text(encoding="utf-8"))
    runs = runs if runs is not None else costlines.collect(tuple(alerts["probe"]["workflows"]))
    out = {}
    for workflow, spec in alerts["probe"]["workflows"].items():
        kept = next(r for r in runs if r.workflow == workflow and r.case == spec["case"] and r.model == "gpt-oss-20b"
                    and r.lines and r.lines[0].input_tokens is not None and r.lines[0].duration_ms is not None)
        first = kept.lines[0]
        out[workflow] = ProbeCase(
            workflow, registry.manifest(workflow)["workflow"], spec["case"], kept.kept_run, first.alias,
            first.data_class, _system(workflow), _user(workflow, spec["case"], kept),
            max(256, 2 * int(first.output_tokens)), int(first.input_tokens), int(first.output_tokens),
            first.duration_ms / 1000, float(alerts["probe"]["limit_s"]))
    return out


def request(case: ProbeCase, trace_id: str) -> dict[str, Any]:
    """The body the probe sends: the shape the workflows' model seams send, which chapter 5's gateway reads."""
    return {"model": case.alias, "temperature": 0, "max_tokens": case.max_tokens,
            "messages": [{"role": "system", "content": case.system}, {"role": "user", "content": case.user}],
            "metadata": {"tags": [f"workflow:{case.gateway_workflow}", f"data_class:{case.data_class}"],
                         "trace_id": trace_id}}


def run_once(gateway: str, key: str, case: ProbeCase, *, trace_id: str | None = None,
             client: httpx.Client | None = None, clock: Any = time.perf_counter) -> ProbeResult:
    """One probe: good when the gateway answers 200 with a reply, within the limit."""
    trace_id = trace_id or uuid.uuid4().hex
    own = client is None
    client = client or httpx.Client(timeout=case.limit_s + 5)
    started = clock()
    try:
        resp = client.post(gateway.rstrip("/") + "/v1/chat/completions", json=request(case, trace_id),
                           headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        return ProbeResult(case.workflow, case.case, trace_id, False, None, round(clock() - started, 3), None, None,
                           None, f"no answer: {type(exc).__name__}")
    finally:
        if own:
            client.close()
    seconds = round(clock() - started, 3)
    if resp.status_code != 200:
        return ProbeResult(case.workflow, case.case, trace_id, False, resp.status_code, seconds, None, None, None,
                           f"the gateway answered {resp.status_code}")
    body = resp.json()
    usage = body.get("usage") or {}
    message = (body.get("choices") or [{}])[0].get("message") or {}
    replied = bool((message.get("content") or "").strip() or message.get("tool_calls"))
    reason = "" if replied else "an empty reply"
    if replied and seconds > case.limit_s:
        reason = f"answered in {seconds} s, over the limit of {case.limit_s:g}"
    return ProbeResult(case.workflow, case.case, trace_id, not reason, 200, seconds, usage.get("prompt_tokens"),
                       usage.get("completion_tokens"), body.get("model"), reason)


def cost_line(case: ProbeCase, result: ProbeResult) -> costlines.CostLine:
    """The probe's call as a line of the ledger's shape, with the tokens the gateway counted."""
    return costlines.CostLine(result.trace_id, result.trace_id, case.workflow, case.gateway_workflow, "probe",
                              case.case, 1, result.served_model or case.alias, "probe", case.alias, case.alias,
                              case.data_class, result.input_tokens, result.output_tokens,
                              int(result.seconds * 1000), False, SOURCE)


def month_cost_lines(case: ProbeCase, probes: list[Any]) -> list[dict[str, Any]]:
    """SIMULATED: one line per probe of the month, at the kept first call's measured tokens; a probe whose call
    failed has a line with no tokens, as the gateway's `failed` line has none."""
    out = []
    for p in probes:
        served = p.end in ("answer", "refusal", "proposal")
        line = costlines.CostLine(p.run_id, None, case.workflow, case.gateway_workflow, "probe", case.case, 1,
                                  "gpt-oss-20b", "gpt-oss-20b", case.alias, case.alias, case.data_class,
                                  case.input_tokens if served else None, case.output_tokens if served else None,
                                  int(round((p.seconds or 0) * 1000)), False, SOURCE)
        out.append({**costlines.as_record(line), "at_s": p.at, "ok": served, "simulated": True})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("workflow", choices=("w1", "w3", "w4"))
    parser.add_argument("--gateway", default=os.environ.get("PROBE_GATEWAY_URL", "http://127.0.0.1:4000"))
    parser.add_argument("--key-env", default="PROBE_KEY", help="the environment variable holding the workflow's key")
    parser.add_argument("--every", type=float, default=0, help="seconds between probes; 0 sends one and stops")
    parser.add_argument("--log", type=Path, default=HERE / "_lab" / "probe.jsonl")
    args = parser.parse_args(argv)
    case = cases()[args.workflow]
    key = os.environ[args.key_env]
    args.log.parent.mkdir(parents=True, exist_ok=True)
    while True:
        result = run_once(args.gateway, key, case)
        line = {**asdict(result), "cost_line": costlines.as_record(cost_line(case, result))}
        with args.log.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(line) + "\n")
        print(json.dumps(line))
        if not args.every:
            return 0 if result.ok else 1
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
