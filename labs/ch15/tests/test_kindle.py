"""The e-reader route to the labels (labels/export.py and labels/answers.py): the export is blind, numbered,
and the same on every run, and the answers become label lines in the page's own shape."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

import answers
import export
import page

FORBIDDEN = [r"gpt-oss", r"gemma", r"nova[ -]?lite", r"\bgq-\d", r"\bw[1-5]-\d", r"VERDICT:", r"judge-",
             r"2026-1[01]-\d\d(?:/| run)"]


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[dict], list[str], Path, Path]:
    items, standard = export.views()
    folder = tmp_path_factory.mktemp("export")
    epub, txt = folder / "a.epub", folder / "a.txt"
    export.write_epub(items, standard, epub)
    export.write_text(items, standard, txt)
    return items, standard, epub, txt


def test_the_export_holds_every_sampled_output_in_the_pages_order(exported) -> None:
    items, _, _, txt = exported
    labeling = page.prepare(labels=txt.parent / "none.jsonl")
    assert [i["id"] for i in items] == labeling.order
    text = txt.read_text(encoding="utf-8")
    assert all(f"\n{n}. " in text for n in range(1, len(items) + 1))
    assert len(items) == 140


def test_the_export_is_blind(exported) -> None:
    items, _, epub, txt = exported
    texts = [txt.read_text(encoding="utf-8")]
    with zipfile.ZipFile(epub) as z:
        texts += [z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".xhtml")]
    for text in texts:
        for pattern in FORBIDDEN:
            assert not re.search(pattern, text, flags=re.IGNORECASE), pattern


def test_the_epub_is_well_formed_and_the_same_on_every_run(exported, tmp_path: Path) -> None:
    items, standard, epub, _ = exported
    with zipfile.ZipFile(epub) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/epub+zip"
        names = z.namelist()
        assert "META-INF/container.xml" in names and "OEBPS/content.opf" in names and "OEBPS/nav.xhtml" in names
        assert sum(1 for n in names if n.startswith("OEBPS/items-")) == 14
    again = tmp_path / "b.epub"
    export.write_epub(items, standard, again)
    assert again.read_bytes() == epub.read_bytes()


def test_the_key_numbers_every_output_once(exported) -> None:
    items, *_ = exported
    key = export.key(items)
    assert sorted(map(int, key["numbers"])) == list(range(1, 141))
    assert len(set(key["numbers"].values())) == 140


def test_answers_are_read_in_every_form_the_export_names() -> None:
    text = "1 R\n2 W the saving is stated where the facts give none\n3. в\n4: Н — cut off\n5 right\n6) wrong\n\n7 +\n"
    got, problems = answers.parse(text, 140)
    assert problems == []
    assert got[1] == ("right", "") and got[2] == ("wrong", "the saving is stated where the facts give none")
    assert got[3] == ("right", "") and got[4] == ("wrong", "cut off")
    assert got[5][0] == "right" and got[6][0] == "wrong" and got[7][0] == "right"


def test_a_later_answer_replaces_an_earlier_one_and_bad_lines_are_reported() -> None:
    got, problems = answers.parse("9 R\n9 W changed my mind\n141 R\nnine R\n10 maybe\n", 140)
    assert got == {9: ("wrong", "changed my mind")}
    assert len(problems) == 3


def test_answers_become_label_lines_in_the_pages_shape(exported, tmp_path: Path) -> None:
    items, *_ = exported
    labels = tmp_path / "labels-A.jsonl"
    labeling = page.prepare(labels=labels)
    numbers = {n: item["id"] for n, item in enumerate(items, start=1)}
    for number, (label, note) in {1: ("right", ""), 2: ("wrong", "a note")}.items():
        labeling.label({"id": numbers[number], "label": label, "note": note})
    lines = [json.loads(line) for line in labels.read_text(encoding="utf-8").splitlines()]
    assert [line["labeler"] for line in lines] == ["A", "A"]
    assert {line["id"] for line in lines} == {numbers[1], numbers[2]}
    assert all(len(line["rubric_sha256"]) == 64 for line in lines)
