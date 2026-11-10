"""The case converter (E-D2): one format for six sets, nothing retyped, and a check that a changed golden
file can't pass silently."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import convert
import registry

COUNTS = {"skeleton": 20, "w1": 25, "w2": 25, "w3": 24, "w4": 8, "w5": 3}


def test_every_set_converts_to_the_same_fields(cases) -> None:
    for workflow, count in COUNTS.items():
        converted = convert.convert(workflow)
        assert len(converted) == count == len(cases[workflow])
        manifest = registry.manifest(workflow)
        for case in converted:
            assert tuple(case) == convert.FIELDS
            assert case["workflow"] == workflow and case["owner"] == manifest["owner"]
            assert case["source"] == registry.WORKFLOWS[workflow].golden
            assert case["data_class"] in ("internal", "confidential", "restricted")
            assert set(case["negative"]) == {"refusal", "trap", "planted"}
            assert case["derived_from"][0]["path"] == registry.WORKFLOWS[workflow].manifest


def test_the_committed_sets_match_their_sources() -> None:
    assert convert.check() == []


def _entries(workflow: str) -> dict[str, dict]:
    """The golden file's entries by id, in the shape each scorer reads, with the defaults it applies."""
    data = registry.read_yaml(registry.path(registry.WORKFLOWS[workflow].golden))
    if workflow == "skeleton":
        return {c["id"]: c for c in data["cases"]}
    if workflow in ("w2", "w3"):
        return {c["id"]: {**c, "persona": c.get("persona", convert.ONCALL)} for c in data}
    if workflow == "w5":
        plants = [p for n in data for p in (n["expected"].get("plants") or [])]
        return {n["id"]: {**n, "expected": {**n["expected"], "plants": plants}} for n in data}
    return {c["id"]: c for c in data}


def test_a_case_goes_back_to_the_entry_it_came_from(cases) -> None:
    """Every entry of every golden file comes back from its converted case: the format carries everything
    the scorers read, and nothing the converter made up."""
    for workflow in registry.ORDER:
        entries = _entries(workflow)
        for case in cases[workflow].values():
            back = convert.scorer_case(case)
            if workflow == "w1":
                question = entries[case["id"].split("/")[0]]
                assert back["question"] == question
                assert back["denied"] == (question["trap"] == "access" and case["input"]["persona"] == convert.ONCALL)
            else:
                assert back == entries[case["id"]], case["id"]
        if workflow != "w1":
            assert set(entries) == set(cases[workflow])


def test_w1_asks_each_access_question_twice(cases) -> None:
    w1 = cases["w1"]
    with registry.loaded("w1") as mods:
        member_of = dict(mods.answer_eval.MEMBER_OF)
    access = [c for c in w1.values() if c["negative"]["trap"] == "access"]
    assert len(access) == 10
    for case in access:
        persona = case["input"]["persona"]
        assert case["negative"]["refusal"] == (persona == convert.ONCALL)
        if persona != convert.ONCALL:
            assert persona == member_of[case["expected"]["required_access_group"]]
            assert case["derived_from"][-1]["path"] == registry.WORKFLOWS["w1"].scorer
    assert all(c["data_class"] == "restricted" for c in w1.values())  # W1-D26: the set quotes Restricted pages


def test_the_hash_reads_crlf_as_lf(tmp_path: Path) -> None:
    lf, crlf = tmp_path / "lf.yaml", tmp_path / "crlf.yaml"
    lf.write_bytes(b"- id: a\n  trap: none\n")
    crlf.write_bytes(b"- id: a\r\n  trap: none\r\n")
    assert registry.sha256_of(lf) == registry.sha256_of(crlf)


@pytest.fixture
def mirror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """W4's golden file, manifest, and scorer copied under a stand-in repository root, so a test can change
    a golden file without touching the workflow's."""
    w4 = registry.WORKFLOWS["w4"]
    for relative in (w4.golden, w4.manifest, w4.scorer):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(registry.path(relative), target)
    monkeypatch.setattr(registry, "ROOT", tmp_path)
    return tmp_path


def test_a_changed_golden_file_fails_the_check(mirror: Path) -> None:
    folder = mirror / "cases"
    convert.write("w4", folder)
    assert convert.check(folder, ("w4",)) == []
    golden = mirror / registry.WORKFLOWS["w4"].golden
    golden.write_text(golden.read_text(encoding="utf-8").replace("expected_class: Low", "expected_class: Medium"),
                      encoding="utf-8")
    problems = convert.check(folder, ("w4",))
    assert len(problems) == 1 and "workflows/w4-change/eval/changes.yaml changed since the conversion" in problems[0]


def test_a_changed_manifest_fails_the_check(mirror: Path) -> None:
    folder = mirror / "cases"
    convert.write("w4", folder)
    manifest = mirror / registry.WORKFLOWS["w4"].manifest
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("owner: tomasz.nowak", "owner: someone.else"),
                        encoding="utf-8")
    problems = convert.check(folder, ("w4",))
    assert len(problems) == 1 and "manifest/w4-change.yaml changed since the conversion" in problems[0]


def test_an_edited_converted_file_fails_the_check(tmp_path: Path) -> None:
    convert.write("w4", tmp_path)
    file = tmp_path / "w4.jsonl"
    file.write_text(file.read_text(encoding="utf-8").replace('"class": "Low"', '"class": "High"', 1), encoding="utf-8")
    assert convert.check(tmp_path, ("w4",)) == ["w4: w4.jsonl differs from a fresh conversion of its sources"]


def test_a_missing_converted_file_fails_the_check(tmp_path: Path) -> None:
    assert convert.check(tmp_path, ("w5",)) == ["w5: w5.jsonl is missing; run cases/convert.py"]
