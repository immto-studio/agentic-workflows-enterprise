"""The tracing hook: exporter selection, the JSON lines format, trace id adoption, the harness."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import yaml
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.semconv.attributes import error_attributes, server_attributes, service_attributes

import client as harness
import server as mcp_server
import trace_setup as tracing


def spans_for(trace_file: Path, trace_id: str) -> list[dict]:
    return [s for s in tracing.read_spans(trace_file) if s["trace_id"] == trace_id]


# --- attribute names ------------------------------------------------------------------------

SEMCONV = Path(__file__).resolve().parent.parent / "tracing" / "semconv-genai"


def registry(name: str) -> dict[str, dict]:
    data = yaml.safe_load((SEMCONV / name).read_text(encoding="utf-8"))
    return {attribute["key"]: attribute for attribute in data["attributes"]}


def test_genai_names_are_in_the_pinned_genai_registry() -> None:
    # The GenAI conventions live in their own repository now, with no releases, so the lab pins
    # a commit (tracing/semconv-genai/SOURCE.md). Every name the lab writes must be in that
    # registry, still "development" and not deprecated. When the copy is refreshed and a name
    # moved, was renamed or went stable, this fails, and the README table is where to say so.
    genai = registry("gen-ai-registry.yaml")
    ours = [tracing.GEN_AI_OPERATION_NAME, tracing.GEN_AI_AGENT_NAME, tracing.GEN_AI_AGENT_DESCRIPTION,
            tracing.GEN_AI_CONVERSATION_ID, tracing.GEN_AI_PROVIDER_NAME, tracing.GEN_AI_REQUEST_MODEL,
            tracing.GEN_AI_RESPONSE_MODEL, tracing.GEN_AI_TOOL_NAME, tracing.GEN_AI_TOOL_TYPE,
            tracing.GEN_AI_TOOL_CALL_ARGUMENTS, tracing.GEN_AI_USAGE_INPUT_TOKENS,
            tracing.GEN_AI_USAGE_OUTPUT_TOKENS]
    for name in ours:
        assert name in genai, name
        assert genai[name]["stability"] == "development", (name, genai[name]["stability"])
        assert "deprecated" not in genai[name], name
    operations = {m["value"] for m in genai[tracing.GEN_AI_OPERATION_NAME]["type"]["members"]}
    assert {tracing.OP_CHAT, tracing.OP_INVOKE_AGENT, tracing.OP_EXECUTE_TOOL} <= operations
    assert tracing.TOOL_TYPE_FUNCTION in genai[tracing.GEN_AI_TOOL_TYPE]["examples"]
    a2a = registry("a2a-registry.yaml")
    assert a2a[tracing.A2A_TASK_ID]["stability"] == "development"


def test_stable_names_match_the_installed_package() -> None:
    assert tracing.SERVICE_NAME == service_attributes.SERVICE_NAME
    assert tracing.SERVICE_NAMESPACE_ATTR == service_attributes.SERVICE_NAMESPACE
    assert tracing.SERVER_ADDRESS == server_attributes.SERVER_ADDRESS
    assert tracing.SERVER_PORT == server_attributes.SERVER_PORT
    assert tracing.ERROR_TYPE == error_attributes.ERROR_TYPE


# --- exporter selection ---------------------------------------------------------------------

def test_json_lines_file_is_the_default_exporter(tmp_path: Path) -> None:
    setup = tracing.build_provider("t", "nobody", environ={})
    assert isinstance(setup.exporter, tracing.JsonLinesSpanExporter)
    assert setup.destination == str(tracing.DEFAULT_TRACE_FILE)
    custom = tracing.build_provider("t", environ={"TRACE_FILE": str(tmp_path / "x.jsonl")})
    assert custom.destination == str(tmp_path / "x.jsonl")


def test_otlp_http_exporter_when_endpoint_is_set() -> None:
    setup = tracing.build_provider("t", environ={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318"})
    assert isinstance(setup.exporter, OTLPSpanExporter)
    assert setup.destination == "http://127.0.0.1:4318"
    setup.provider.shutdown()  # nothing was sent, nothing to flush


def test_spans_are_written_one_json_line_each(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    setup = tracing.build_provider("unit", "unit-identity", environ={"TRACE_FILE": str(path)})
    tracer = setup.provider.get_tracer("test")
    with tracer.start_as_current_span("outer", attributes={"k": "v"}):
        with tracer.start_as_current_span("inner"):
            pass
    inner, outer = tracing.read_spans(path)  # the inner span ends first
    assert path.read_text().count("\n") == 2
    assert (inner["name"], outer["name"]) == ("inner", "outer")
    assert inner["trace_id"] == outer["trace_id"] and inner["parent_span_id"] == outer["span_id"]
    assert outer["parent_span_id"] is None and outer["attributes"] == {"k": "v"}
    assert outer["resource"]["service.name"] == "unit"
    assert outer["resource"][tracing.LARKSPUR_IDENTITY] == "unit-identity"


WRITER = """
import sys
sys.path.insert(0, sys.argv[1])
import trace_setup as tracing
setup = tracing.build_provider(f"writer-{sys.argv[3]}", environ={"TRACE_FILE": sys.argv[2]})
tracer = setup.provider.get_tracer("writers")
for i in range(150):
    with tracer.start_as_current_span(f"span-{i}", attributes={"padding": "x" * 3000}):
        pass
setup.provider.shutdown()
"""


def test_concurrent_writers_never_split_a_line(tmp_path: Path) -> None:
    # Four processes, 150 spans each, every line over three kilobytes: what the analyst, the MCP
    # server, the gateway and the harness do to one file during a run.
    import subprocess
    import sys

    path = tmp_path / "shared.jsonl"
    tracing_dir = str(Path(tracing.__file__).resolve().parent)
    procs = [subprocess.Popen([sys.executable, "-c", WRITER, tracing_dir, str(path), str(n)]) for n in range(4)]
    reads = 0
    while any(p.poll() is None for p in procs):  # and a reader while they write, as the tests do
        tracing.read_spans(path)  # raises PermissionError if a writer's lock covered the content
        reads += 1
    assert all(p.wait(timeout=120) == 0 for p in procs)
    spans = tracing.read_spans(path)  # json.loads raises on a split line
    assert len(spans) == 600 and reads > 0


# --- trace ids ------------------------------------------------------------------------------

def test_trace_id_validation() -> None:
    assert tracing.is_trace_id(tracing.new_trace_id())
    assert not tracing.is_trace_id("demo0001")
    assert not tracing.is_trace_id("0" * 32)
    assert not tracing.is_trace_id("0AF7651916CD43DD8448EB211C80319C")  # uppercase is not W3C form


def test_an_adopted_trace_id_makes_a_real_root(trace_file: Path) -> None:
    wanted = tracing.new_trace_id()
    with tracing.start_span("adopted-root", trace_id=wanted):
        pass
    [root] = [s for s in tracing.read_spans(trace_file) if s["name"] == "adopted-root"]
    assert root["trace_id"] == wanted and root["parent_span_id"] is None


def test_open_span_takes_explicit_times(trace_file: Path) -> None:
    wanted = tracing.new_trace_id()
    span = tracing.open_span("timed", trace_id=wanted, start_time=1_700_000_000_000_000_000)
    span.end(end_time=1_700_000_000_250_000_000)
    [timed] = [s for s in tracing.read_spans(trace_file) if s["name"] == "timed"]
    assert timed["trace_id"] == wanted
    assert timed["start"].endswith("22:13:20.000000+00:00") and timed["end"].endswith("22:13:20.250000+00:00")


def test_a_bare_trace_id_is_adopted_only_outside_a_trace() -> None:
    wanted = tracing.new_trace_id()
    with tracing.start_span("root", trace_id=wanted):
        assert tracing.current_trace_id() == wanted
        with tracing.start_span("child", trace_id=tracing.new_trace_id()):
            assert tracing.current_trace_id() == wanted  # one trace cannot be two
    with tracing.start_span("other", trace_id="not-a-trace-id"):
        assert tracing.current_trace_id() != wanted  # a fresh trace, the string is just a string


def test_traceparent_round_trip(trace_file: Path) -> None:
    with tracing.start_span("caller") as caller:
        carried = tracing.current_traceparent()
        caller_id = format(caller.get_span_context().span_id, "016x")
        trace_id = tracing.current_trace_id()
    assert carried and carried.startswith(f"00-{trace_id}-{caller_id}-")
    with tracing.start_span("callee", traceparent=carried, trace_id=tracing.new_trace_id()):
        assert tracing.current_trace_id() == trace_id  # the traceparent wins over the bare id
    callee = [s for s in spans_for(trace_file, trace_id) if s["name"] == "callee"][0]
    assert callee["parent_span_id"] == caller_id


# --- content in spans -----------------------------------------------------------------------

def test_tool_arguments_stay_out_of_spans_unless_switched_on() -> None:
    args = {"service": "claims-api", "minutes": 60}
    assert tracing.tool_arguments(args, environ={}) is None
    assert tracing.tool_arguments(args, environ={tracing.TRACE_TOOL_ARGS_ENV: "0"}) is None
    for value in ("1", "true", "YES"):
        assert tracing.tool_arguments(args, environ={tracing.TRACE_TOOL_ARGS_ENV: value}) ==             '{"minutes": 60, "service": "claims-api"}'


# --- the harness and the server in one trace ------------------------------------------------

@pytest.mark.anyio
async def test_harness_and_server_spans_share_the_trace_id(trace_file: Path) -> None:
    trace_id = tracing.new_trace_id()
    server_log = io.StringIO()
    answer = await harness.run_harness(mcp_server.build_server("larkspur-ops-reader", server_log, "inproc"),
                                       trace_id=trace_id, log=io.StringIO())
    assert answer == "claims-api has 2 of 3 pods ready."

    spans = spans_for(trace_file, trace_id)
    by_name = {(s["attributes"].get(tracing.LARKSPUR_COMPONENT), s["name"]): s for s in spans}
    run = by_name[("harness", "invoke_agent harness")]
    call = by_name[("harness", "execute_tool get_pod_status")]
    served = by_name[("mcp-server", "execute_tool get_pod_status")]
    assert run["parent_span_id"] is None  # the adopted trace id makes a real root, not an orphan
    assert call["parent_span_id"] == run["span_id"]
    assert run["attributes"][tracing.GEN_AI_OPERATION_NAME] == "invoke_agent"
    assert run["attributes"][tracing.GEN_AI_REQUEST_MODEL] == "fake_model"
    assert run["attributes"][tracing.LARKSPUR_REFUSED] is False
    assert tracing.GEN_AI_TOOL_CALL_ARGUMENTS not in call["attributes"]  # content is opt-in
    # The MCP SDK's own server span sits between ours (over stdio and HTTP its client span too):
    # the server's execute_tool is a descendant of the harness's execute_tool, so the trace is one.
    ids = {s["span_id"]: s for s in spans}
    chain = [served["name"]]
    cursor = served
    while cursor["parent_span_id"] in ids and cursor["span_id"] != call["span_id"]:
        cursor = ids[cursor["parent_span_id"]]
        chain.append(cursor["name"])
    assert chain[0] == "execute_tool get_pod_status" and "tools/call get_pod_status" in chain
    assert cursor["span_id"] == call["span_id"], chain
    # And the log line on the server side carries the same id, from the request `_meta`.
    logged = [line for line in server_log.getvalue().splitlines() if '"tool_call"' in line][0]
    assert f'"trace_id": "{trace_id}"' in logged and '"trace_source": "request"' in logged
