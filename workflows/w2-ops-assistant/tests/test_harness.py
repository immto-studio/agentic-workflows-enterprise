"""W2's harness end to end over the three servers, with a scripted model behind a gateway stand-in: the
locks, the read budget, the refusal wording, the out-of-scope rule, a failed read, and the audit lines."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import AUDIT_KEY, USERS, W2, free_port, log_events, w2_token

sys.path.insert(0, str(W2 / "harness"))
import answer  # noqa: E402
from audit_hmac import text_hmac  # noqa: E402  (W1's knowledge-server folder, on the path from conftest)

GATEWAY_KEY = "sk-test-w2"
# What the scripted model does, keyed by a phrase in the question.
KEEP_READING = "(keep reading)"  # asks for another read on every call, however many results it holds
WANT_RESTART = "restart"  # the model proposes restart_deployment, which no server serves
FAIL_CHAT = "(the model is down)"
LAST_WEEK = "(last week)"  # asks for a week of alerts, which the server won't take, then for a day
SEARCH_LOGS = "(search the logs)"  # one search_logs call for SEARCHED, then the answer
SEARCHED = "Dana Whitfield"  # a search string that holds a person's name, the case chapter 17 keeps out of an audit line


@pytest.fixture(scope="session")
def fake_gateway():
    """A Chat Completions stand-in with a scripted model: pod status first, then alerts, then an answer
    that quotes the numbers; or whatever the question's phrase asks for. Records every request."""
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), **body})
            question = next(m["content"] for m in body["messages"] if m["role"] == "user")
            results = [m for m in body["messages"] if m["role"] == "tool"]
            service = next((w for w in question.lower().replace("?", "").split() if "-" in w), "claims-api")
            tools_offered = bool(body.get("tools"))
            if FAIL_CHAT in question:
                return self.reply(500, {"error": "the model is down"})
            if WANT_RESTART in question.lower() and not results:
                return self.tool_call("restart_deployment", {"service": service})
            if LAST_WEEK in question:
                if not results:
                    return self.tool_call("get_recent_alerts", {"service": service, "minutes": 10080})
                if len(results) == 1 and "error" in json.loads(results[0]["content"]):
                    return self.tool_call("get_recent_alerts", {"service": service, "minutes": 1440})
            if SEARCH_LOGS in question and not results:
                return self.tool_call("search_logs", {"service": service, "minutes": 60, "contains": SEARCHED,
                                                      "lines": 20})
            if SEARCH_LOGS not in question and (KEEP_READING in question or (tools_offered and len(results) < 2)):
                name, args = (("get_pod_status", {"service": service}) if len(results) % 2 == 0
                              else ("get_recent_alerts", {"service": service, "minutes": 60}))
                if KEEP_READING in question and len(results) >= 2:  # vary the read so the loop sees new results
                    name, args = "get_recent_events", {"service": service, "minutes": 60}
                return self.tool_call(name, args)
            summary = []
            for r in results:
                try:
                    data = json.loads(r["content"])
                except ValueError:
                    data = {}
                if "error" in data:
                    summary.append(f"a read failed: {data['error'][:60]}")
                elif "ready" in data:
                    summary.append(f"{data['service']} has {data['ready']} of {data['desired']} pods ready")
                elif "alerts" in data:
                    summary.append(f"{data['count']} alerts in {data['window_minutes']} minutes")
                elif "lines" in data:
                    summary.append(f"{data['returned']} log lines in {data['window_minutes']} minutes")
            text = "; ".join(summary) or "Nothing the assistant can read for you answers this question."
            return self.reply(200, {"choices": [{"message": {"role": "assistant", "content": text}}],
                                    "usage": {"prompt_tokens": 100, "completion_tokens": 10}})

        def tool_call(self, name: str, args: dict) -> None:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
            self.reply(200, {"choices": [{"message": message}], "usage": {"prompt_tokens": 100, "completion_tokens": 10}})

        def reply(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", free_port()), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", seen
    httpd.shutdown()


def servers_of(running_servers) -> dict[str, str]:
    return {f"{name}-mcp": url for name, (url, _) in running_servers.items()}


def ask(question: str, user: str, running_servers, fake_gateway, **token_options):
    url, _ = fake_gateway
    log = io.StringIO()
    text, model = asyncio.run(answer.ask(question, w2_token(user, **token_options), servers_of(running_servers),
                                         url, GATEWAY_KEY, log=log, audit={"case": "test", "persona": user}))
    return text, model, [json.loads(line) for line in log.getvalue().splitlines()]


def test_a_question_reads_twice_and_answers_with_the_numbers(running_servers, fake_gateway):
    text, model, events = ask("Is claims-api healthy?", "oncall.engineer", running_servers, fake_gateway)
    assert "claims-api has 2 of 3 pods ready" in text and "alerts in 60 minutes" in text
    tools = [e["tool"] for e in events if e["event"] == "tool_call"]
    assert tools == ["get_pod_status", "get_recent_alerts"]
    assert all(e["ok"] for e in events if e["event"] == "tool_call")
    verified = [e["server"] for e in events if e["event"] == "tools_verified"]
    assert sorted(verified) == ["kubernetes-mcp", "logs-mcp", "metrics-mcp"]  # every lock checked before the model
    assert model.labels and all(label == ("internal", "larkspur-chat") for label in model.labels)  # W2-D7
    trace_ids = {e["trace_id"] for e in events}
    assert len(trace_ids) == 1  # one trace through the harness and every server


def test_the_gateway_request_carries_the_class_the_workflow_and_the_trace(running_servers, fake_gateway):
    _, seen = fake_gateway
    before = len(seen)
    ask("How many pods does policy-admin have ready?", "oncall.engineer", running_servers, fake_gateway)
    request = seen[before]
    assert request["model"] == "larkspur-chat" and request["auth"] == f"Bearer {GATEWAY_KEY}"
    assert set(request["metadata"]["tags"]) == {"workflow:w2-ops-assistant", "data_class:internal"}
    assert request["messages"][0]["role"] == "system" and "quoted text" in request["messages"][0]["content"]
    offered = {t["function"]["name"] for t in request["tools"]}
    assert offered == set(answer.ALLOWED)  # the manifest's six tools, from the three locks


def test_the_read_budget_stops_a_model_that_keeps_reading(running_servers, fake_gateway):
    text, model, events = ask(f"What is going on with claims-api? {KEEP_READING}", "oncall.engineer",
                              running_servers, fake_gateway)
    reads = [e for e in events if e["event"] == "tool_call"]
    assert len(reads) == answer.MAX_READS  # four reads, then no tool offered, then the refusal
    assert answer.without_reference(text) == answer.REFUSAL and text.startswith(answer.REFUSAL)
    assert text.endswith(f"{answer.REFERENCE}{events[-1]['trace_id'][:8]}.")  # chapter 3: a refusal with a reference
    assert [e for e in events if e["event"] == "answer"][-1]["refused"] is True


def test_a_bad_argument_goes_back_to_the_model_and_costs_a_read(running_servers, fake_gateway):
    _, seen = fake_gateway
    before = len(seen)
    text, _, events = ask(f"Any alerts on notification-gateway? {LAST_WEEK}", "oncall.engineer",
                          running_servers, fake_gateway)
    reads = [e for e in events if e["event"] == "tool_call"]
    assert [r["ok"] for r in reads] == [False, True]  # the week was refused as a bad argument, the day read
    assert text != answer.READ_FAILED and "bad argument" in text and "0 alerts in 1440 minutes" in text
    assert len(seen) - before == 3  # the read, the corrected read, the answer


def test_a_call_the_manifest_doesnt_allow_is_refused_by_the_loop(running_servers, fake_gateway):
    text, _, events = ask("Please restart claims-api", "oncall.engineer", running_servers, fake_gateway)
    assert answer.without_reference(text) == answer.REFUSAL  # run_agent's "Refused: ..." reworded
    assert not [e for e in events if e["event"] == "tool_call"]  # no server was asked


def test_a_service_the_engineer_may_not_see_reads_as_a_refusal_not_an_error(running_servers, fake_gateway):
    _, seen = fake_gateway
    before = len(seen)
    text, _, events = ask("Is fraud-scoring healthy?", "oncall.engineer", running_servers, fake_gateway)
    reads = [e for e in events if e["event"] == "tool_call"]
    assert reads and not reads[0]["ok"]  # the server refused: the on-call engineer doesn't hold incident response
    assert answer.without_reference(text) == answer.REFUSAL  # the harness's sentence, not the server's, not an outage
    assert len(seen) - before == 1  # one model call proposed the read; none saw the refusal


def test_an_out_of_scope_question_is_refused_before_any_call(running_servers, fake_gateway):
    _, seen = fake_gateway
    before = len(seen)
    text, _, events = ask("What happened to claim CLM-2026-118842?", "oncall.engineer", running_servers, fake_gateway)
    assert answer.without_reference(text) == answer.REFUSAL
    assert len(seen) == before and not [e for e in events if e["event"] == "tool_call"]
    assert [e for e in events if e["event"] == "answer"][-1]["reason"] == "out of scope"


def test_a_token_for_w1s_server_gets_no_reads_and_the_refusal(running_servers, fake_gateway):
    from access import issue
    from conftest import SECRET
    url, _ = fake_gateway
    w1_shaped = issue(SECRET, USERS["oncall.engineer"], "x")
    log = io.StringIO()
    text, _ = asyncio.run(answer.ask("Is claims-api healthy?", w1_shaped, servers_of(running_servers), url,
                                     GATEWAY_KEY, log=log))
    events = [json.loads(line) for line in log.getvalue().splitlines()]
    assert all(not e["ok"] for e in events if e["event"] == "tool_call")  # every read refused by the servers
    assert answer.without_reference(text) == answer.REFUSAL


def test_a_timed_out_read_goes_back_to_the_model_as_a_result():
    def slow(**args):
        raise TimeoutError("the bridge's wait ran out")

    log = io.StringIO()
    tool = answer.timeout_as_result(slow, "get_pod_logs", "abc123def456", log, {"case": "test"})
    result = tool(service="claims-api", minutes=1440, lines=200)
    assert result["error"].startswith(answer.TIMED_OUT)
    assert answer.timed_out(result) and not answer.read_failed([{"role": "tool", "content": json.dumps(result)}])
    line = json.loads(log.getvalue())
    assert line["event"] == "tool_call" and line["ok"] is False and line["error"].startswith(answer.TIMED_OUT)


def test_a_failed_model_call_raises_rather_than_answering(running_servers, fake_gateway):
    with pytest.raises(Exception):
        ask(f"Is claims-api healthy? {FAIL_CHAT}", "oncall.engineer", running_servers, fake_gateway)


def test_the_audit_lines_hold_arguments_and_never_a_results_text(running_servers, fake_gateway):
    _, _, events = ask("Is claims-api healthy?", "oncall.engineer", running_servers, fake_gateway)
    for e in events:
        if e["event"] == "tool_call":
            assert set(e["args"]) <= {"service", "minutes", "lines", "contains", "metric"}
            assert "ready" not in json.dumps(e) and "summary" not in json.dumps(e)
    assert all(e.get("workflow") == "w2-ops-assistant" for e in events if e["event"] != "tools_verified")


def test_the_logs_servers_line_keeps_an_hmac_of_the_search_string_the_harnesss_log_keeps(running_servers, fake_gateway):
    # Chapter 17's rule (companion #126): `contains` is text, so the logs server keeps it only as an HMAC under the
    # audit key; the harness's log keeps the text, and an auditor with the key matches the two on the trace id.
    text, model, events = ask(f"Did claims-api log anything about {SEARCHED}? {SEARCH_LOGS}", "oncall.engineer",
                              running_servers, fake_gateway)
    assert "log lines in 60 minutes" in text
    [kept] = [e for e in events if e["event"] == "tool_call" and e["tool"] == "search_logs"]
    assert kept["args"]["contains"] == SEARCHED and kept["trace_id"] == model.trace_id
    _, log = running_servers["logs"]
    [audited] = [e for e in log_events(log) if e["event"] == "tool_call" and e["trace_id"] == model.trace_id]
    key = AUDIT_KEY.encode()
    # The service, the window, and the line count as they are; the search string as its HMAC, the full digest.
    assert audited["args"] == {"service": "claims-api", "minutes": 60, "lines": 20,
                               "contains": text_hmac(kept["args"]["contains"], key)}
    assert audited["args"]["contains"] != text_hmac(SEARCHED, b"another audit key, also 32 bytes or more")
    assert audited["ok"] is True and audited["caller"] == USERS["oncall.engineer"]
    line = json.dumps(audited).lower()
    assert not any(part in line for part in SEARCHED.lower().split())  # no part of the text in clear
