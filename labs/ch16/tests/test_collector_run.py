"""The pinned Collector running config.yaml on synthetic spans: the content drop, every sampling decision, the
share each kept trace records, Langfuse's cost copy and header, CloudWatch's SigV4 signature, and what a
decision made before a trace's root arrives misses. decision_wait is 2 seconds here; the run keeps 30."""

from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

import fake_otlp
import otelcol
import policies
from collector_support import exe_or_skip, request, running, send, span, trace_id, wait_until

CONTENT = {attr: "content" for attr in policies.content_attributes() if not policies.is_template(attr)}
CONTENT["gen_ai.prompt.variable.user_name"] = "Alice"
KEEP = {"larkspur.keep": "yes", "gen_ai.tool.description": "recommended, not opt-in: kept"}
POLICY_OF = {"failed-status": "failed", "failed-error-type": "failed", "refused": "refused", "slow": "slow",
             "over-budget": "over-budget", "fallback": "fallback"}
NOT_KEPT = ("not-slow", "under-budget", "under-w3-budget")


def drop_id() -> str:
    """A trace id the share's hash drops, so only a keep-all policy can keep the trace."""
    return trace_id(kept_by_share=False)


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    exe = exe_or_skip()
    sent: dict[str, list[dict[str, Any]]] = {}

    with running(exe, tmp_path_factory.mktemp("collector-run")) as collector:
        def go(label: str, spans: list, service: str = "harness") -> None:
            req = request(spans, service)
            send(collector.url, req)
            sent.setdefault(label, []).extend(fake_otlp.spans_from_request(req))

        t, root = drop_id(), uuid.uuid4().hex[:16]
        go("content", [span(t, "root", span_id=root, attributes={**CONTENT, **KEEP, "larkspur.refused": True},
                            events=[("gen_ai.client.inference.operation.details", {**CONTENT, **KEEP})]),
                       span(t, "child without events", parent=root, attributes={**CONTENT, **KEEP})])
        go("failed-status", [span(drop_id(), "root", error=True)])
        go("failed-error-type", [span(drop_id(), "root", attributes={"error.type": "tool_error"})])
        go("refused", [span(drop_id(), "root", attributes={"larkspur.refused": True})])
        go("slow", [span(drop_id(), "root", seconds=10.5)])
        go("not-slow", [span(drop_id(), "root", seconds=10.0)])  # 10,000 ms isn't over 10,000
        go("over-budget", [span(drop_id(), "chat larkspur-chat", attributes={
            "larkspur.workflow": "w1-knowledge", "larkspur.cost_usd": 0.20})], service="gateway")  # W1's per_run_usd
        go("under-budget", [span(drop_id(), "chat larkspur-chat", attributes={
            "larkspur.workflow": "w1-knowledge", "larkspur.cost_usd": 0.1999})], service="gateway")
        go("under-w3-budget", [span(drop_id(), "chat larkspur-chat", attributes={
            "larkspur.workflow": "w3-incident", "larkspur.cost_usd": 1.99})], service="gateway")
        go("fallback", [span(drop_id(), "chat larkspur-chat", attributes={
            "larkspur.workflow": "w2-ops-assistant", "larkspur.fallback": True, "larkspur.cost_usd": 0.000412})],
           service="gateway")
        plain = [span(trace_id(), "root") for _ in range(200)]
        req = request(plain)
        send(collector.url, req)
        for s in fake_otlp.spans_from_request(req):
            sent[f"plain-{s['trace_id']}"] = [s]
        late, late_root = drop_id(), uuid.uuid4().hex[:16]
        go("late-root", [span(late, "early child", parent=late_root)])
        time.sleep(4.5)  # past the 2-second decision
        go("late-root", [span(late, "slow root", span_id=late_root, seconds=40)])

        cfg = policies.settings()
        expected = {label: policies.decide(spans[0]["trace_id"], policies.features(spans), per_run=policies.budgets(),
                                           threshold_ms=cfg["threshold_ms"], salt=cfg["salt"], percent=cfg["percent"])
                    for label, spans in sent.items() if label != "late-root"}

        def complete() -> bool:
            got = [fake_otlp.by_trace(collector.langfuse.spans()), fake_otlp.by_trace(collector.cloudwatch.spans())]
            return all(len(g.get(sent[label][0]["trace_id"], [])) == len(sent[label])
                       for g in got for label, d in expected.items() if d["kept"])

        assert wait_until(complete, 30)
        time.sleep(3)  # a late root's decision, and anything that shouldn't come
    return {"sent": sent, "expected": expected, "stores": collector.stores(),
            "langfuse": collector.langfuse.records, "cloudwatch": collector.cloudwatch.records}


def spans_in(run: dict[str, Any], store: str, label: str) -> list[dict[str, Any]]:
    return run["stores"][store].get(run["sent"][label][0]["trace_id"], [])


def test_content_is_dropped_from_spans_and_span_events_and_nothing_else(run: dict[str, Any]) -> None:
    for store in ("file", "cloudwatch", "langfuse"):
        spans = spans_in(run, store, "content")
        assert len(spans) == 2, store
        for s in spans:
            assert not [k for k in s["attributes"] if policies.is_content(k)], (store, s["name"])
            assert {k: s["attributes"][k] for k in KEEP} == KEEP
            for event in s["events"]:
                assert not [k for k in event["attributes"] if policies.is_content(k)]
                assert {k: event["attributes"][k] for k in KEEP} == KEEP
    sent = run["sent"]["content"]
    assert sum(1 for s in sent for k in s["attributes"] if policies.is_content(k)) == 2 * len(CONTENT)


@pytest.mark.parametrize("label", sorted(POLICY_OF))
def test_each_keep_all_policy_keeps_its_trace_records_itself_and_a_share_of_one(run: dict[str, Any], label: str) -> None:
    assert run["expected"][label]["policy"] == POLICY_OF[label]
    for store in ("file", "cloudwatch", "langfuse"):
        spans = spans_in(run, store, label)
        assert spans, (store, label)
        assert {s["scope_attributes"].get("tailsampling.policy") for s in spans} == {POLICY_OF[label]}
        assert {s["trace_state"] for s in spans} == {"ot=th:0"}
        assert {policies.share_from_tracestate(s["trace_state"]) for s in spans} == {1.0}


@pytest.mark.parametrize("label", NOT_KEPT)
def test_a_trace_just_short_of_a_policy_is_left_to_the_share(run: dict[str, Any], label: str) -> None:
    assert run["expected"][label]["kept"] is False
    assert not any(spans_in(run, store, label) for store in ("file", "cloudwatch", "langfuse"))


def test_the_share_of_the_rest_is_the_fnv_hash_of_the_trace_id_and_records_ten_percent(run: dict[str, Any]) -> None:
    plain = [label for label in run["sent"] if label.startswith("plain-")]
    predicted = {label for label in plain if run["expected"][label]["kept"]}
    kept = {label for label in plain if spans_in(run, "langfuse", label)}
    assert kept == predicted and 5 <= len(kept) <= 40
    for label in kept:
        s = spans_in(run, "langfuse", label)[0]
        assert s["scope_attributes"]["tailsampling.policy"] == policies.SHARE
        assert s["trace_state"] == "ot=th:e6666666666666" and policies.share_from_tracestate(s["trace_state"]) == 0.1


def test_the_same_spans_reach_the_file_cloudwatch_and_langfuse(run: dict[str, Any]) -> None:
    for label, decision in run["expected"].items():
        ids = {store: sorted(s["span_id"] for s in spans_in(run, store, label)) for store in ("file", "cloudwatch", "langfuse")}
        want = sorted(s["span_id"] for s in run["sent"][label]) if decision["kept"] else []
        assert ids == {"file": want, "cloudwatch": want, "langfuse": want}, label


def test_langfuse_alone_gets_the_gateway_s_cost_as_gen_ai_usage_cost(run: dict[str, Any]) -> None:
    for label in ("over-budget", "fallback"):
        [lf] = spans_in(run, "langfuse", label)
        assert lf["attributes"]["gen_ai.usage.cost"] == lf["attributes"]["larkspur.cost_usd"]
        for store in ("file", "cloudwatch"):
            assert "gen_ai.usage.cost" not in spans_in(run, store, label)[0]["attributes"]
    assert all("gen_ai.usage.cost" not in s["attributes"] for s in spans_in(run, "langfuse", "refused"))


def test_langfuse_gets_basic_auth_from_the_environment_and_the_v4_ingestion_header(run: dict[str, Any]) -> None:
    expected = "Basic " + base64.b64encode(f"{otelcol.DUMMY_LANGFUSE_PUBLIC_KEY}:{otelcol.DUMMY_LANGFUSE_SECRET_KEY}".encode()).decode()
    assert run["langfuse"]
    for record in run["langfuse"]:
        assert record["path"] == fake_otlp.LANGFUSE_PATH and record["error"] is None
        assert record["headers"]["Authorization"] == expected
        assert record["headers"]["X-Langfuse-Ingestion-Version"] == "4"


def test_cloudwatch_gets_a_sigv4_signature_for_xray_in_us_east_2_from_the_dummy_key(run: dict[str, Any]) -> None:
    assert run["cloudwatch"]
    for record in run["cloudwatch"]:
        auth = fake_otlp.parse_sigv4(record["headers"]["Authorization"])
        assert record["path"] == fake_otlp.CLOUDWATCH_PATH and record["error"] is None
        assert (auth["algorithm"], auth["access_key_id"], auth["region"], auth["service"], auth["terminal"]) == (
            "AWS4-HMAC-SHA256", otelcol.DUMMY_ACCESS_KEY_ID, "us-east-2", "xray", "aws4_request")
        assert {"host", "x-amz-date", "content-encoding"} <= set(auth["signed_headers"])
        assert auth["date"] == record["headers"]["X-Amz-Date"][:8] and len(auth["signature"]) == 64
        assert fake_otlp.verify_sigv4(record, otelcol.DUMMY_SECRET_ACCESS_KEY)
        assert not fake_otlp.verify_sigv4(record, "another-secret")


def test_a_root_that_arrives_after_the_decision_is_judged_without_it(run: dict[str, Any]) -> None:
    """With decision_wait and no root trigger, the policies see the spans that came first: no slow run here."""
    full = policies.features(run["sent"]["late-root"])
    assert "slow" in policies.matched(full, policies.budgets(), policies.settings()["threshold_ms"])
    assert not any(spans_in(run, store, "late-root") for store in ("file", "cloudwatch", "langfuse"))


def test_one_list_for_spans_and_span_events_would_leave_content_on_spans_without_events(tmp_path: Path) -> None:
    """Why config.yaml holds two groups: merged into one list, the statements run once per span event."""
    exe = exe_or_skip()
    cfg = yaml.safe_load(otelcol.CONFIG.read_text(encoding="utf-8"))
    groups = cfg["processors"]["transform/drop-content"]["trace_statements"]
    cfg["processors"]["transform/drop-content"]["trace_statements"] = [s for g in groups for s in g["statements"]]
    merged = tmp_path / "merged.yaml"
    merged.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    content = {"gen_ai.tool.call.arguments": '{"service": "claims-api"}', "larkspur.refused": True}
    with fake_otlp.langfuse() as lf, fake_otlp.cloudwatch() as cw:
        env = otelcol.environment(span_file=tmp_path / "spans.jsonl", langfuse_endpoint=f"{lf.url}/api/public/otel",
                                  work=tmp_path)
        extra = otelcol.overlay(otlp_port=otelcol.free_port(), cloudwatch_url=cw.url, metrics_port=otelcol.free_port(),
                                decision_wait="1s")
        with otelcol.Collector(exe, tmp_path, env, extra, config=merged) as collector:
            url = f"http://127.0.0.1:{collector.otlp_port}"
            bare, evented = drop_id(), drop_id()
            send(url, request([span(bare, "no events", attributes=content)]))
            send(url, request([span(evented, "one event", attributes=content, events=[("e", content)])]))
            assert wait_until(lambda: {bare, evented} <= set(fake_otlp.by_trace(lf.spans())), 15)
    got = fake_otlp.by_trace(lf.spans())
    assert "gen_ai.tool.call.arguments" in got[bare][0]["attributes"]          # left on the span
    assert "gen_ai.tool.call.arguments" not in got[evented][0]["attributes"]   # dropped once per event


def test_with_the_root_trigger_the_whole_trace_is_judged(tmp_path: Path) -> None:
    """decision_wait_after_root_received: the decision waits for the root, up to decision_wait."""
    exe = exe_or_skip()
    with running(exe, tmp_path, decision_wait="20s", tail={"decision_wait_after_root_received": "1s"}) as collector:
        late, root = drop_id(), uuid.uuid4().hex[:16]
        send(collector.url, request([span(late, "early child", parent=root)]))
        time.sleep(4.5)
        sent_root = time.time()
        send(collector.url, request([span(late, "slow root", span_id=root, seconds=40)]))
        assert wait_until(lambda: len(fake_otlp.by_trace(collector.langfuse.spans()).get(late, [])) == 2, 15)
        arrived = min(r["received_at"] for r in collector.langfuse.records)
    spans = collector.stores()["langfuse"][late]
    assert {s["scope_attributes"]["tailsampling.policy"] for s in spans} == {"slow"}
    assert arrived - sent_root < 5  # a second after the root, not twenty after the first span
