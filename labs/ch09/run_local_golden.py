"""The chapter 5 golden set against a real model: the local one, through the gateway.

Chapter 9, part 1. The chapter 5 runner checks exact answers, because its "model" was a set of
rules. A real model words its answers its own way, so this runner scores three things per case:

- tool: the harness made exactly the expected tool call (name and arguments), or none when none
  was expected (the request to scale a deployment);
- facts: the answer states what the tool returned. The facts come from the fake platform, not
  from the rule model's sentence: the service, the ready and desired pod counts, the number of
  alerts in the window, or that the service does not exist. A number may be written as digits or
  as a word. Numbers the question supplied (a 60-minute window) are not facts; repeating them
  proves nothing. A first version scored every number in the expected sentence and marked most
  correct answers wrong, because models do not repeat the window or the restart count;
- latency: wall time for the whole case, and the time and tokens of each model call.

It starts nothing: the gateway (labs/ch09/gateway) and the model server must already be running.

Run:  python run_local_golden.py --gateway http://127.0.0.1:4011 --alias larkspur-chat-restricted
      python run_local_golden.py --json local-golden.json
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CH05 = HERE.parent / "ch05"
for folder in ("harness", "mcp-server", "tracing", "golden"):
    if str(CH05 / folder) not in sys.path:
        sys.path.insert(0, str(CH05 / folder))
sys.path.insert(0, str(HERE))

import client as harness  # noqa: E402
import fake_platform  # noqa: E402  (chapter 5's fake namespace: where the facts come from)
import run_golden  # noqa: E402  (chapter 5: load_cases, expected_calls, inproc_server, BOTH_TOOLS)
import trace_setup as tracing  # noqa: E402
from gateway_model import GatewayModel, tool_specs  # noqa: E402  (chapter 5's adapter)

NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
NOT_FOUND = ["no deployment", "not found", "does not exist", "doesn't exist", "no such", "unknown", "not exist",
             "couldn't find", "could not find"]
NO_ALERTS = ["no alerts", "no recent alerts", "none", "no alert"]

Fact = list[str]  # acceptable ways of stating one fact; any one of them counts


ONE_ALERT = ["a single", "an alert", "a warning", "a critical", "an info"]
# Models write identifiers with typographic hyphens and quotes (gpt-oss uses U+2011, the
# non-breaking hyphen, inside service names). A person reads them as the same name; kubectl does
# not. Facts are matched after normalizing them, and the result records that it happened.
TYPOGRAPHIC = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2212": "-",
                             "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def number(n: int) -> Fact:
    return [str(n)] + ([NUMBER_WORDS[n]] if n < len(NUMBER_WORDS) else [])


def key_facts(case: dict[str, Any]) -> list[Fact]:
    """What a correct answer must state, from the fake platform the tool reads."""
    expect = case["expect"]
    args = expect.get("args") or {}
    service = args.get("service")
    if not expect.get("tool"):
        return []  # the refusal case: the tool check (no call) is the test
    if service not in fake_platform.DEPLOYMENTS:
        return [[service], NOT_FOUND]
    if expect["tool"] == "get_pod_status":
        deployment = fake_platform.DEPLOYMENTS[service]
        return [[service], number(deployment["ready"]), number(deployment["desired"])]
    count = fake_platform.recent_alerts(service, args["minutes"])["count"]
    return [[service], number(count) + (NO_ALERTS if count == 0 else []) + (ONE_ALERT if count == 1 else [])]


def states(answer: str, fact: Fact) -> bool:
    """True when the answer states the fact in any of its accepted forms, as a whole word."""
    answer = answer.translate(TYPOGRAPHIC)
    return any(re.search(rf"(?<![\w-]){re.escape(form)}(?![\w-])", answer, re.IGNORECASE) for form in fact)


@dataclass
class LocalResult:
    id: str
    question: str
    answer: str
    expected_calls: list[list[Any]]
    calls: list[list[Any]]
    facts: list[Fact]
    missing_facts: list[Fact]
    seconds: float
    model_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def typographic(self) -> bool:
        """The answer used typographic hyphens or quotes, which an identifier must not contain."""
        return self.answer != self.answer.translate(TYPOGRAPHIC)

    @property
    def tool_ok(self) -> bool:
        return self.calls == self.expected_calls

    @property
    def facts_ok(self) -> bool:
        return not self.missing_facts


async def run_case(case: dict[str, Any], gateway: str, alias: str, specs: list[dict[str, Any]]) -> LocalResult:
    trace_id = tracing.new_trace_id()
    model = GatewayModel(gateway_url=gateway, alias=alias, tools=specs, trace_id=trace_id)
    log = io.StringIO()
    started = time.perf_counter()
    answer = await harness.run_harness(run_golden.inproc_server(), case["question"], model=model,
                                       trace_id=trace_id, log=log, allowed=run_golden.BOTH_TOOLS)
    seconds = time.perf_counter() - started
    entries = [json.loads(line) for line in log.getvalue().splitlines() if line.strip()]
    calls = [[e["tool"], e["args"]] for e in entries if e["event"] == "tool_call"]
    facts = key_facts(case)
    missing = [fact for fact in facts if not states(answer, fact)]
    return LocalResult(case["id"], case["question"], answer, run_golden.expected_calls(case), calls,
                       facts, missing, seconds, [asdict(c) for c in model.calls])


def advertised_tools() -> list[dict[str, Any]]:
    server = run_golden.inproc_server()
    return tool_specs(asyncio.run(server.list_tools()))


def summarize(results: list[LocalResult]) -> dict[str, Any]:
    n = len(results)
    tool_ok = sum(r.tool_ok for r in results)
    facts_ok = sum(r.facts_ok for r in results)
    both = sum(r.tool_ok and r.facts_ok for r in results)
    latencies = [r.seconds for r in results]
    model_calls = [c for r in results for c in r.model_calls]
    return {
        "cases": n, "tool_correct": tool_ok, "facts_correct": facts_ok, "both": both,
        "typographic_answers": sum(r.typographic for r in results),
        "median_case_seconds": round(statistics.median(latencies), 2) if latencies else None,
        "p90_case_seconds": round(sorted(latencies)[max(0, int(0.9 * n) - 1)], 2) if latencies else None,
        "model_calls": len(model_calls),
        "completion_tokens": sum(c["completion_tokens"] or 0 for c in model_calls),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--gateway", default="http://127.0.0.1:4011")
    parser.add_argument("--alias", default="larkspur-chat-restricted")
    parser.add_argument("--only", help="run only the case with this id")
    parser.add_argument("--json", type=Path, help="write the full results to this file")
    args = parser.parse_args(argv)

    tracing.configure("local-golden")
    cases = run_golden.load_cases()
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    specs = advertised_tools()
    results = []
    for case in cases:
        result = asyncio.run(run_case(case, args.gateway, args.alias, specs))
        mark = ("tool ok " if result.tool_ok else "TOOL X  ") + ("facts ok" if result.facts_ok else "FACTS X ")
        print(f"{mark}  {result.seconds:6.1f}s  {result.id}: {result.answer[:110]}")
        results.append(result)
    summary = summarize(results)
    print(json.dumps(summary))
    if args.json:
        payload = {"summary": summary,
                   "results": [asdict(r) | {"tool_ok": r.tool_ok, "facts_ok": r.facts_ok,
                                            "typographic": r.typographic} for r in results]}
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
