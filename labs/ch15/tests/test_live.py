"""The live job (E-D9, E-D12) end to end with a fake model: every golden set through its workflow's harness and
servers, the judge, one result with its pins and tokens, the comparison with the baseline, --accept, and the pins
that invalidate an accepted baseline. The fake (tests/fake_model.py) stands where chapter 5's gateway stands and
writes the call line its hooks write; for W4 it writes a text from the author's sample, so the judge's verdict on it
must be withheld. The last test puts chapter 5's real gateway in front of the fake, as Ollama."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "ci"))

import baseline as baseline_file  # noqa: E402
import fake_model  # noqa: E402
import live  # noqa: E402
import measure  # noqa: E402

import items as itemize  # noqa: E402
import registry  # noqa: E402
import report  # noqa: E402
import sample  # noqa: E402

W4_RATIONALE = "You write one sentence of rationale"  # W4's rationale seam (a2a/rationale_model.SYSTEM)


@pytest.fixture(scope="module")
def sampled_w4() -> str:
    """A W4 rationale in the author's sample, as step 3's judge read it."""
    by_key = {i.key: i for its in itemize.build_all().values() for i in its}
    entry = next(e for e in sample.load()["items"] if e["workflow"] == "w4")
    return by_key[sample.key_of(entry)].output


@pytest.fixture(scope="module")
def fake(sampled_w4: str):
    def reply(body: dict) -> str:
        system = next((m.get("content") or "" for m in body.get("messages") or [] if m.get("role") == "system"), "")
        return sampled_w4 if system.startswith(W4_RATIONALE) else fake_model.reply_for(body)

    model = fake_model.FakeModel(reply)
    yield model
    model.close()


@pytest.fixture(scope="module")
def full(fake, tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("live")
    lines: list[str] = []
    plan = live.Plan("gpt-oss-20b", "gemma4-12b", fake.port, fake.port)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(live, "QUIET_S", 0.1)
        path = live.run(plan, tmp / "scratch", start=fake.start_gateway, out=tmp / "live", progress=lines.append)
    return {"path": path, "doc": registry.read_json(path), "lines": lines, "tmp": tmp, "plan": plan}


@pytest.fixture(scope="module")
def accepted(full) -> Path:
    path = full["tmp"] / "baseline.json"
    live.accept(full["path"], baseline=path, today="2026-11-04")
    return path


def test_a_complete_run_writes_one_result_named_by_its_time_and_model(full) -> None:
    path, doc = full["path"], full["doc"]
    assert path.parent == full["tmp"] / "live"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{6}Z-gpt-oss-20b\.json", path.name)
    assert doc["kind"] == "live" and doc["run"]["complete"] and doc["run"]["why_partial"] is None
    assert list(doc["workflows"]) == list(measure.WORKFLOWS)


def test_the_result_carries_every_pin(full, fake) -> None:
    pins, now = full["doc"]["pins"], measure.current_pins()
    assert pins["prompt"] == now["prompt"]
    gpt_oss, gemma = "ollama_chat/gpt-oss:20b", "ollama_chat/gemma4:12b"
    expected_aliases = {"skeleton": {"larkspur-chat-restricted": gpt_oss},
                        "w1": {"larkspur-embed": "ollama/qwen3-embedding:0.6b", "larkspur-chat": gpt_oss,
                               "larkspur-chat-restricted": gpt_oss}}
    for workflow, pin in pins["workflows"].items():
        assert pin["set"] == now["sets"][workflow] and pin["rubric"] == now["rubrics"].get(workflow)
        assert pin["aliases"] == expected_aliases.get(workflow, {"larkspur-chat": gpt_oss, "larkspur-chat-restricted": gpt_oss})
        assert pin["config"]["source"] == live.CONFIGS[(workflow, "gpt-oss-20b")]
        for served, model in pin["models"].items():
            assert (model["digest"], model["server"]) == (fake.digests[served.split("/", 1)[1]], fake.version)
    judge = pins["judge"]
    assert (judge["model"], judge["served"], judge["digest"]) == ("gemma4-12b", gemma, fake.digests["gemma4:12b"])
    assert judge["aliases"] == {"larkspur-chat": gemma, "larkspur-chat-restricted": gemma}
    assert judge["config"]["source"] == live.JUDGE_CONFIGS["gemma4-12b"]


def test_every_case_of_every_set_is_scored_check_by_check(full) -> None:
    for workflow, entry in full["doc"]["workflows"].items():
        assert len(entry["cases"]) == measure.current_pins()["sets"][workflow]["cases"]
        assert all(list(v) == measure.case_checks(workflow) for v in entry["cases"].values())
        assert entry["tally"] == measure.tally(workflow, entry["cases"])
        for case, failed in entry["failing"].items():
            assert all(entry["cases"][case][name] is False for name in failed)
    # A fake that reads nothing states no fact, and the controls hold whatever it says.
    w2 = full["doc"]["workflows"]["w2"]["tally"]
    assert w2["deterministic.facts"]["passed"] == 0 and w2["deterministic.masked"]["failed"] == 0


def test_the_tokens_are_the_gateways_count_per_workflow(full) -> None:
    scratch = full["tmp"] / "scratch"
    for workflow, entry in full["doc"]["workflows"].items():
        tag = registry.manifest(workflow)["workflow"]
        lines = registry.read_jsonl(scratch / workflow / f"gateway-{workflow}.jsonl")
        chat = [x for x in lines if x["workflow"] == tag and x["requested_alias"] != "larkspur-embed"]
        tokens = entry["tokens"]["workflow"]
        assert tokens["calls"] == len(chat) > 0
        assert tokens["prompt"] == sum(x["prompt_tokens"] for x in chat)
        if workflow in measure.JUDGED:
            assert entry["tokens"]["judge"]["calls"] == len(entry["judged"]) > 0


def test_the_judge_reads_every_output_a_model_wrote_and_withholds_a_sampled_text(full) -> None:
    sampled = report.sampled_texts()
    for workflow in measure.JUDGED:
        entry = full["doc"]["workflows"][workflow]
        rows = entry["judged"]
        assert rows and entry["judge"]["judged"] == len(rows)
        for row in rows:
            assert row["criteria"] and row["author"] == "gpt-oss-20b"
            assert row["text_sha256"] == report.text_sha256(row["output"])
            if row["text_sha256"] in sampled:
                assert (row["verdict"], row["reason"], row["withheld"]) == (None, None, measure.WITHHELD)
            else:
                assert row["verdict"] == "right" and row["withheld"] is None
    w4 = full["doc"]["workflows"]["w4"]["judge"]
    assert w4["withheld"] == w4["judged"] == 8 and w4["right"] == 0


def test_no_verdict_is_printed_while_the_run_goes(full) -> None:
    said = "\n".join(full["lines"])
    assert "judged" in said and not re.search(r"\b(right|wrong)\b|VERDICT", said)


def test_the_result_names_no_path_of_this_machine(full) -> None:
    text = full["path"].read_text(encoding="utf-8")
    for place in (full["tmp"], registry.ROOT, Path.home()):
        for spelling in (str(place), place.as_posix(), json.dumps(str(place))[1:-1]):
            assert spelling not in text, spelling


def test_the_run_is_compared_with_the_baseline_and_becomes_it_after_review(full, accepted) -> None:
    passed, text = live.compare(full["path"])
    # No kept run recorded a digest, and the fake's judge is not step 3's Gemma.
    assert not passed and "is invalid for the judge, skeleton, w1, w2, w3, w4, w5 until a run is accepted" in text
    held = registry.read_json(accepted)
    assert held["source"]["kind"] == "live" and held["source"]["sha256"] == registry.sha256_of(full["path"])
    assert held["pins"] == full["doc"]["pins"] and baseline_file.check(accepted) == []
    passed, text = live.compare(full["path"], baseline=accepted)
    assert passed and "The gate passes" in text


def test_a_changed_digest_or_alias_map_invalidates_the_accepted_baseline(full, fake, accepted) -> None:
    said: list[str] = []
    assert live.dry_run(full["plan"], baseline=accepted, progress=said.append)["problems"] == {}
    assert said[-1] == "The baseline holds for this alias map and these digests."
    saved = fake.digests["gpt-oss:20b"]
    fake.digests["gpt-oss:20b"] = "1" * 64
    try:
        problems = live.dry_run(full["plan"], baseline=accepted, progress=lambda line: None)["problems"]
    finally:
        fake.digests["gpt-oss:20b"] = saved
    assert sorted(problems) == list(measure.WORKFLOWS)
    assert problems["w3"] == ["ollama_chat/gpt-oss:20b: the digest changed: ffffffffffff -> 111111111111"]
    remapped = live.Plan("gemma4-12b", "gpt-oss-20b", fake.port, fake.port)
    problems = live.dry_run(remapped, baseline=accepted, progress=lambda line: None)["problems"]
    assert any(p.startswith("the alias map changed: larkspur-chat ollama_chat/gpt-oss:20b -> ollama_chat/gemma4:12b")
               for p in problems["w2"])
    assert "the judge's model changed: gemma4-12b -> gpt-oss-20b" in problems["the judge"]


def test_a_smoke_run_stays_in_its_scratch_folder_resumes_and_cannot_be_accepted(fake, tmp_path: Path) -> None:
    plan = live.Plan("gpt-oss-20b", "gemma4-12b", fake.port, fake.port, ("w4",), 2)
    scratch = tmp_path / "scratch"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(live, "QUIET_S", 0.1)
        path = live.run(plan, scratch, start=fake.start_gateway, out=tmp_path / "live", progress=lambda line: None)
        started = fake.requests["gateway w4"]
        again = live.run(plan, scratch, start=fake.start_gateway, out=tmp_path / "live", progress=lambda line: None)
    assert path == again == scratch / "result.json" and not (tmp_path / "live").exists()
    assert fake.requests["gateway w4"] == started  # the set's files were written, so it didn't run again
    doc = registry.read_json(path)
    assert not doc["run"]["complete"] and doc["run"]["why_partial"] == "workflows w4, the first 2 cases"
    assert list(doc["workflows"]["w4"]["cases"]) == ["w4-01", "w4-02"]
    with pytest.raises(SystemExit, match="partial run"):
        live.accept(path, baseline=tmp_path / "baseline.json")
    with pytest.raises(SystemExit, match="other options"):
        live.run(live.Plan("gpt-oss-20b", "gemma4-12b", fake.port, fake.port, ("w4",), 3), scratch,
                 start=fake.start_gateway, progress=lambda line: None)


def test_a_model_never_judges_its_own_outputs(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(SystemExit, match="gpt-oss-20b would judge its own outputs"):
        live.run(live.Plan("gpt-oss-20b", "gpt-oss-20b"), tmp_path / "scratch", progress=lambda line: None)
    # A remap of the configs themselves onto the judge's model is caught by what they serve, not by --model.
    monkeypatch.setitem(live.CONFIGS, ("w2", "gpt-oss-20b"), live.CONFIGS[("w2", "gemma4-12b")])
    with pytest.raises(SystemExit, match=r"gemma4-12b would judge its own outputs \(w2\)"):
        live.run(live.Plan("gpt-oss-20b", "gemma4-12b"), tmp_path / "scratch", progress=lambda line: None)
    assert not (tmp_path / "scratch").exists()


def _litellm() -> str | None:
    beside = Path(sys.executable).parent / ("litellm.exe" if os.name == "nt" else "litellm")
    return str(beside) if beside.exists() else shutil.which("litellm")


@pytest.mark.skipif(_litellm() is None, reason="the litellm console script is not installed beside this interpreter")
def test_the_skeleton_runs_through_chapter_5s_real_gateway(fake, tmp_path: Path) -> None:
    """Chapter 9's config copied with the run's settings, chapter 5's hooks loaded from chapter 9's gateway folder
    with chapter 5's manifests, and the call lines they write: the fake answers as Ollama behind LiteLLM."""
    plan = live.Plan("gpt-oss-20b", "gemma4-12b", fake.port, fake.port, ("skeleton",), 2)
    path = live.run(plan, tmp_path / "scratch", out=tmp_path / "live", progress=lambda line: None)
    doc = registry.read_json(path)
    lines = registry.read_jsonl(tmp_path / "scratch" / "skeleton" / "gateway-skeleton.jsonl")
    calls = [x for x in lines if x["event"] == "call"]
    assert len(calls) == 2 and all(
        (x["workflow"], x["data_class"], x["requested_alias"], x["served_model"], x["fallback"])
        == ("w2-ops-assistant", "internal", "larkspur-chat-restricted", "gpt-oss:20b", False) for x in calls)
    assert doc["workflows"]["skeleton"]["tokens"]["workflow"]["calls"] == 2
    assert doc["workflows"]["skeleton"]["tokens"]["workflow"]["prompt"] == sum(x["prompt_tokens"] for x in calls) > 0
    config = (tmp_path / "scratch" / "skeleton" / "litellm.config.yaml").read_text(encoding="utf-8")
    assert f"api_base: http://127.0.0.1:{fake.port}" in config and "num_ctx: 16384" in config
