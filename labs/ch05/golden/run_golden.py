"""Run the part 1 harness over the golden set and report the pass rate.

Chapter 5, part 2. A golden set is the regression test for an agent: questions with known
answers, run on every change to a prompt, a tool description or a model. This runner feeds each
question to `run_harness` (the chapter 1 loop behind the part 1 MCP server) with the rule-based
model and both tools allowed, then checks two things per case: the tool call the harness logged
(name and arguments) and the exact answer. The pass rate is the number of cases with both right.

With `--gateway`, the model is not called in-process: every model call goes through the model
gateway of part 3 as a Chat Completions request (`harness/gateway_model.py`), so the run exercises
the harness, the MCP server, the gateway, the trace and the golden set together.

Run:  python run_golden.py                 # in-process server and model, no identity needed
      TOOL_IDENTITY=larkspur-ops-reader python run_golden.py --stdio
      python run_golden.py --url http://127.0.0.1:8765/mcp
      LITELLM_MASTER_KEY=... python run_golden.py --gateway http://127.0.0.1:4010
Exit status 0 means every case passed.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in ("harness", "mcp-server", "tracing"):
    if str(LAB / folder) not in sys.path:
        sys.path.insert(0, str(LAB / folder))

import client as harness  # noqa: E402
import server as mcp_server  # noqa: E402
import trace_setup as tracing  # noqa: E402
from gateway_model import GatewayModel, pinned_tool_specs  # noqa: E402
from rule_model import rule_based_model  # noqa: E402

GOLDEN_PATH = HERE / "golden-set.yaml"
RUNNER_IDENTITY = "larkspur-ops-reader"
# The golden set covers both tools, so the harness is allowed both here. The analyst, by
# contrast, is allowed one; the allowlist is the caller's decision every time.
BOTH_TOOLS: dict[str, set[str]] = {"get_pod_status": {"service"}, "get_recent_alerts": {"service", "minutes"}}


@dataclass
class CaseResult:
    id: str
    question: str
    expected_answer: str
    answer: str
    expected_calls: list[list[Any]]
    calls: list[list[Any]]
    passed: bool

    @property
    def reason(self) -> str:
        if self.passed:
            return ""
        if self.calls != self.expected_calls:
            return f"tool calls {self.calls} != expected {self.expected_calls}"
        return f"answer {self.answer!r} != expected {self.expected_answer!r}"


@dataclass
class Report:
    results: list[CaseResult]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def pass_rate(self) -> float:
        return self.passed / len(self.results) if self.results else 0.0

    def summary(self) -> str:
        return f"pass rate: {self.passed}/{len(self.results)} ({self.pass_rate:.1%})"

    def lines(self) -> list[str]:
        out = [f"{'PASS' if r.passed else 'FAIL'}  {r.id}" + (f"  {r.reason}" if not r.passed else "")
               for r in self.results]
        return out + [self.summary()]

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "total": len(self.results), "pass_rate": self.pass_rate,
                "cases": [asdict(r) | {"reason": r.reason} for r in self.results]}


def load_cases(path: Path = GOLDEN_PATH) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = data["cases"]
    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate case ids in {path}")
    for case in cases:
        if "question" not in case or "answer" not in case.get("expect", {}):
            raise ValueError(f"case {case.get('id')!r} needs a question and expect.answer")
    return cases


def expected_calls(case: dict[str, Any]) -> list[list[Any]]:
    expect = case["expect"]
    return [[expect["tool"], expect.get("args", {})]] if expect.get("tool") else []


async def run_case(server: Any, case: dict[str, Any], *, model: Callable = rule_based_model) -> CaseResult:
    log = io.StringIO()
    answer = await harness.run_harness(server, case["question"], model=model, trace_id=tracing.new_trace_id(),
                                       log=log, allowed=BOTH_TOOLS)
    entries = [json.loads(line) for line in log.getvalue().splitlines() if line.strip()]
    calls = [[e["tool"], e["args"]] for e in entries if e["event"] == "tool_call"]
    wanted = expected_calls(case)
    return CaseResult(case["id"], case["question"], case["expect"]["answer"], answer, wanted, calls,
                      passed=(answer == case["expect"]["answer"] and calls == wanted))


def inproc_server() -> Any:
    """A fresh in-process MCP server, the same code the stdio and HTTP transports serve."""
    return mcp_server.build_server(RUNNER_IDENTITY, io.StringIO(), "inproc")


async def run_golden(server_factory: Callable[[], Any] = inproc_server,
                     cases: list[dict[str, Any]] | None = None, *,
                     model: Callable = rule_based_model) -> Report:
    cases = cases if cases is not None else load_cases()
    results = [await run_case(server_factory(), case, model=model) for case in cases]
    return Report(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--stdio", action="store_true", help="launch server.py per case (needs TOOL_IDENTITY)")
    where.add_argument("--url", help="Streamable HTTP URL of a running server")
    parser.add_argument("--gateway", help="send every model call through the gateway at this URL")
    parser.add_argument("--alias", default="larkspur-chat", help="gateway alias to ask for (default larkspur-chat)")
    parser.add_argument("--json", type=Path, help="also write the full report to this file")
    args = parser.parse_args(argv)

    tracing.configure("golden-runner")
    factory: Callable[[], Any]
    if args.url:
        factory = lambda: args.url  # noqa: E731
    elif args.stdio:
        factory = harness.stdio_server
    else:
        factory = inproc_server

    model: Callable = rule_based_model
    if args.gateway:
        model = GatewayModel(args.gateway, args.alias, tools=pinned_tool_specs(harness.LOCK_PATH, set(BOTH_TOOLS)))
    report = asyncio.run(run_golden(factory, load_cases(args.golden), model=model))
    print("\n".join(report.lines()))
    if args.json:
        args.json.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    return 0 if report.pass_rate == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
