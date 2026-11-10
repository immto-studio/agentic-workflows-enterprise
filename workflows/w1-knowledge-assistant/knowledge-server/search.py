"""The knowledge search behind W1's two tools: embed the question, filter by the caller, rank, cite.

Chapter 10. `KnowledgeSearch` is everything the server's tools do, without the MCP transport
around them, so the tests drive it directly. `search` is `search_docs`:

1. The caller comes from access.py: the forwarded token and the membership table.
2. The question is embedded through the gateway as `w1-knowledge`, labeled with the caller's
   class and at least Internal. The query is part of the conversation (W1-D21): a custodian may
   type a line of the runbook into it, and a second query may restate a passage.
3. The store filters by the caller's groups and by the class cap in W1's manifest before it
   ranks (store.py), and returns the top five. On AWS, W1's pages have a Knowledge Base of their
   own that holds only the classes the manifest allows, so the filter there carries the group
   test alone (W1-D15); the lab keeps every page in one store, so it applies the cap as well.
4. Each passage goes back with what a citation needs (the page, its title, its last review) and
   its class, which the harness uses to label the next model call (chapter 2's rule).

`caller_class` is the second tool: the highest class among the pages the caller may read, under
the manifest's cap. The harness asks for it once per question, before the loop, and labels every
model call at least at that class (W1-D21). It reads page metadata only and returns no text. It
counts the groups the table lists for the caller even when a stale table or a token grants fewer
today, since the class protects what the engineer may type.

Nothing tells the caller that a page they can't read matched: when nothing passes the filter, the
answer is an empty list (W1-D5 on companion issue #8).

One JSON line per call goes to the audit log: the trace id, the caller's object ID, where their
groups came from ("stale table" once the table is past its age), the groups used, an HMAC of the
title of each page returned, and the class the query went out as. The question stays out, as the
manifest's `trace_content: false` asks. A title can name a person, and a restricted page's title
can be the secret, so the line names a page only by the HMAC (audit_hmac.py, chapter 17's rule,
companion #126). The titles stay in the harness's log, a Restricted store (W1-D24), where an
auditor who holds the key matches them to the line.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence, TextIO

import numpy as np

HERE = Path(__file__).resolve().parent
W1 = HERE.parent
for folder in ("ingest", "store"):
    sys.path.insert(0, str(W1 / folder))
from access import Caller  # noqa: E402
from audit_hmac import text_hmac  # noqa: E402
from store import RANK, VectorStore, allowed  # noqa: E402

TOP_K = 5

# Embeds one question, labeled with a data class, under a trace id; returns its vector.
QueryEmbedder = Callable[[str, str, str], np.ndarray]


@dataclass(frozen=True)
class Passage:
    doc_id: str
    title: str
    last_reviewed: str
    classification: str
    text: str

    def as_dict(self) -> dict:
        return {"doc_id": self.doc_id, "title": self.title, "last_reviewed": self.last_reviewed,
                "classification": self.classification, "text": self.text}


def highest_class(passages: Sequence[Passage], floor: str = "Internal") -> str:
    """The class a prompt holding these passages carries: the highest among them, never below the floor."""
    return max([floor, *(p.classification for p in passages)], key=RANK.__getitem__)


class KnowledgeSearch:
    def __init__(self, store: VectorStore, embed_query: QueryEmbedder, *, max_class: str,
                 audit: TextIO | None = None, audit_key: bytes | None = None):
        self.store, self.embed_query, self.max_class = store, embed_query, max_class
        self.audit = audit or sys.stderr
        self.audit_key = audit_key  # None: AUDIT_HMAC_KEY's, through audit_hmac.audit_key

    def search(self, query: str, caller: Caller, trace_id: str,
               k: int = TOP_K) -> list[Passage]:
        # Only the caller's groups that some page names go into
        # the filter; with none, no search at all (W1-D12).
        readable = caller.groups & self.store.groups()
        query_class = max("Internal", self.held_class(caller),
                          key=RANK.__getitem__)  # W1-D21
        hits = []
        if readable:
            vector = self.embed_query(query, trace_id, query_class)
            hits = self.store.search(vector, k, readable,
                                     self.max_class)
        passages = [Passage(h.chunk.doc_id, h.chunk.title,
                            h.chunk.last_reviewed,
                            h.chunk.classification, h.chunk.text)
                    for h in hits]
        # Values as they are, text as an HMAC (chapter 17). The
        # time is a number; the trace id, the caller's object ID
        # and the group names are system identifiers; the event,
        # groups_from and the two classes come from fixed sets. A
        # title can name a person, and doc_id is a file name made
        # from the title, so each page is named by an HMAC of its
        # title alone.
        self.audit.write(json.dumps({  # never the question
            "ts": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"),
            "event": "search", "trace_id": trace_id,
            "caller": caller.oid, "groups_from": caller.source,
            "groups": sorted(readable),
            "returned": [text_hmac(p.title, self.audit_key)
                         for p in passages],
            "highest_class": highest_class(passages),
            "query_class": query_class,
        }) + "\n")
        self.audit.flush()
        return passages

    def held_class(self, caller: Caller) -> str:
        """The highest class among the pages the caller's table row opens, under the cap; Public when none."""
        held = caller.held & self.store.groups()
        classes = {c.classification for c in self.store.chunks if allowed(c, held, self.max_class)}
        return max(classes, key=RANK.__getitem__, default="Public")

    def caller_class(self, caller: Caller, trace_id: str) -> str:
        """The `caller_class` tool: held_class, with one audit line."""
        data_class = self.held_class(caller)
        # Values only: identifiers, group names, and fixed sets.
        self.audit.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": "caller_class", "trace_id": trace_id, "caller": caller.oid,
            "groups_from": caller.source, "counted_groups": sorted(caller.held & self.store.groups()),
            "data_class": data_class,
        }) + "\n")
        self.audit.flush()
        return data_class
