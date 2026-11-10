"""The labeling page (chapter 15, step 4, E-D7): one sampled output at a time, blind to every verdict, each label
saved as it is made.

`python labels/page.py` serves page.html on 127.0.0.1:8015 with Python's own http.server. The page shows what the
judge read for the output, rendered by the judge's own code (judge.render) and checked against the request its
result row records: the rubric's title and criteria, the reference with the workflow's input in it, and the
output, beside the judge's standard from its system prompt. It shows no verdict of a scorer, a layer, or the
judge, and not the model, the run, or the case: an item's view carries the fields in SHOWN and no others, and its
id is a hash. The order is the sample shuffled by ORDER_SEED.

R labels the output right and W wrong, with the note typed beside it, and the page moves to the next output
without a label. B goes back one item. Each label is one JSON line appended to labels-A.jsonl and flushed to disk
before the page moves on: the id, the label, the note, the time in UTC, the rubric file's hash, and the labeler,
"A". A corrected label is a new line, and the last line for an id is its label. A restart reads the file and
resumes at the first output without a label.

Nothing leaves the workstation: the server listens on 127.0.0.1 only and answers only requests addressed to it
there, a label must come as JSON from the page's own origin, and the page loads nothing from anywhere else, which
its Content-Security-Policy also enforces.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import socket
import sys
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for folder in (LAB / "layers", LAB / "cases", LAB, LAB / "judge", HERE):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import items as itemize  # noqa: E402
import judge as judging  # noqa: E402
import registry  # noqa: E402
import sample as sampling  # noqa: E402

HOST = "127.0.0.1"
PORT = 8015
LABELER = "A"
LABELS = HERE / f"labels-{LABELER}.jsonl"
PAGE = HERE / "page.html"
ORDER_SEED = "chapter 15, step 4: the labeling page's order"
SHOWN = ("id", "name", "title", "criteria", "reference", "output", "label", "note")  # all an item's view carries
NOTE_MAX = 1000
BODY_MAX = 8192
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


# --- what the page shows ---------------------------------------------------------------------------------------

def standard(prompt: tuple[str, str]) -> list[str]:
    """The judge's standard, from its system prompt: the paragraph on the reference and the one on right and
    wrong, so that the person labels by the same rule the judge was given. The reply's form is left out."""
    paragraphs = [" ".join(p.split()) for p in prompt[0].split("\n\n")]
    chosen = [p for p in paragraphs if p.startswith(("The reference was written", "An output is right"))]
    if len(chosen) != 2:
        raise ValueError("prompt.txt no longer holds the two paragraphs the page shows as the standard")
    return chosen


def views(document: dict[str, Any], all_items: dict[str, list[itemize.Item]],
          rows: dict[tuple, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each sampled output's view by id: the four texts the judge's user message is made of, rendered by the
    judge's own code. Refused if a text no longer renders to the request the judge read for that output, since a
    label would then answer another question than the judge's verdict."""
    prompt = judging.load_prompt()
    frame = prompt[1]
    rubrics = {w: judging.load_rubric(w) for w in judging.JUDGED}
    by_key = {i.key: i for its in all_items.values() for i in its}
    out, stale = {}, []
    for entry in document["items"]:
        key = sampling.key_of(entry)
        item = by_key[key]
        rubric = rubrics[item.workflow]
        messages = judging.render(prompt, rubric, item.conditions, item.reference, item.output)
        parts = {"title": judging._flat(rubric["title"]),
                 "criteria": "\n".join(f"{n}. {judging._flat(c['text'])}"
                                       for n, c in enumerate(judging.criteria_for(rubric, item.conditions), 1)),
                 "reference": judging._inside(item.reference, "reference"),
                 "output": judging._inside(item.output, "output")}
        if frame.format(**parts) != messages[1]["content"]:
            raise ValueError(f"{entry['id']}: the page's texts do not make the judge's message")
        row = rows.get((entry["judge"], key))
        if row is None or row["messages_sha256"] != judging.messages_sha256(messages):
            stale.append(entry["id"])
        out[entry["id"]] = {"id": entry["id"], "name": registry.WORKFLOWS[item.workflow].name, **parts}
    if stale:
        shown = ", ".join(stale[:5]) + (", ..." if len(stale) > 5 else "")
        raise ValueError(f"the judge's results read another text for {len(stale)} sampled outputs ({shown}); "
                         "run the judge again before labeling")
    return out


def order(ids: list[str], seed: str = ORDER_SEED) -> list[str]:
    """The page's order: the sample's ids shuffled by a fixed seed."""
    out = sorted(ids)
    random.Random(seed).shuffle(out)
    return out


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the labels --------------------------------------------------------------------------------------------------

class Store:
    """The label file: one JSON line per label, appended and flushed to disk as it is made. The last line for an
    id is its label."""

    def __init__(self, path: Path, ids: set[str]) -> None:
        self.path, self.lock = path, threading.Lock()
        self.labels, _ = sampling.read_labels(path, ids)

    def add(self, id_: str, label: str, note: str, rubric_sha256: str) -> dict[str, Any]:
        line = {"id": id_, "label": label, "note": note, "time": now(), "rubric_sha256": rubric_sha256,
                "labeler": LABELER}
        with self.lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self.labels[id_] = line
        return line


class Labeling:
    """The page's state: the views in the page's order, and the labels."""

    def __init__(self, shown: dict[str, dict[str, Any]], workflows: dict[str, str], labels: Path,
                 standard_: list[str]) -> None:
        self.shown, self.order, self.workflow = shown, order(list(shown)), workflows
        self.rubric = {w: sampling.rubric_sha256(w) for w in sorted(set(workflows.values()))}
        self.store = Store(labels, set(shown))
        self.standard = standard_

    @property
    def total(self) -> int:
        return len(self.order)

    @property
    def done(self) -> int:
        return len(self.store.labels)

    def meta(self) -> dict[str, Any]:
        return {"total": self.total, "labeler": LABELER, "standard": self.standard}

    def view(self, at: int) -> dict[str, Any]:
        id_ = self.order[at]
        line = self.store.labels.get(id_) or {}
        item = {**self.shown[id_], "label": line.get("label"), "note": line.get("note", "")}
        return {"total": self.total, "done": self.done, "at": at, "finished": False,
                "item": {k: item[k] for k in SHOWN}}

    def open_after(self, at: int) -> dict[str, Any]:
        """The first output without a label after position `at`, else the first from the start, else the end."""
        for n in [*range(at + 1, self.total), *range(0, at + 1)]:
            if self.order[n] not in self.store.labels:
                return self.view(n)
        return {"total": self.total, "done": self.done, "at": self.total, "finished": True, "item": None}

    def label(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict) or body.get("id") not in self.shown:
            raise ValueError("no sampled output with that id")
        if body.get("label") not in judging.VERDICTS:
            raise ValueError("a label is right or wrong")
        note = body.get("note", "")
        if not isinstance(note, str) or len(note) > NOTE_MAX:
            raise ValueError(f"a note is text of at most {NOTE_MAX} characters")
        self.store.add(body["id"], body["label"], note.strip(), self.rubric[self.workflow[body["id"]]])
        return self.open_after(self.order.index(body["id"]))


def prepare(labels: Path = LABELS, document: dict[str, Any] | None = None,
            all_items: dict[str, list[itemize.Item]] | None = None, folder: Path | None = None) -> Labeling:
    """The page's state from sample.json, the outputs, and the judge's current results."""
    document = sampling.load() if document is None else document
    all_items = itemize.build_all() if all_items is None else all_items
    rows = sampling.cross_rows(sampling.judge_results(folder or sampling.results_folder()))
    shown = views(document, all_items, rows)
    workflows = {e["id"]: e["workflow"] for e in document["items"]}
    return Labeling(shown, workflows, labels, standard(judging.load_prompt()))


# --- the server ------------------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "ch15-labeling"

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, format: str, *args: Any) -> None:
        return  # one line per request would bury the start message the author needs

    def _send(self, status: int, body: bytes, content_type: str, csp: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if csp:
            self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _local(self) -> bool:
        """Only requests addressed to this server on the loopback, from its own page when they carry an origin."""
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        if self.headers.get("Host") not in hosts or (origin is not None and origin not in {f"http://{h}" for h in hosts}):
            self._json({"error": "this page answers its own requests on 127.0.0.1 only"}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def do_GET(self) -> None:
        if not self._local():
            return
        url = urlsplit(self.path)
        labeling: Labeling = self.server.labeling  # type: ignore[attr-defined]
        if url.path == "/":
            self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8", csp=True)
        elif url.path == "/api/meta":
            self._json(labeling.meta())
        elif url.path == "/api/item":
            at = parse_qs(url.query).get("at", [None])[0]
            if at is None:
                self._json(labeling.open_after(-1))
            elif at.isascii() and at.isdigit() and int(at) < labeling.total:
                self._json(labeling.view(int(at)))
            else:
                self._json({"error": "no output at that position"}, HTTPStatus.BAD_REQUEST)
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if not self._local():
            return
        if urlsplit(self.path).path != "/api/label":
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if self.headers.get_content_type() != "application/json":
            self._json({"error": "a label comes as JSON"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        given = self.headers.get("Content-Length") or ""
        length = int(given) if given.isascii() and given.isdigit() else 0
        if not 0 < length <= BODY_MAX:
            self._json({"error": "a label's request is empty or too long"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            self._json(self.server.labeling.label(body))  # type: ignore[attr-defined]
        except (ValueError, UnicodeDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


class Server(ThreadingHTTPServer):
    """The page's server. On Windows, SO_REUSEADDR lets a second server bind a port the first one is listening on,
    which would split the labels between two processes, so there the port is this process's alone."""
    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(labeling: Labeling, port: int = PORT) -> Server:
    """The page's server on 127.0.0.1; port 0 takes a free one."""
    server = Server((HOST, port), Handler)
    server.labeling = labeling  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=PORT, help=f"the port on 127.0.0.1 (default {PORT})")
    args = parser.parse_args(argv)
    print("Preparing the sampled outputs (a few seconds)...", flush=True)
    try:
        labeling = prepare()
    except ValueError as exc:
        raise SystemExit(f"The page did not start: {exc}") from exc
    try:
        server = make_server(labeling, args.port)
    except OSError as exc:
        raise SystemExit(f"The page did not start: port {args.port} on {HOST} is taken ({exc.strerror}); "
                         "start it with --port and another number") from exc
    port = server.server_address[1]
    print(f"Open http://127.0.0.1:{port}/ in a browser. {labeling.done} of {labeling.total} outputs are labeled; "
          f"each label is saved to {registry.rel(LABELS)} as it is made. Ctrl+C stops the page.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print(f"Stopped with {labeling.done} of {labeling.total} labeled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
