"""Ingestion for W1: the corpus is classified before it is indexed, then cut the way the Knowledge Base cuts it.

Chapter 10. Chapter 2's rule is that a corpus is classified before it is indexed, and chapter 6's
Knowledge Base parses with the default parser and cuts fixed chunks of 300 tokens with 20 percent
overlap. This module does both for the local lab, in three steps:

1. The gate (`check`). A document is indexed only if its front matter names a title, a doc_type,
   an owner_team, a system, one of the four classes, a non-empty access_groups list and a
   last_reviewed date. Every group has to be one that security engineering's reviewed map knows
   (knowledge-server/membership/groups.yaml, W1-D17), and a Confidential or Restricted page may
   not name a broad group such as lm-all-staff or lm-eng-all (W1-D18). In production the pipeline
   also compares a page's groups with the source's own permissions and refuses a page whose front
   matter is wider; the lab has no source system to compare with. A refused page goes into a
   report with its owner team, and the rest of the corpus is indexed without it.
2. What a reader sees (`visible_text`). Three things a reader of the rendered page never sees
   stay out of the index: Markdown link reference definitions, which render as nothing and serve
   as comments in the `[//]: # (...)` form; HTML comments, closed or not; and invisible code
   points, meaning Unicode format characters (zero-width spaces, bidirectional controls), the
   tag block U+E0000 to U+E007F, and variation selectors. CommonMark decides which lines render,
   through markdown-it-py from chapter 5's pinned set. One of the corpus's three injections hides
   in a comment (rb-fnol-intake-queue-backlog.md); the other two are text a reader sees, so they
   stay. Raw HTML that hides text some other way, such as a hidden div, gets through; production
   indexes the page as the wiki renders it.
3. Chunks. `fixed_chunks` cuts windows of 300 tokens with 60 tokens of overlap, each carrying its
   document's metadata, as the Knowledge Base stores the chunk text beside the metadata and
   embeds the text alone. The tokens are tiktoken's cl100k_base, read from the copy LiteLLM ships,
   so nothing is downloaded; Titan's tokenizer isn't published, so the windows only approximate
   the Knowledge Base's. `heading_chunks` is the variant the lab measures against it: one chunk
   per section, with the document's title and the section's heading in front of its text.

Run: python ingest.py [--variant fixed|heading]   (prints the counts and every refused page with its owner)
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import yaml
from markdown_it import MarkdownIt

HERE = Path(__file__).resolve().parent
DOCS_DIR = HERE.parent / "corpus" / "docs"
sys.path.insert(0, str(HERE.parent / "knowledge-server" / "membership"))
from group_map import GroupMap  # noqa: E402
from group_map import load as load_group_map  # noqa: E402

CLASSES = ("Public", "Internal", "Confidential", "Restricted")  # in order: a higher index is more sensitive
NARROW_ONLY = ("Confidential", "Restricted")  # classes a broad group may not read (W1-D18)
REQUIRED = ("title", "doc_type", "owner_team", "system", "classification", "access_groups", "last_reviewed")
GROUPS = load_group_map()
# Chapter 6 sets both numbers for fixed-size chunking, which takes the size and the overlap from
# the caller: 300 tokens a chunk, 20 percent overlap. Neither is a Knowledge Base default; the
# default strategy cuts chunks of about 300 tokens and honors sentence boundaries.
CHUNK_TOKENS = 300
OVERLAP_TOKENS = 60  # 20 percent of CHUNK_TOKENS

FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
# A comment as CommonMark 0.31.2 defines it: <!-->, <!--->, or <!-- up to the first -->.
HTML_COMMENT = re.compile(r"<!--(?:>|->|.*?-->)", re.S)
# A comment that never closes. CommonMark ends an HTML block that opens with <!-- at the end of
# the document when no line closes it, so nothing after it renders. Mid-line, the spec would show
# the text; it goes anyway, because indexing less than a reader sees costs an answer at most,
# and indexing more lets hidden text in.
UNCLOSED_COMMENT = re.compile(r"<!--.*\Z", re.S)
# A line renders when it belongs to a leaf block: a paragraph, a heading, code, raw HTML or a
# rule. A link reference definition (CommonMark 4.7) belongs to none, which is why `[//]: # (...)`
# and `[comment]: <> (...)` work as comments, in a quote or a list item as anywhere else.
COMMONMARK = MarkdownIt("commonmark")
LEAVES = {"paragraph_open", "heading_open", "fence", "code_block", "html_block", "hr"}
# Code points no reader sees beyond category Cf: the tag block's unassigned points, which are Cn,
# and the variation selectors, which only modify the character before them.
INVISIBLE = re.compile("[\U000e0000-\U000e007f︀-️\U000e0100-\U000e01ef]")
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$", re.M)


def _encoding():
    """cl100k_base from the files LiteLLM bundles, found without importing LiteLLM itself."""
    spec = importlib.util.find_spec("litellm")
    if spec and spec.submodule_search_locations:
        bundled = Path(next(iter(spec.submodule_search_locations))) / "litellm_core_utils" / "tokenizers"
        os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(bundled))
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


ENCODING = _encoding()


@dataclass(frozen=True)
class Chunk:
    """One indexed piece of a document, with the metadata every query filters on."""

    chunk_id: str  # "<doc_id>#<n>"
    doc_id: str  # the file name, which is what a citation names
    text: str
    title: str
    doc_type: str
    owner_team: str
    system: str
    classification: str
    access_groups: tuple[str, ...]
    last_reviewed: str  # ISO date

    def metadata(self) -> dict:
        meta = asdict(self)
        meta.pop("text")
        meta["access_groups"] = list(self.access_groups)
        return meta


@dataclass(frozen=True)
class Refusal:
    doc_id: str
    reason: str
    owner_team: str = ""  # who hears about it; empty when the page names no owner


def read_document(path: Path) -> tuple[dict, str]:
    """Split a document into its front matter and its body. A file without front matter has none."""
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1))
    return (meta if isinstance(meta, dict) else {}), match.group(2)


def check(meta: dict, groups: GroupMap = GROUPS) -> str | None:
    """The gate: why a document may not be indexed, or None."""
    missing = [f for f in REQUIRED if not meta.get(f)]
    if missing:
        return "missing " + ", ".join(missing)
    if meta["classification"] not in CLASSES:
        return f"unknown classification {meta['classification']!r}"
    named = meta["access_groups"]
    if not (isinstance(named, list) and all(
            isinstance(g, str) and g for g in named)):
        return "access_groups is not a list of group names"
    unknown = sorted(set(named) - groups.names)
    if unknown:
        return f"groups not in the reviewed map: {unknown}"
    broad = sorted(set(named) & groups.broad)
    if broad and meta["classification"] in NARROW_ONLY:
        return (f"a {meta['classification']} page names"
                f" a broad group: {broad}")
    reviewed = meta["last_reviewed"]
    if not isinstance(reviewed, date):
        try:
            date.fromisoformat(str(reviewed))
        except ValueError:
            return f"last_reviewed {reviewed!r} is not a date"
    return None


def without_format(text: str) -> str:
    """The text without the code points no reader sees: format characters (Cf) and INVISIBLE."""
    return INVISIBLE.sub("", "".join(c for c in text if unicodedata.category(c) != "Cf"))


def rendered_lines(body: str) -> str:
    """The body's lines that CommonMark renders, and its blank lines; nothing a reader can't see."""
    lines = body.split("\n")
    shown: set[int] = set()
    for token in COMMONMARK.parse(body):
        if token.map and token.type in LEAVES:
            shown.update(range(*token.map))
    return "\n".join(line for i, line in enumerate(lines) if i in shown or not line.strip())


def visible_text(body: str) -> str:
    """The body as a reader of the rendered page sees it: no invisible code points, definitions or comments."""
    text = without_format(body).replace("\r\n", "\n").replace("\r", "\n")
    text = HTML_COMMENT.sub("", rendered_lines(text))
    return UNCLOSED_COMMENT.sub("", text)


def _chunk(doc_id: str, meta: dict, n: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}#{n}",
        doc_id=doc_id,
        text=text.strip(),
        title=str(meta["title"]),
        doc_type=str(meta["doc_type"]),
        owner_team=str(meta["owner_team"]),
        system=str(meta["system"]),
        classification=str(meta["classification"]),
        access_groups=tuple(meta["access_groups"]),
        last_reviewed=str(meta["last_reviewed"]),
    )


def _windows(text: str, size: int = CHUNK_TOKENS, overlap: int = OVERLAP_TOKENS) -> list[str]:
    tokens = ENCODING.encode(text)
    if len(tokens) <= size:
        return [text]
    step = size - overlap
    starts = range(0, len(tokens) - overlap, step)
    return [ENCODING.decode(tokens[start:start + size]) for start in starts]


def fixed_chunks(doc_id: str, meta: dict, body: str) -> list[Chunk]:
    """Windows of 300 tokens with 60 of overlap over the whole body, as the Knowledge Base cuts them."""
    return [_chunk(doc_id, meta, n, text) for n, text in enumerate(_windows(body))]


def heading_chunks(doc_id: str, meta: dict, body: str) -> list[Chunk]:
    """One chunk per section, the title and the heading in front; a long section is cut in windows."""
    marks = list(HEADING.finditer(body))
    sections: list[tuple[str, str]] = []
    if not marks or marks[0].start() > 0:
        sections.append(("", body[: marks[0].start()] if marks else body))
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        sections.append((mark.group(2), body[mark.end():end]))
    chunks: list[Chunk] = []
    for heading, text in sections:
        if not text.strip():
            continue
        head = str(meta["title"]) if not heading or heading == meta["title"] else f"{meta['title']}: {heading}"
        for window in _windows(text.strip(), CHUNK_TOKENS - len(ENCODING.encode(head)) - 2, OVERLAP_TOKENS):
            chunks.append(_chunk(doc_id, meta, len(chunks), f"{head}\n\n{window}"))
    return chunks


CHUNKERS = {"fixed": fixed_chunks, "heading": heading_chunks}


def ingest(docs_dir: Path = DOCS_DIR, variant: str = "fixed") -> tuple[list[Chunk], list[Refusal]]:
    """Every document through the gate, then through the chunker. Returns the chunks and the refusals.

    A refused page stays out and the rest go in: one owner's missing review date never holds up
    everyone else's pages. The front matter's text fields lose their format characters too, since
    the title reaches the model in every passage.
    """
    chunker = CHUNKERS[variant]
    chunks: list[Chunk] = []
    refusals: list[Refusal] = []
    for path in sorted(docs_dir.glob("*.md")):
        meta, body = read_document(path)
        reason = check(meta)
        if reason:
            refusals.append(Refusal(path.name, reason, str(meta.get("owner_team") or "")))
            continue
        meta = {k: without_format(v) if isinstance(v, str) else v for k, v in meta.items()}
        chunks.extend(chunker(path.name, meta, visible_text(body)))
    return chunks, refusals


def refusals_report(refusals: list[Refusal]) -> list[dict[str, str]]:
    """Each refused page, its owner team and the reason: what the pipeline sends to the owners."""
    return [{"page": r.doc_id, "owner_team": r.owner_team or "(none named)", "reason": r.reason}
            for r in refusals]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--variant", choices=sorted(CHUNKERS), default="fixed")
    parser.add_argument("--docs", type=Path, default=DOCS_DIR)
    args = parser.parse_args(argv)
    chunks, refusals = ingest(args.docs, args.variant)
    docs = {c.doc_id for c in chunks}
    print(f"{len(docs)} documents indexed as {len(chunks)} {args.variant} chunks; {len(refusals)} refused")
    for row in refusals_report(refusals):
        print(f"  refused {row['page']} (owner {row['owner_team']}): {row['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
