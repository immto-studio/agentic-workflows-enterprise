"""The 140 sampled outputs as a book to label on an e-reader (chapter 15, E-D7 as amended on 3 November 2026).

The author asked to read the outputs on his Kindle and send his labels back as text, in place of the labeling
page. This writes the same blind views the page shows (page.prepare: the workflow's name, the rubric as the judge
read it, the reference with the workflow's input, and the output, never a verdict, a model, a run, or a case), in
the page's order, numbered 1 to 140:

- labels/export/ch15-labels.epub, an EPUB 3 book for Send to Kindle;
- labels/export/ch15-labels.txt, the same text, plain;
- labels/kindle-key.json, which number is which output (ids only), for answers.py.

The export folder is git-ignored; the key is committed, since the labels are transcribed through it. Each run
writes the same bytes: the book's identifier and date come from the order's seed, not the clock.

Run from labs/ch15:  python labels/export.py
"""

from __future__ import annotations

import hashlib
import html
import json
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import page  # noqa: E402

EXPORT = HERE / "export"
KEY = HERE / "kindle-key.json"
TITLE = "Chapter 15: the 140 outputs to label"
PER_FILE = 10
MODIFIED = "2026-11-03T00:00:00Z"  # fixed, so a rerun writes the same bytes

HOW_TO = [
    "Each numbered output below is something a workflow wrote. Read the rubric, then the input and the "
    "reference, then the output, and decide whether the output meets every criterion of the rubric shown.",
    "Right means it meets every criterion. Wrong means it breaks at least one.",
    "The judge's standard, which applies to you as well, is printed after these lines.",
    "Send your answers as plain text, one per line: the number, then R for right or W for wrong, then a note if "
    "you want one. For example:",
    "1 R",
    "2 W the saving is stated where the facts give none",
    "3 R",
    "Russian letters work too: В for right and Н for wrong. Answers can come in several messages, in any order, "
    "and a later answer for the same number replaces the earlier one.",
    "Until all 140 are labeled, leave the lab's results, its README sections on the judge's runs, and the comments "
    "on issue #13 from step 3 on closed: they hold the verdicts your labels are measured against.",
]


def views() -> tuple[list[dict[str, Any]], list[str]]:
    """The page's views in the page's order, and the judge's standard, from a scratch label file."""
    with tempfile.TemporaryDirectory() as scratch:
        labeling = page.prepare(labels=Path(scratch) / "labels-scratch.jsonl")
        assert labeling.done == 0
        items = [labeling.view(at)["item"] for at in range(labeling.total)]
        standard = labeling.meta()["standard"]
    for item in items:
        assert set(item) == set(page.SHOWN)
    return items, standard


def book_id(items: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256("\n".join(i["id"] for i in items).encode("utf-8")).hexdigest()
    return f"urn:uuid:{uuid.UUID(digest[:32])}"


def paragraphs(text: str) -> str:
    """Plain text as XHTML paragraphs: every line kept, blank lines as space, nothing read as markup."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out = []
    for line in lines:
        out.append(f"<p>{html.escape(line)}</p>" if line.strip() else '<p class="gap">&#160;</p>')
    return "\n".join(out)


def xhtml(title: str, body: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" '
            'xml:lang="en">\n<head><meta charset="utf-8"/><title>' + html.escape(title) + '</title>'
            '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n<body>\n' + body + "\n</body>\n</html>\n")


def item_body(number: int, item: dict[str, Any]) -> str:
    return "\n".join([
        f'<section id="o{number}" class="item">',
        f"<h2>{number}. {html.escape(item['name'])}</h2>",
        "<h3>Rubric</h3>", f"<p class=\"title\">{html.escape(item['title'])}</p>", paragraphs(item["criteria"]),
        "<h3>Input and reference</h3>", paragraphs(item["reference"]),
        "<h3>Output</h3>", f'<div class="output">{paragraphs(item["output"])}</div>',
        f"<p class=\"answer\">Answer: {number} R or {number} W</p>",
        "</section>",
    ])


CSS = ("body { font-family: serif; line-height: 1.4; }\n"
       "h1 { font-size: 1.4em; } h2 { font-size: 1.2em; margin-top: 1.5em; } h3 { font-size: 1em; margin: 0.9em 0 0.2em; }\n"
       "p { margin: 0 0 0.25em 0; text-indent: 0; } p.gap { margin: 0; line-height: 0.6; }\n"
       "p.title { font-style: italic; } div.output { border-left: 3px solid #555; padding-left: 0.6em; }\n"
       "p.answer { margin-top: 0.8em; font-weight: bold; } section.item { page-break-before: always; }\n")


def write_epub(items: list[dict[str, Any]], standard: list[str], path: Path) -> None:
    files: list[tuple[str, str]] = []  # (name, content)
    intro = "\n".join(["<h1>" + html.escape(TITLE) + "</h1>", "<h2>How to label</h2>",
                       *(f"<p>{html.escape(line)}</p>" for line in HOW_TO),
                       "<h2>The judge's standard</h2>", *(f"<p>{html.escape(p)}</p>" for p in standard)])
    files.append(("intro.xhtml", xhtml("How to label", intro)))
    chunks = [items[i:i + PER_FILE] for i in range(0, len(items), PER_FILE)]
    for n, chunk in enumerate(chunks):
        first = n * PER_FILE + 1
        body = "\n".join(item_body(first + k, item) for k, item in enumerate(chunk))
        files.append((f"items-{n + 1:02d}.xhtml", xhtml(f"Outputs {first} to {first + len(chunk) - 1}", body)))
    nav_items = ['<li><a href="intro.xhtml">How to label</a></li>']
    for n, chunk in enumerate(chunks):
        first = n * PER_FILE + 1
        nav_items.append(f'<li><a href="items-{n + 1:02d}.xhtml">Outputs {first} to {first + len(chunk) - 1}</a></li>')
    nav = ('<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>' + "".join(nav_items) + "</ol></nav>")
    files.append(("nav.xhtml", xhtml("Contents", nav)))
    manifest = ['<item id="css" href="style.css" media-type="text/css"/>',
                '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>']
    spine = []
    for name, _ in files:
        if name == "nav.xhtml":
            continue
        ident = name.replace(".xhtml", "")
        manifest.append(f'<item id="{ident}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{ident}"/>')
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="en">\n'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
           f'<dc:identifier id="bookid">{book_id(items)}</dc:identifier>\n'
           f"<dc:title>{html.escape(TITLE)}</dc:title>\n<dc:language>en</dc:language>\n"
           "<dc:creator>Larkspur lab, chapter 15</dc:creator>\n"
           f'<meta property="dcterms:modified">{MODIFIED}</meta>\n</metadata>\n'
           "<manifest>\n" + "\n".join(manifest) + "\n</manifest>\n"
           '<spine>\n' + "\n".join(spine) + "\n</spine>\n</package>\n")
    container = ('<?xml version="1.0" encoding="utf-8"?>\n'
                 '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                 "</rootfiles>\n</container>\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    fixed = (2026, 11, 3, 0, 0, 0)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype", fixed), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        entries = [("META-INF/container.xml", container), ("OEBPS/content.opf", opf), ("OEBPS/style.css", CSS)]
        entries += [(f"OEBPS/{name}", content) for name, content in files]
        for name, content in entries:
            z.writestr(zipfile.ZipInfo(name, fixed), content.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)


def write_text(items: list[dict[str, Any]], standard: list[str], path: Path) -> None:
    rule = "=" * 60
    lines = [TITLE, "", "HOW TO LABEL", "", *HOW_TO, "", "THE JUDGE'S STANDARD", "", *standard, ""]
    for number, item in enumerate(items, start=1):
        lines += [rule, f"{number}. {item['name']}", rule, "", "RUBRIC", item["title"], item["criteria"], "",
                  "INPUT AND REFERENCE", item["reference"], "", "OUTPUT", item["output"], "",
                  f"Answer: {number} R or {number} W", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def key(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"about": "Which number in labels/export/ch15-labels.epub and .txt is which sampled output; answers.py "
                     "reads it. Ids only, no verdicts.",
            "order_seed": page.ORDER_SEED,
            "numbers": {str(n): item["id"] for n, item in enumerate(items, start=1)}}


def main() -> int:
    items, standard = views()
    write_epub(items, standard, EXPORT / "ch15-labels.epub")
    write_text(items, standard, EXPORT / "ch15-labels.txt")
    KEY.write_text(json.dumps(key(items), ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(items)} outputs to labels/export/ch15-labels.epub and .txt, and labels/kindle-key.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
