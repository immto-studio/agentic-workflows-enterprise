"""A change as one trace (chapter 16's lab, companion #14; the follow-up to step 3b on issue #11).

Step 3b found a change's spans in two trees: the scribe's span held the analyst's and the risk scorer's through
the `traceparent` in the A2A request, but the risk scorer's rationale call sent the gateway a bare trace id, so
the gateway's `chat` span was a root of its own. The risk scorer now hands its span's `traceparent` to the
rationale seam. This test runs a change through the scribe with the risk scorer's seam pointed at a scripted
gateway on 127.0.0.1, then opens the gateway's span from what the gateway received, by chapter 5's rule (a
`traceparent` in the metadata wins over the bare trace id), and follows every span of the change to one root."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from opentelemetry.trace import SpanKind

import risk_scorer
import scribe
import trace_setup as tracing
from a2a_support import DEVNULL, RISK_CALLERS, RISK_SCORER_IDENTITY, SCRIBE_IDENTITY, SCRIBE_TOKEN, launch, stop

pytestmark = pytest.mark.anyio

RATIONALE = "Low risk for claims-api#482 on claims-api: the checks passed and a rollback is named."


@contextmanager
def scripted_gateway() -> Iterator[tuple[str, list[dict]]]:
    """A Chat Completions endpoint on 127.0.0.1 that answers every request with one sentence; each body kept."""
    bodies: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            return None

        def do_POST(self):  # noqa: N802
            bodies.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0))))
            payload = json.dumps({"choices": [{"message": {"role": "assistant", "content": RATIONALE}}],
                                  "usage": {"prompt_tokens": 60, "completion_tokens": 20}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", bodies
    finally:
        server.shutdown()
        server.server_close()


def gateway_span(metadata: dict, folder: Path) -> dict:
    """The span chapter 5's gateway opens for a call (gateway_hooks._span), opened here from the metadata the
    scripted gateway received, on a provider of its own as the gateway's is: the traceparent there wins, else the
    bare trace id makes the span a root."""
    setup = tracing.build_provider("gateway", environ={tracing.TRACE_FILE_ENV: str(folder / "gateway-spans.jsonl")})
    span = tracing.open_span(f"{tracing.OP_CHAT} larkspur-chat", kind=SpanKind.CLIENT, traceparent=metadata.get("traceparent"),
                             trace_id=metadata["trace_id"], use_tracer=setup.provider.get_tracer(tracing.INSTRUMENTATION_NAME),
                             ignore_current=True)
    span.end()
    setup.provider.shutdown()
    [record] = tracing.read_spans(folder / "gateway-spans.jsonl")
    return record


async def test_every_span_of_a_change_has_one_root(analyst_server, trace_file: Path, tmp_path: Path) -> None:
    with scripted_gateway() as (gateway, bodies):
        risk = launch(risk_scorer, RISK_SCORER_IDENTITY, "RISK_SCORER_CALLER_TOKENS", RISK_CALLERS, tmp_path,
                      extra={"W4_MODEL_BASE_URL": gateway, "W4_MODEL_API_KEY": "sk-w4-trace-test"})
        try:
            pack = await scribe.run_scribe("claims-api#482", None, SCRIBE_IDENTITY, SCRIBE_TOKEN,
                                           analyst_url=analyst_server.url, risk_scorer_url=risk.url, log=DEVNULL)
        finally:
            stop(risk)  # the agents write each span to the session's file as it ends
    trace = pack["trace_id"]
    assert pack["risk"]["risk_class"] == "Low" and pack["risk"]["rationale"] == RATIONALE
    assert pack["risk"]["rationale_source"] == "model"

    recorded = tracing.read_spans(trace_file)
    spans = [s for s in recorded if s["trace_id"] == trace]
    # nothing of this change went to another trace: no span elsewhere names its trace id
    assert not [s for s in recorded if s["attributes"].get(tracing.LARKSPUR_TRACE_ID) == trace and s["trace_id"] != trace]
    names = {(s["name"], s["resource"]["service.name"]) for s in spans}
    assert names == {("invoke_agent change-management", "pytest"), ("invoke_agent analyst", "analyst"),
                     ("invoke_agent risk-scorer", "risk-scorer")}
    [scorer] = [s for s in spans if s["name"] == "invoke_agent risk-scorer"]

    # The rationale call: the change's trace id and the risk scorer's traceparent, beside it.
    [body] = bodies
    version, trace_part, parent, flags = body["metadata"]["traceparent"].split("-")
    assert body["metadata"]["trace_id"] == trace and (version, trace_part, parent) == ("00", trace, scorer["span_id"])
    assert int(flags, 16) & 1  # sampled

    # With the gateway's span, by chapter 5's rule, the change is one tree under the scribe's span.
    chat = gateway_span(body["metadata"], tmp_path)
    assert chat["trace_id"] == trace and chat["parent_span_id"] == scorer["span_id"]
    every = spans + [chat]
    by_id = {s["span_id"]: s for s in every}
    roots = [s for s in every if s["parent_span_id"] is None]
    assert [(r["name"], r["resource"]["service.name"]) for r in roots] == [("invoke_agent change-management", "pytest")]
    for span in every:
        current = span
        while current["parent_span_id"] is not None:
            assert current["parent_span_id"] in by_id, span["name"]
            current = by_id[current["parent_span_id"]]
        assert current is roots[0], span["name"]


def test_the_seam_puts_the_traceparent_beside_the_trace_id_and_only_when_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rationale request carries the caller's traceparent in its metadata when one is given, and the metadata
    it always carried otherwise: chapter 5's gateway reads the tags and the trace id there, and the traceparent."""
    import httpx

    import rationale_model

    sent: list[dict] = []

    def post(url, **kwargs):
        sent.append(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {"content": RATIONALE}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setenv("W4_MODEL_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setattr(httpx, "post", post)
    evidence = {"change_ref": "claims-api#482", "service": "claims-api"}
    parent = f"00-{'a' * 32}-{'b' * 16}-01"
    assert rationale_model.rationale_with_source(evidence, "Low", ["CI passed"], trace_id="a" * 32,
                                                 traceparent=parent) == (RATIONALE, "model")
    assert rationale_model.rationale(evidence, "Low", ["CI passed"], trace_id="a" * 32) == RATIONALE
    tags = ["workflow:w4-change", "data_class:internal"]
    assert sent[0]["metadata"] == {"tags": tags, "trace_id": "a" * 32, "traceparent": parent}
    assert sent[1]["metadata"] == {"tags": tags, "trace_id": "a" * 32}
