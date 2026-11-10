"""config.yaml: the binary's own validation, the content drop against the pinned conventions and the manifests,
the policies against the manifests, the three exporters, and the pinned binary itself."""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest
import yaml

import fetch
import otelcol
import policies
from collector_support import exe_or_skip

CFG = policies.config()


def env(tmp_path: Path) -> dict[str, str]:
    return otelcol.environment(span_file=tmp_path / "spans.jsonl", langfuse_endpoint="http://127.0.0.1:9/api/public/otel",
                               work=tmp_path)


# --- the binary's own checks ---------------------------------------------------------------------------------

def test_the_binary_validates_the_config(tmp_path: Path) -> None:
    result = otelcol.validate(exe_or_skip(), env(tmp_path), otelcol.CONFIG)
    assert result.returncode == 0, result.stdout + result.stderr


def test_validation_rejects_a_statement_that_does_not_parse(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(otelcol.CONFIG.read_text(encoding="utf-8").replace("delete_key(span.attributes", "delete_kye(span.attributes", 1),
                   encoding="utf-8")
    result = otelcol.validate(exe_or_skip(), env(tmp_path), bad)
    assert result.returncode != 0 and "delete_kye" in result.stdout + result.stderr


def test_validation_misses_a_bad_tail_sampling_condition_and_a_start_catches_it(tmp_path: Path) -> None:
    """Why the tests also start the Collector: the policies' OTTL is parsed at start, not by `validate`."""
    exe = exe_or_skip()
    bad = tmp_path / "bad.yaml"
    bad.write_text(otelcol.CONFIG.read_text(encoding="utf-8").replace("STATUS_CODE_ERROR", "STATUS_CODE_EROR"), encoding="utf-8")
    assert otelcol.validate(exe, env(tmp_path), bad).returncode == 0
    extra = otelcol.overlay(otlp_port=otelcol.free_port(), cloudwatch_url="http://127.0.0.1:9", metrics_port=otelcol.free_port())
    with pytest.raises(RuntimeError, match="exited"):
        otelcol.Collector(exe, tmp_path, env(tmp_path), extra, config=bad).start()
    assert "STATUS_CODE_EROR" in (tmp_path / "otelcol.log").read_text(encoding="utf-8", errors="replace")


# --- the content drop -----------------------------------------------------------------------------------------

def statements(context: str) -> list[str]:
    groups = CFG["processors"]["transform/drop-content"]["trace_statements"]
    return [s for g in groups for s in g["statements"] if s.split("(", 1)[1].startswith(f"{context}.attributes")]


def expected_statements(context: str) -> list[str]:
    out = []
    for attr in policies.content_attributes():
        if policies.is_template(attr):
            pattern = "^" + attr.replace(".", "\\\\.") + "\\\\."
            out.append(f'delete_matching_keys({context}.attributes, "{pattern}")')
        else:
            out.append(f'delete_key({context}.attributes, "{attr}")')
    return sorted(out)


def test_the_opt_in_attributes_come_from_the_registry_chapter_5_pinned() -> None:
    registry = policies.registry()
    attrs = policies.content_attributes()
    assert "gen_ai.tool.call.arguments" in attrs and len(attrs) == 15
    assert all(registry[a]["stability"] == "development" and "deprecated" not in registry[a] for a in attrs)
    assert [a for a in attrs if policies.is_template(a)] == ["gen_ai.prompt.variable"]


def test_the_drop_deletes_every_opt_in_attribute_from_spans_and_span_events() -> None:
    assert sorted(statements("span")) == expected_statements("span")
    assert sorted(statements("spanevent")) == expected_statements("spanevent")
    groups = CFG["processors"]["transform/drop-content"]["trace_statements"]
    # one group per context, so the span statements run on every span, with events or without
    assert [{s.split("(", 1)[1].split(".", 1)[0] for s in g["statements"]} for g in groups] == [{"span"}, {"spanevent"}]
    assert CFG["processors"]["transform/drop-content"]["error_mode"] == "propagate"


def test_every_manifest_in_the_companion_allows_no_content_so_the_drop_has_no_exception() -> None:
    found = policies.manifests()
    assert len(found) >= 9
    assert {path.name: data["trace_content"] for path, data in found.items()} == {path.name: False for path in found}
    assert all("where" not in s for g in CFG["processors"]["transform/drop-content"]["trace_statements"]
               for s in g["statements"])


# --- the policies ----------------------------------------------------------------------------------------------

def policy(name: str) -> dict:
    return next(p for p in CFG["processors"]["tail_sampling"]["policies"] if p["name"] == name)


def test_the_policies_and_their_order() -> None:
    assert [p["name"] for p in CFG["processors"]["tail_sampling"]["policies"]] == [*policies.KEEP_ALL, policies.SHARE]
    assert policy("failed")["ottl_condition"]["span"] == ["span.status.code == STATUS_CODE_ERROR",
                                                          'span.attributes["error.type"] != nil']
    assert policy("refused")["boolean_attribute"] == {"key": "larkspur.refused", "value": True}
    assert policy("fallback")["boolean_attribute"] == {"key": "larkspur.fallback", "value": True}
    assert policy("slow")["latency"] == {"threshold_ms": 10000}
    assert policy(policies.SHARE)["probabilistic"] == {"hash_salt": "larkspur-ch16",
                                                       "sampling_percentage": "${env:LARKSPUR_TRACE_SHARE_PERCENT:-10}"}
    assert CFG["processors"]["tail_sampling"]["decision_wait"] == "30s"  # the processor's default, written down


def test_over_budget_is_each_workflow_s_per_run_budget_from_its_manifest() -> None:
    budgets = policies.budgets()
    assert set(budgets) == {"w1-ingest", "w1-knowledge", "w2-ops-assistant", "w3-incident", "w4-change", "w5-drift"}
    assert policy("over-budget")["ottl_condition"]["span"] == policies.over_budget_conditions(budgets)
    # chapter 5's copies of W2 and W3 agree with the workflows' own manifests
    assert policies.budgets(("labs/ch05/manifest/*.yaml",)) == {k: budgets[k] for k in ("w2-ops-assistant", "w3-incident")}


# --- the receiver and the exporters ---------------------------------------------------------------------------

def test_the_receiver_listens_on_loopback_only() -> None:
    assert CFG["receivers"]["otlp"]["protocols"] == {"http": {"endpoint": "127.0.0.1:4318"}}


def test_cloudwatch_is_otlp_http_signed_with_sigv4_for_xray_in_us_east_2() -> None:
    exporter = CFG["exporters"]["otlp_http/cloudwatch"]
    assert exporter["traces_endpoint"] == "https://xray.us-east-2.amazonaws.com/v1/traces"
    assert exporter["auth"] == {"authenticator": "sigv4auth/cloudwatch"}
    assert CFG["extensions"]["sigv4auth/cloudwatch"] == {"region": "us-east-2", "service": "xray"}


def test_langfuse_is_otlp_http_with_basic_auth_from_the_environment_and_the_v4_header() -> None:
    exporter = CFG["exporters"]["otlp_http/langfuse"]
    assert exporter["endpoint"] == "${env:LANGFUSE_OTLP_ENDPOINT}"
    assert exporter["headers"] == {"x-langfuse-ingestion-version": "4"}
    assert CFG["extensions"]["basicauth/langfuse"]["client_auth"] == {
        "username": "${env:LANGFUSE_PUBLIC_KEY}", "password": "${env:LANGFUSE_SECRET_KEY}"}


def test_the_span_file_is_appended_to_not_truncated_at_each_start() -> None:
    assert CFG["exporters"]["file"] == {"path": "${env:LARKSPUR_SPAN_FILE}", "append": True}


def test_the_cost_copy_runs_on_the_langfuse_pipeline_only() -> None:
    pipelines = CFG["service"]["pipelines"]
    assert pipelines["traces/sample"] == {"receivers": ["otlp"], "processors": ["transform/drop-content", "tail_sampling", "batch"],
                                          "exporters": ["forward/sampled"]}
    assert pipelines["traces/stores"] == {"receivers": ["forward/sampled"], "exporters": ["file", "otlp_http/cloudwatch"]}
    assert pipelines["traces/langfuse"] == {"receivers": ["forward/sampled"], "processors": ["transform/langfuse-cost"],
                                            "exporters": ["otlp_http/langfuse"]}
    assert CFG["processors"]["transform/langfuse-cost"]["trace_statements"] == [
        'set(span.attributes["gen_ai.usage.cost"], span.attributes["larkspur.cost_usd"]) '
        'where span.attributes["larkspur.cost_usd"] != nil']


def test_the_overlay_changes_only_ports_endpoints_and_the_wait() -> None:
    extra = otelcol.overlay(otlp_port=1, cloudwatch_url="http://127.0.0.1:2", metrics_port=3, decision_wait="2s")
    assert set(extra) == {"receivers", "exporters", "service", "processors"}
    assert set(extra["processors"]["tail_sampling"]) == {"decision_wait"}
    assert yaml.safe_load(yaml.safe_dump(extra))["exporters"] == {"otlp_http/cloudwatch": {"traces_endpoint": "http://127.0.0.1:2/v1/traces"}}


def test_the_collector_gets_dummy_credentials_and_none_of_this_machine_s(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AWS_PROFILE", "a-real-profile")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "a-real-token")
    e = env(tmp_path)
    assert e["AWS_ACCESS_KEY_ID"] == otelcol.DUMMY_ACCESS_KEY_ID and e["AWS_EC2_METADATA_DISABLED"] == "true"
    assert "AWS_PROFILE" not in e and "AWS_SESSION_TOKEN" not in e
    assert not Path(e["AWS_SHARED_CREDENTIALS_FILE"]).exists() and not Path(e["AWS_CONFIG_FILE"]).exists()


# --- the pinned binary -------------------------------------------------------------------------------------------

def make_tarball(path: Path, payload: bytes) -> str:
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(fetch.EXE_NAME)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_tarball_or_a_binary_that_is_not_the_pinned_one_is_refused(tmp_path: Path) -> None:
    tarball = tmp_path / "otelcol.tar.gz"
    digest = make_tarball(tarball, b"the pinned binary")
    exe = fetch.unpack(tarball, tmp_path)
    assert fetch.verified(tarball, exe, digest) == exe
    with pytest.raises(fetch.Mismatch, match="expected"):
        fetch.verified(tarball, exe, "0" * 64)                      # a tarball other than the pinned one
    exe.write_bytes(b"another binary")
    with pytest.raises(fetch.Mismatch, match="the pinned tarball holds"):
        fetch.verified(tarball, exe, digest)                         # a binary swapped after unpacking
    with pytest.raises(FileNotFoundError):
        fetch.verified(tmp_path / "missing.tar.gz", exe, digest)


def test_the_binary_here_is_the_pinned_one() -> None:
    exe = exe_or_skip()
    assert exe == fetch.EXE and fetch.SHA256 == "1fb8163f9036126a1bdc59eab2d7aef4e6cda36f6c1e618f2359663cae8b0f4a"
    assert fetch.URL.endswith("/v0.164.0/otelcol-contrib_0.164.0_windows_amd64.tar.gz")
