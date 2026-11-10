"""Fake OTLP/HTTP receivers that stand in for Langfuse and CloudWatch, and read back what the Collector sent.

Chapter 16, step 3 (companion #14, O-D3, O-D4). The real backends wait for the cloud session (step 7). Until
then two small HTTP servers on 127.0.0.1 take their place: one answers on Langfuse's OTLP path
(`/api/public/otel/v1/traces`), one on CloudWatch's (`/v1/traces`). Each records every request: the time
it arrived, its path, its headers, and its spans, decoded from OTLP protobuf (gzip or not) into the flat
shape chapter 5's JSON lines file uses, with the trace state and the scope's attributes added. A receiver
can also keep the raw body, which the SigV4 check needs.

What a recording shows and what it can't: the headers the Collector sent (Langfuse's basic auth and its
ingestion header; CloudWatch's SigV4 Authorization, which `verify_sigv4` recomputes from the dummy secret)
and the spans it sent. Whether Langfuse or CloudWatch accept them, and what they show, is step 7's to see.

The module also reads the Collector's span file (`spans_from_file`: OTLP JSON, one export request a line),
so the run can set the three stores side by side.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import threading
import time
import zlib
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest, ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue

LANGFUSE_PATH = "/api/public/otel/v1/traces"
CLOUDWATCH_PATH = "/v1/traces"
KINDS = {0: "UNSPECIFIED", 1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}
STATUS = {0: "UNSET", 1: "OK", 2: "ERROR"}


# --- spans, flattened ------------------------------------------------------------------------------------

def any_value(value: AnyValue) -> Any:
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    if kind == "array_value":
        return [any_value(v) for v in value.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: any_value(kv.value) for kv in value.kvlist_value.values}
    if kind == "bytes_value":
        return value.bytes_value.hex()
    return getattr(value, kind)


def _attrs(pairs: Iterable[Any]) -> dict[str, Any]:
    return {kv.key: any_value(kv.value) for kv in pairs}


def _iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat(timespec="microseconds")


def _flat(*, name: str, trace_id: str, span_id: str, parent: str, kind: int, start: int, end: int,
          status: int, message: str, attributes: dict, events: list, resource: dict, scope: str,
          scope_attributes: dict, trace_state: str) -> dict[str, Any]:
    """One span in chapter 5's flat shape (trace_setup.span_record), plus what the Collector adds."""
    return {"name": name, "trace_id": trace_id, "span_id": span_id, "parent_span_id": parent or None,
            "kind": KINDS.get(kind, str(kind)), "start": _iso(start), "end": _iso(end), "start_ns": start,
            "end_ns": end, "status": STATUS.get(status, str(status)), "status_description": message or None,
            "attributes": attributes, "events": events, "resource": resource, "scope": scope or None,
            "scope_attributes": scope_attributes, "trace_state": trace_state}


def spans_from_request(request: ExportTraceServiceRequest) -> list[dict[str, Any]]:
    out = []
    for rs in request.resource_spans:
        resource = _attrs(rs.resource.attributes)
        for ss in rs.scope_spans:
            scope_attributes = _attrs(ss.scope.attributes)
            for s in ss.spans:
                out.append(_flat(
                    name=s.name, trace_id=s.trace_id.hex(), span_id=s.span_id.hex(), parent=s.parent_span_id.hex(),
                    kind=s.kind, start=s.start_time_unix_nano, end=s.end_time_unix_nano, status=s.status.code,
                    message=s.status.message, attributes=_attrs(s.attributes),
                    events=[{"name": e.name, "attributes": _attrs(e.attributes)} for e in s.events],
                    resource=resource, scope=ss.scope.name, scope_attributes=scope_attributes,
                    trace_state=s.trace_state))
    return out


def _json_value(value: Mapping[str, Any]) -> Any:
    """An OTLP JSON AnyValue: {"stringValue": ...}, {"intValue": "12"}, {"arrayValue": {"values": [...]}}..."""
    if not value:
        return None
    kind, inner = next(iter(value.items()))
    if kind == "intValue":
        return int(inner)
    if kind == "arrayValue":
        return [_json_value(v) for v in inner.get("values", [])]
    if kind == "kvlistValue":
        return {kv["key"]: _json_value(kv.get("value", {})) for kv in inner.get("values", [])}
    if kind == "bytesValue":
        return base64.b64decode(inner).hex()
    return inner


def _json_attrs(pairs: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    return {kv["key"]: _json_value(kv.get("value", {})) for kv in pairs or []}


def spans_from_json(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The spans of one OTLP JSON export request (what the file exporter writes on each line)."""
    out = []
    for rs in data.get("resourceSpans", []):
        resource = _json_attrs(rs.get("resource", {}).get("attributes"))
        for ss in rs.get("scopeSpans", []):
            scope = ss.get("scope", {})
            scope_attributes = _json_attrs(scope.get("attributes"))
            for s in ss.get("spans", []):
                status = s.get("status", {})
                out.append(_flat(
                    name=s.get("name", ""), trace_id=s.get("traceId", ""), span_id=s.get("spanId", ""),
                    parent=s.get("parentSpanId", ""), kind=int(s.get("kind", 0)), start=int(s.get("startTimeUnixNano", 0)),
                    end=int(s.get("endTimeUnixNano", 0)), status=int(status.get("code", 0)), message=status.get("message", ""),
                    attributes=_json_attrs(s.get("attributes")),
                    events=[{"name": e.get("name", ""), "attributes": _json_attrs(e.get("attributes"))}
                            for e in s.get("events", [])],
                    resource=resource, scope=scope.get("name", ""), scope_attributes=scope_attributes,
                    trace_state=s.get("traceState", "")))
    return out


def spans_from_file(path: Path) -> list[dict[str, Any]]:
    """Every span in the Collector's span file, in the order it was written."""
    path = Path(path)
    if not path.exists():
        return []
    return [span for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
            for span in spans_from_json(json.loads(line))]


def decode_body(body: bytes, content_encoding: str | None) -> bytes:
    encoding = (content_encoding or "").lower()
    if encoding == "gzip":
        return gzip.decompress(body)
    if encoding in {"deflate", "zlib"}:
        return zlib.decompress(body)
    if encoding not in {"", "identity"}:
        raise ValueError(f"unsupported Content-Encoding {content_encoding!r}")
    return body


# --- SigV4, recomputed ------------------------------------------------------------------------------------

def parse_sigv4(authorization: str) -> dict[str, Any]:
    """The parts of an `AWS4-HMAC-SHA256 Credential=..., SignedHeaders=..., Signature=...` header."""
    algorithm, _, rest = authorization.partition(" ")
    fields = dict(part.strip().split("=", 1) for part in rest.split(",") if "=" in part)
    key_id, date, region, service, terminal = (fields.get("Credential", "").split("/") + [""] * 5)[:5]
    return {"algorithm": algorithm, "access_key_id": key_id, "date": date, "region": region,
            "service": service, "terminal": terminal,
            "signed_headers": fields.get("SignedHeaders", "").split(";") if fields.get("SignedHeaders") else [],
            "signature": fields.get("Signature", "")}


def _sign(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).digest()


def sigv4_signature(*, method: str, path: str, query: str, headers: Mapping[str, str], body: bytes,
                    signed_headers: list[str], amz_date: str, region: str, service: str, secret_key: str) -> str:
    """The signature AWS would compute for this request (the SigV4 steps, written out)."""
    lower = {k.lower(): v for k, v in headers.items()}
    canonical_headers = "".join(f"{h}:{' '.join(str(lower.get(h, '')).split())}\n" for h in signed_headers)
    payload = lower.get("x-amz-content-sha256") or hashlib.sha256(body).hexdigest()
    pairs = sorted((quote(k, safe="-_.~"), quote(v, safe="-_.~"))
                   for k, _, v in (item.partition("=") for item in query.split("&") if item))
    canonical_query = "&".join(f"{k}={v}" for k, v in pairs)
    canonical_request = "\n".join([method, quote(path, safe="/-_.~"), canonical_query, canonical_headers,
                                   ";".join(signed_headers), payload])
    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])
    key = _sign(("AWS4" + secret_key).encode("utf-8"), amz_date[:8])
    for part in (region, service, "aws4_request"):
        key = _sign(key, part)
    return hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_sigv4(record: Mapping[str, Any], secret_key: str) -> bool:
    """Whether a recorded request's SigV4 signature is the one its headers and raw body give."""
    headers = record["headers"]
    auth = parse_sigv4(headers.get("Authorization", ""))
    body = base64.b64decode(record["body_b64"])
    expected = sigv4_signature(method=record["method"], path=record["path"], query=record.get("query", ""),
                               headers=headers, body=body, signed_headers=auth["signed_headers"],
                               amz_date=headers.get("X-Amz-Date", ""), region=auth["region"],
                               service=auth["service"], secret_key=secret_key)
    return hmac.compare_digest(expected, auth["signature"])


# --- the receivers ----------------------------------------------------------------------------------------

class Receiver(ThreadingHTTPServer):
    """One fake backend on 127.0.0.1. `records` holds every request it answered, in arrival order."""

    daemon_threads = True

    def __init__(self, name: str, path: str, *, port: int = 0, keep_raw: bool = False) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.name, self.path, self.keep_raw = name, path, keep_raw
        self.records: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self) -> Receiver:
        self._thread = threading.Thread(target=self.serve_forever, name=f"fake-{self.name}", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()

    def __enter__(self) -> Receiver:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def spans(self) -> list[dict[str, Any]]:
        with self.lock:
            return [span for record in self.records for span in record["spans"]]

    def write(self, path: Path, *, raw: bool = False) -> None:
        """Every record as one JSON line; the raw bodies only when asked."""
        with self.lock:
            records = [r if raw else {k: v for k, v in r.items() if k != "body_b64"} for r in self.records]
        Path(path).write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8", newline="\n")


class _Handler(BaseHTTPRequestHandler):
    server: Receiver

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return None  # quiet: the records are the log

    def do_POST(self) -> None:  # noqa: N802
        received = time.time()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        url = urlsplit(self.path)
        record: dict[str, Any] = {
            "receiver": self.server.name, "received_at": received, "method": "POST", "path": url.path,
            "query": url.query, "headers": dict(self.headers.items()), "body_bytes": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest(), "spans": [], "error": None,
        }
        if self.server.keep_raw:
            record["body_b64"] = base64.b64encode(body).decode("ascii")
        status = 200
        if url.path != self.server.path:
            status, record["error"] = 404, f"no route {url.path}"
        else:
            try:
                raw = decode_body(body, self.headers.get("Content-Encoding"))
                if (self.headers.get("Content-Type") or "").startswith("application/json"):
                    record["spans"] = spans_from_json(json.loads(raw))
                else:
                    request = ExportTraceServiceRequest()
                    request.ParseFromString(raw)
                    record["spans"] = spans_from_request(request)
            except Exception as exc:  # a body the fake can't read is recorded, and refused
                status, record["error"] = 400, f"{type(exc).__name__}: {exc}"
        with self.server.lock:
            self.server.records.append(record)
        payload = ExportTraceServiceResponse().SerializeToString()
        self.send_response(status)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def langfuse(port: int = 0, **kwargs: Any) -> Receiver:
    return Receiver("langfuse", LANGFUSE_PATH, port=port, **kwargs)


def cloudwatch(port: int = 0, **kwargs: Any) -> Receiver:
    return Receiver("cloudwatch", CLOUDWATCH_PATH, port=port, keep_raw=True, **kwargs)


def by_trace(spans: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for span in spans:
        out.setdefault(span["trace_id"], []).append(span)
    return out


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    path = Path(path)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)
