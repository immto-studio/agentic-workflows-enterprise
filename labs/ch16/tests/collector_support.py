"""Synthetic OTLP spans, and the pinned Collector running config.yaml for a test, with the two fakes behind it.

The tests that need the binary start it the way the local run does (otelcol.py): config.yaml as it is, and an
overlay that sets the ports, points CloudWatch's exporter at its fake, and shortens decision_wait so a test
waits seconds, not half a minute. They skip when the binary isn't there (python collector/fetch.py), and fail
when it is there and isn't the pinned one.
"""

from __future__ import annotations

import functools
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status

import fake_otlp
import fetch
import otelcol
import policies


def exe_or_skip() -> Path:
    try:
        return fetch.verified()
    except FileNotFoundError:
        pytest.skip("the pinned Collector isn't here; run python collector/fetch.py once")


def kv(key: str, value: Any) -> KeyValue:
    if isinstance(value, bool):
        v = AnyValue(bool_value=value)
    elif isinstance(value, int):
        v = AnyValue(int_value=value)
    elif isinstance(value, float):
        v = AnyValue(double_value=value)
    else:
        v = AnyValue(string_value=str(value))
    return KeyValue(key=key, value=v)


def span(trace_id: str, name: str, *, parent: str | None = None, span_id: str | None = None, start: int | None = None,
         seconds: float = 0.001, attributes: Mapping[str, Any] | None = None, error: bool = False,
         events: list[tuple[str, Mapping[str, Any]]] | None = None) -> Span:
    start = start or time.time_ns()
    s = Span(trace_id=bytes.fromhex(trace_id), span_id=bytes.fromhex(span_id or uuid.uuid4().hex[:16]),
             parent_span_id=bytes.fromhex(parent) if parent else b"", name=name, kind=Span.SPAN_KIND_INTERNAL,
             start_time_unix_nano=start, end_time_unix_nano=start + int(seconds * 1e9),
             attributes=[kv(k, v) for k, v in (attributes or {}).items()],
             status=Status(code=Status.STATUS_CODE_ERROR if error else Status.STATUS_CODE_UNSET))
    for event_name, event_attributes in events or []:
        event = s.events.add()
        event.name, event.time_unix_nano = event_name, start
        event.attributes.extend(kv(k, v) for k, v in event_attributes.items())
    return s


def request(spans: list[Span], service: str = "harness") -> ExportTraceServiceRequest:
    req = ExportTraceServiceRequest()
    rs = req.resource_spans.add()
    rs.resource.attributes.extend([kv("service.name", service)])
    ss = rs.scope_spans.add()
    ss.scope.name = "larkspur.lab.ch05"
    ss.spans.extend(spans)
    return req


def send(url: str, req: ExportTraceServiceRequest) -> None:
    response = httpx.post(f"{url}/v1/traces", content=req.SerializeToString(),
                          headers={"Content-Type": "application/x-protobuf"}, timeout=10)
    response.raise_for_status()


@functools.lru_cache(maxsize=None)
def _salt() -> str:
    return policies.settings()["salt"]


def trace_id(*, kept_by_share: bool | None = None, percent: float = 10.0) -> str:
    """A fresh trace id; when asked, one the share's hash keeps, or one it doesn't, at this percentage."""
    salt = _salt()
    while True:
        candidate = uuid.uuid4().hex
        if kept_by_share is None or policies.share_keeps(candidate, salt, percent) == kept_by_share:
            return candidate


def wait_until(predicate: Callable[[], bool], seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return predicate()


class Running:
    def __init__(self, collector: otelcol.Collector, langfuse: fake_otlp.Receiver, cloudwatch: fake_otlp.Receiver,
                 span_file: Path) -> None:
        self.collector, self.langfuse, self.cloudwatch, self.span_file = collector, langfuse, cloudwatch, span_file
        self.url = f"http://127.0.0.1:{collector.otlp_port}"

    def stores(self) -> dict[str, dict[str, list[Mapping[str, Any]]]]:
        return {"file": fake_otlp.by_trace(fake_otlp.spans_from_file(self.span_file)),
                "cloudwatch": fake_otlp.by_trace(self.cloudwatch.spans()),
                "langfuse": fake_otlp.by_trace(self.langfuse.spans())}


@contextmanager
def running(exe: Path, work: Path, *, decision_wait: str = "2s", tail: Mapping[str, Any] | None = None,
            share: float | None = None) -> Iterator[Running]:
    """config.yaml with a test's overlay; the file exporter flushes on stop, so read the span file after."""
    work.mkdir(parents=True, exist_ok=True)
    with fake_otlp.langfuse() as lf, fake_otlp.cloudwatch() as cw:
        span_file = work / "spans.jsonl"
        env = otelcol.environment(span_file=span_file, langfuse_endpoint=f"{lf.url}/api/public/otel",
                                  share_percent=share, work=work)
        extra = otelcol.overlay(otlp_port=otelcol.free_port(), cloudwatch_url=cw.url, metrics_port=otelcol.free_port(),
                                decision_wait=decision_wait)
        if tail:
            extra.setdefault("processors", {}).setdefault("tail_sampling", {}).update(tail)
        collector = otelcol.Collector(exe, work, env, extra)
        with collector:
            yield Running(collector, lf, cw, span_file)
