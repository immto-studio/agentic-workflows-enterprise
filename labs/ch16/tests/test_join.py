"""join.py on the stores the local run recorded, and on CloudTrail events in the shape AWS documents."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import join

LAB = Path(__file__).resolve().parents[1]
RESULTS = LAB / "results" / "2026-11-03" / "collector"
RUN_A, RUN_B, RUN_C = ("7d3e0c5f9a1b4c2e8f6a0b1c2d3e4f5a", "2c9a4e6b8d0f41a3b5c7d9e1f3a5b7c9",
                       "9e8d7c6b5a4f43e2a1b0c9d8e7f6a5b4")


def stand_in() -> dict:
    """The skeleton's run that stood in for fig-16-01 until step 3b: the every-run phase's pods-claims-api."""
    return next(r for r in summary()["phases"]["every-run"]["rows"] if r["case"] == "pods-claims-api")


def summary() -> dict:
    return json.loads((RESULTS / "collector.json").read_text(encoding="utf-8"))


def test_one_run_from_every_local_store() -> None:
    trace_id = stand_in()["trace_id"]
    joined = join.join(trace_id, join.local_stores(RESULTS / "every-run"))
    assert [r["event"] for r in joined["harness log"]] == ["tools_verified", "tool_call", "answer"]
    assert [(r["event"], r["tool"], r["identity"]) for r in joined["tool server log"]] == [
        ("tool_call", "get_pod_status", "larkspur-ops-reader")]
    assert [r["event"] for r in joined["gateway cost lines"]] == ["call", "call"]
    assert all(r["trace_id"] == trace_id for records in joined.values() for r in records)
    spans = joined["spans"]
    assert len(spans) == stand_in()["spans_sent"]
    assert {s["resource"]["service.name"] for s in spans} == {"harness", "gateway", "mcp-server"}
    assert sum(1 for s in spans if s["name"] == "chat larkspur-chat") == 2
    assert sum(1 for s in spans if s["name"] == "execute_tool get_pod_status") == 2  # the harness's and the server's


def test_a_run_the_sampler_dropped_still_has_its_logs_and_its_cost_lines() -> None:
    rows = summary()["phases"]["sampled"]["rows"]
    dropped = next(r for r in rows if r["kind"] == "golden" and not r["expected"]["kept"] and r["tool_calls"])
    joined = join.join(dropped["trace_id"], join.local_stores(RESULTS / "sampled"))
    assert joined["spans"] == []
    assert joined["harness log"] and joined["tool server log"] and joined["gateway cost lines"]
    assert "none kept" in join.render(dropped["trace_id"], joined)


def test_the_tree_and_the_header_lines(capsys: pytest.CaptureFixture[str]) -> None:
    trace_id = stand_in()["trace_id"]
    assert join.main([trace_id, "--stores", str(RESULTS / "every-run")]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"trace {trace_id}\n")
    assert "harness log: 3 records" in out and "tool server log: 1 record\n" in out
    assert "gateway cost lines: 2 records: 2 served" in out
    assert f"spans: {stand_in()['spans_sent']} kept by share-of-the-rest, at a share of 1" in out
    assert "\n  invoke_agent harness  [harness]  +0 ms" in out and "\n    chat larkspur-chat  [gateway]" in out


def test_the_readme_shows_what_join_prints() -> None:
    readme = (LAB / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    block = readme.split("fig-16-01 until step 3b:\n\n```\n", 1)[1].split("```", 1)[0]
    trace_id = stand_in()["trace_id"]
    assert block == join.render(trace_id, join.join(trace_id, join.local_stores(RESULTS / "every-run")))


def test_cloudtrail_events_join_by_the_session_name_the_tag_or_the_access_key() -> None:
    trail = join.CloudTrail(join.SAMPLE_CLOUDTRAIL)
    assert len(trail.events) == 9

    def matched(trace_id: str) -> list[tuple[str, str]]:
        return [(why, event["eventName"]) for why, event in trail.matches(trace_id)]

    assert matched(RUN_A) == [("AssumeRole, session tag trace_id", "AssumeRole"),
                              ("role session name in userIdentity.arn", "DescribeCluster"),
                              ("role session name in userIdentity.arn", "DescribeNodegroup")]  # its accessKeyId is ""
    assert matched(RUN_B) == [("AssumeRole, session tag trace_id", "AssumeRole"),
                              ("role session name in userIdentity.arn", "DescribeCluster")]
    # chapter 6's session name, the object ID alone: the key is the only link, and CloudTrail left one call without it
    assert matched(RUN_C) == [("AssumeRole, session tag trace_id", "AssumeRole"),
                              ("access key from the run's AssumeRole", "DescribeCluster")]
    every = {event["eventID"] for t in (RUN_A, RUN_B, RUN_C) for _, event in trail.matches(t)}
    assert len(every) == 7  # C's DescribeNodegroup and the platform team's call belong to no run found


def test_a_session_name_without_a_tag_still_joins_by_its_16_characters(tmp_path: Path) -> None:
    trail = join.CloudTrail(join.SAMPLE_CLOUDTRAIL)
    for event in trail.events:  # as if the AssumeRole had fallen out of the window
        if event["eventName"] == "AssumeRole":
            event["requestParameters"]["tags"] = []
    assert [e["eventName"] for _, e in trail.matches(RUN_A)] == ["AssumeRole", "DescribeCluster", "DescribeNodegroup"]
    assert trail.matches("7d3e0c5f9a1b4c2e" + "0" * 16)  # the session name holds 16 characters, not the whole id


def test_the_run_behind_a_cloudtrail_event(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trail = join.CloudTrail(join.SAMPLE_CLOUDTRAIL)
    no_key = next(e for e in trail.events if e["eventName"] == "DescribeNodegroup" and RUN_A[:16] in e["userIdentity"]["arn"])
    assert no_key["userIdentity"]["accessKeyId"] == ""
    assert join.trace_for_event(no_key, [], trail) == [RUN_A]            # from the AssumeRole's tag
    unrelated = trail.events[-1]
    assert join.trace_for_event(unrelated, [], trail) == []
    # with no trail, the local logs name the run whose trace id starts with the 16 characters
    (tmp_path / "harness.jsonl").write_text(json.dumps({"event": "answer", "trace_id": RUN_A}) + "\n", encoding="utf-8")
    assert join.trace_for_event(no_key, join.local_stores(tmp_path), None) == [RUN_A]
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(no_key), encoding="utf-8")
    assert join.main(["--event", str(event_file), "--stores", str(tmp_path), "--cloudtrail", str(join.SAMPLE_CLOUDTRAIL)]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"trace {RUN_A}\n") and "CloudTrail: 3 records" in out


def test_lookup_events_output_and_json_lines_read_the_same(tmp_path: Path) -> None:
    events = join.load_events(join.SAMPLE_CLOUDTRAIL)
    lookup = tmp_path / "lookup.json"
    lookup.write_text(json.dumps({"Events": [{"CloudTrailEvent": json.dumps(e)} for e in events]}), encoding="utf-8")
    lines = tmp_path / "events.jsonl"
    lines.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    assert join.load_events(lookup) == join.load_events(lines) == events


def test_a_trace_id_must_be_32_hex_characters() -> None:
    with pytest.raises(ValueError, match="isn't a trace id"):
        join.join("demo0001", join.local_stores(RESULTS / "every-run"))
    assert join.prefix_of_session("3f2b9c1e-6a4d-4e8b-9c7f-1a2b3c4d5e6f.7d3e0c5f9a1b4c2e") == "7d3e0c5f9a1b4c2e"
    assert join.prefix_of_session("3f2b9c1e-6a4d-4e8b-9c7f-1a2b3c4d5e6f") is None
    assert join.prefix_of_session("someone.7D3E0C5F9A1B4C2E") is None
    assert join.session_of_arn("arn:aws:sts::111122223333:assumed-role/r/s.0123456789abcdef") == "s.0123456789abcdef"
    assert join.session_of_arn("arn:aws:iam::111122223333:user/alice") is None
