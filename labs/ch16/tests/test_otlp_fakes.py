"""The fake receivers and the SigV4 check, with no Collector: decoding OTLP, refusing what isn't OTLP, and the
signature recomputed on the CloudWatch request the local run recorded."""

from __future__ import annotations

import base64
import copy
import gzip
import json
from pathlib import Path

import httpx
from google.protobuf.json_format import MessageToDict

import fake_otlp
import otelcol
from collector_support import request, span, trace_id

LAB = Path(__file__).resolve().parents[1]
RECORDED = LAB / "results" / "2026-11-03" / "collector" / "cloudwatch-request.json"


def otlp_json(req) -> str:
    """OTLP JSON as the spec writes it: enums as integers, trace and span ids as hex (protobuf's JSON uses base64)."""
    data = MessageToDict(req, use_integers_for_enums=True)
    for rs in data.get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []):
            for s in ss.get("spans", []):
                for key in ("traceId", "spanId", "parentSpanId"):
                    if key in s:
                        s[key] = base64.b64decode(s[key]).hex()
    return json.dumps(data)


def test_the_recorded_cloudwatch_request_carries_a_sigv4_signature_the_dummy_secret_reproduces() -> None:
    record = json.loads(RECORDED.read_text(encoding="utf-8"))
    auth = fake_otlp.parse_sigv4(record["headers"]["Authorization"])
    assert auth["algorithm"] == "AWS4-HMAC-SHA256"
    assert (auth["access_key_id"], auth["region"], auth["service"], auth["terminal"]) == (
        otelcol.DUMMY_ACCESS_KEY_ID, "us-east-2", "xray", "aws4_request")
    assert auth["signed_headers"] == ["content-encoding", "content-length", "content-type", "host", "x-amz-date"]
    assert auth["date"] == record["headers"]["X-Amz-Date"][:8]
    assert fake_otlp.verify_sigv4(record, otelcol.DUMMY_SECRET_ACCESS_KEY)
    assert not fake_otlp.verify_sigv4(record, otelcol.DUMMY_SECRET_ACCESS_KEY + "x")
    tampered = copy.deepcopy(record)
    body = bytearray(base64.b64decode(tampered["body_b64"]))
    body[-1] ^= 1
    tampered["body_b64"] = base64.b64encode(bytes(body)).decode()
    assert not fake_otlp.verify_sigv4(tampered, otelcol.DUMMY_SECRET_ACCESS_KEY)
    # the signature covers the body as sent: gzip, as the exporter compresses by default
    assert record["headers"]["Content-Encoding"] == "gzip"
    assert gzip.decompress(base64.b64decode(record["body_b64"]))


def test_the_check_agrees_with_botocore_s_signer() -> None:
    """An independent signer: botocore signs a request with the dummy key, and the check accepts it."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials

    body = gzip.compress(b"spans")
    signed = AWSRequest(method="POST", url="http://127.0.0.1:4318/v1/traces?x=1", data=body,
                        headers={"Content-Type": "application/x-protobuf", "Content-Encoding": "gzip"})
    SigV4Auth(Credentials(otelcol.DUMMY_ACCESS_KEY_ID, otelcol.DUMMY_SECRET_ACCESS_KEY), "xray", "us-east-2").add_auth(signed)
    record = {"method": "POST", "path": "/v1/traces", "query": "x=1", "body_b64": base64.b64encode(body).decode(),
              "headers": {**dict(signed.headers.items()), "Host": "127.0.0.1:4318"}}
    assert "host" in fake_otlp.parse_sigv4(record["headers"]["Authorization"])["signed_headers"]
    assert fake_otlp.verify_sigv4(record, otelcol.DUMMY_SECRET_ACCESS_KEY)
    assert not fake_otlp.verify_sigv4({**record, "query": "x=2"}, otelcol.DUMMY_SECRET_ACCESS_KEY)


def test_a_receiver_decodes_gzip_protobuf_and_json_into_the_same_spans() -> None:
    t = trace_id()
    req = request([span(t, "root", attributes={"larkspur.refused": True, "n": 3, "x": 0.5}, error=True,
                        events=[("e", {"k": "v"})])], service="harness")
    with fake_otlp.langfuse() as lf:
        url = lf.url + fake_otlp.LANGFUSE_PATH
        httpx.post(url, content=gzip.compress(req.SerializeToString()), timeout=5,
                   headers={"Content-Type": "application/x-protobuf", "Content-Encoding": "gzip"}).raise_for_status()
        httpx.post(url, content=otlp_json(req).encode(), timeout=5,
                   headers={"Content-Type": "application/json"}).raise_for_status()
        refused = httpx.post(lf.url + "/v1/traces", content=req.SerializeToString(), timeout=5)
    proto, as_json = lf.records[0]["spans"], lf.records[1]["spans"]
    assert proto == as_json == fake_otlp.spans_from_request(req)
    s = proto[0]
    assert (s["trace_id"], s["status"], s["kind"], s["resource"]) == (t, "ERROR", "INTERNAL", {"service.name": "harness"})
    assert s["attributes"] == {"larkspur.refused": True, "n": 3, "x": 0.5} and s["events"] == [{"name": "e", "attributes": {"k": "v"}}]
    assert refused.status_code == 404 and lf.records[2]["error"] == "no route /v1/traces"


def test_the_span_file_reads_back_as_the_same_spans(tmp_path: Path) -> None:
    req = request([span(trace_id(), "a"), span(trace_id(), "b", attributes={"k": "v"})])
    path = tmp_path / "spans.jsonl"
    path.write_text(otlp_json(req) + "\n", encoding="utf-8")
    assert fake_otlp.spans_from_file(path) == fake_otlp.spans_from_request(req)
