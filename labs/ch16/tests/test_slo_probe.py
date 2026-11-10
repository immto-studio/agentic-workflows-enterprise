"""Step 6's hourly probe against a fake model on 127.0.0.1: what it sends, how it judges the answer, and its cost
lines in the ledger's shape."""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import costlines
import price
import probe
import registry

LAB = Path(__file__).resolve().parents[1]


class FakeModel:
    """An OpenAI-shaped chat endpoint that records each request and answers as told."""

    def __init__(self, status: int = 200, content: str = "claims-api is healthy.", usage=(120, 12)) -> None:
        self.status, self.content, self.usage, self.requests = status, content, usage, []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                payload = {"model": body["model"], "choices": [{"message": {"role": "assistant",
                                                                            "content": fake.content}}],
                           "usage": {"prompt_tokens": fake.usage[0], "completion_tokens": fake.usage[1]}}
                data = json.dumps(payload).encode() if fake.status == 200 else b'{"error": "down"}'
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(scope="module")
def cases():
    return probe.cases()


@pytest.fixture
def fake():
    model = FakeModel()
    yield model
    model.close()


def test_each_probe_case_is_a_kept_first_call_on_the_managed_alias(cases):
    assert sorted(cases) == ["w1", "w3", "w4"]
    for workflow, case in cases.items():
        assert case.alias == "larkspur-chat" and case.input_tokens > 0 and case.output_tokens > 0
        assert case.gateway_workflow == registry.manifest(workflow)["workflow"]
        assert case.limit_s == 30
    assert cases["w3"].user == "Is policy-admin healthy?"
    assert cases["w4"].user.startswith("CLASS: Low\nREASONS: ")
    with registry.isolated(("workflows/w3-incident/harness",)):
        import loop
        assert cases["w3"].system == loop.SYSTEM_PROMPT


def test_the_probe_sends_the_workflows_tags_and_a_trace_id_and_counts_a_reply_good(cases, fake):
    result = probe.run_once(fake.url, "sk-lab-probe", cases["w3"], trace_id="ab" * 16)
    assert result.ok and result.status == 200 and result.reason == ""
    assert (result.input_tokens, result.output_tokens, result.served_model) == (120, 12, "larkspur-chat")
    sent = fake.requests[0]
    assert sent["path"] == "/v1/chat/completions" and sent["auth"] == "Bearer sk-lab-probe"
    body = sent["body"]
    assert body["model"] == "larkspur-chat" and body["max_tokens"] == cases["w3"].max_tokens
    assert body["metadata"] == {"tags": ["workflow:w3-incident", "data_class:confidential"], "trace_id": "ab" * 16}
    assert [m["role"] for m in body["messages"]] == ["system", "user"] and "tools" not in body


@pytest.mark.parametrize("status,content,reason", [(500, "", "the gateway answered 500"),
                                                   (429, "", "the gateway answered 429"),
                                                   (200, "  ", "an empty reply")])
def test_a_failed_or_empty_answer_is_a_bad_probe(cases, status, content, reason):
    model = FakeModel(status=status, content=content)
    try:
        result = probe.run_once(model.url, "k", cases["w1"])
    finally:
        model.close()
    assert not result.ok and result.reason == reason


def test_an_answer_over_the_limit_is_a_bad_probe(cases, fake):
    ticks = iter([0.0, 31.5])
    result = probe.run_once(fake.url, "k", cases["w4"], clock=lambda: next(ticks))
    assert not result.ok and result.seconds == 31.5 and "over the limit of 30" in result.reason


def test_no_gateway_at_all_is_a_bad_probe(cases):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    result = probe.run_once(f"http://127.0.0.1:{port}", "k", cases["w1"])
    assert not result.ok and result.status is None and result.reason.startswith("no answer")


def test_a_probes_cost_line_is_the_ledgers_shape_and_priced_like_any_line(cases, fake, table):
    result = probe.run_once(fake.url, "k", cases["w1"], trace_id="cd" * 16)
    line = probe.cost_line(cases["w1"], result)
    assert isinstance(line, costlines.CostLine) and line.kept_run == "probe" and line.run_id == "cd" * 16
    nova = price.deployment(table, "larkspur-chat")
    assert price.line_cost(table, line) == 120 * price.per_token(nova["input_per_million"]) \
        + 12 * price.per_token(nova["output_per_million"])


def test_the_months_probe_lines_carry_the_kept_tokens_and_none_for_a_failed_call(cases, month, table):
    w4 = [p for p in month.probes if p.workflow == "w4" and p.at >= 0]
    lines = probe.month_cost_lines(cases["w4"], w4)
    assert len(lines) == 720 and all(line["simulated"] for line in lines)
    failed = [line for line in lines if not line["ok"]]
    assert len(failed) == 1 and failed[0]["input_tokens"] is None
    served = [line for line in lines if line["ok"]]
    assert {(line["input_tokens"], line["output_tokens"]) for line in served} == {(200, 253)}
    fields = {k: v for k, v in served[0].items() if k in costlines.CostLine.__dataclass_fields__}
    assert price.line_cost(table, costlines.CostLine(**fields)) > Decimal(0)
