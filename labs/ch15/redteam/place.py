"""Where a red-team variant goes: the fakes a workflow reads, edited in memory, or a scratch copy of W1's corpus.

Chapter 15, step 6. A variant's `placements` (redteam/generate.py) say what text goes where. This module puts
it there and nowhere else: the workflows' files stay as they are.

- W2 to W5 read their fakes in server processes the workflows' own code starts (W2's three servers, W3's
  five, W4's analyst, W5's four readers). `apply` edits a fake module's data after it is imported: W2's
  `fakes` (alerts, logs, events, labels), W3's `changes` (tickets), W4's `github_fake` (pull requests), and
  W5's `cloud_fake` (tags, the trail), `state_fake` (outputs), and `cost_fake` (cost lines).
- W1's knowledge server reads the corpus from disk when it starts. `w1_docs` writes a copy of the corpus with
  the variant in it, and `w1_index` embeds the chunks that changed through W1's gateway, as the ingestion job
  does (ingest/build_index.py), so the server finds a vector for every chunk. The server is pointed at both by
  W1_INDEX, which it reads, and by the hook below, which makes `ingest.ingest` read the copy.

The hook: hook/sitecustomize.py, on PYTHONPATH for a red-team run only, calls `install` when
CH15_REDTEAM_PLACEMENT names a placement file. `install` adds an import finder that, when one of the fake
modules above is imported from the workflow file it expects, runs the module and then `apply`. Every process
the run starts inherits the variable, so the servers serve the variant; a process that never imports a fake
module is untouched, and without the variable the hook does nothing.

`neutral=True` places a neutral string of the same kind in place of each piece, which is how the run asks what
a decision would have been with the same fields and no plant's words in them (W5-D12's structural test,
applied to every variant).
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import json
import os
import re
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
COMPANION = HERE.parents[2]
W1 = "workflows/w1-knowledge-assistant"
W2 = "workflows/w2-ops-assistant"
W3 = "workflows/w3-incident"
W4 = "workflows/w4-change"
W5 = "workflows/w5-drift"
ENV = "CH15_REDTEAM_PLACEMENT"
HOOK = HERE / "hook"
NEUTRAL_TEXT = "neutral text"
# The fake modules a placement edits: the module's name, and the file it must come from.
MODULES: dict[str, dict[str, str]] = {
    "w1": {"ingest": f"{W1}/ingest/ingest.py"},
    "w2": {"fakes": f"{W2}/servers/fakes.py"},
    "w3": {"fakes": f"{W2}/servers/fakes.py", "changes": f"{W3}/servers/changes.py"},
    "w4": {"github_fake": f"{W4}/servers/github_fake.py"},
    "w5": {"cloud_fake": f"{W5}/servers/cloud_fake.py", "state_fake": f"{W5}/servers/state_fake.py",
           "cost_fake": f"{W5}/servers/cost_fake.py"},
}
FOLDERS: dict[str, tuple[str, ...]] = {
    "w1": (f"{W1}/ingest", f"{W1}/store", f"{W1}/knowledge-server"),
    "w2": (f"{W2}/servers",),
    "w3": (f"{W3}/servers", f"{W2}/servers"),
    "w4": (f"{W4}/servers", f"{W4}/a2a"),
    "w5": (f"{W5}/servers", f"{W5}/detect"),
}


def _texts(placements: list[dict[str, Any]], neutral: bool) -> list[dict[str, Any]]:
    """The placements, each piece's text neutral when asked; an empty text (a moved plant's old place) stays."""
    if not neutral:
        return placements
    return [{**p, "text": f"{NEUTRAL_TEXT} {i}" if p["text"] else ""} for i, p in enumerate(placements)]


# --- W1: a copy of the corpus ---------------------------------------------------------------------------------

FRONT = re.compile(r"^(---\n.*?\n---\n)(.*)$", re.S)


def _wrap(text: str, container: str) -> str:
    if not text:
        return ""
    return f"<!-- {text} -->" if container == "html-comment" else text


def _paragraphs(body: str) -> list[str]:
    return re.split(r"\n\s*\n", body)


def _join(paragraphs: list[str]) -> str:
    return "\n\n".join(p for p in paragraphs if p.strip() or p == "")


def place_page(body: str, target: dict[str, Any], text: str, plant_block: str | None) -> str:
    """One placement in one page's body. `plant_block` is the raw block of the plant on its own page."""
    if "before_line" in target:  # moved: a paragraph at the first line break of the chunk the index ranks
        line = target["before_line"]
        at = body.index(line)
        if at > 0 and body[at - 1] != "\n":  # the chunk starts inside a line: go to the next one
            at = body.index("\n", at) + 1
        return body[:at] + text + "\n\n" + body[at:]
    container = target.get("container", "paragraph")
    block = _wrap(text, "paragraph" if container == "as-is" else container)
    if target.get("op") == "after-next-paragraph":
        paragraphs = _paragraphs(body)
        at = next(i for i, p in enumerate(paragraphs) if plant_block is not None and plant_block in p)
        paragraphs.insert(min(at + 2, len(paragraphs)), block)
        return _join(paragraphs)
    if plant_block is None or plant_block not in body:
        raise LookupError(f"{target.get('page')}: the plant's block is not in the page")
    if block:
        return body.replace(plant_block, block, 1)
    paragraphs = [p for p in _paragraphs(body.replace(plant_block, "", 1))]
    return _join([p for p in paragraphs if p.strip()]) + ("\n" if body.endswith("\n") else "")


def w1_docs(placements: list[dict[str, Any]], out: Path, *, neutral: bool = False) -> Path:
    """A copy of W1's corpus/docs under `out` with the placements in it. Returns the folder."""
    sys.path.insert(0, str(HERE))
    import plants  # noqa: E402  (the block finder the inventory uses)
    source = COMPANION / W1 / "corpus" / "docs"
    docs = out / "docs"
    if docs.exists():
        shutil.rmtree(docs)
    shutil.copytree(source, docs)
    placed_block: dict[str, str | None] = {}
    for p in _texts(placements, neutral):
        target = p["target"]
        path = docs / target["page"]
        raw = path.read_bytes().decode("utf-8")
        match = FRONT.match(raw)
        front, body = (match.group(1), match.group(2)) if match else ("", raw)
        page = target["page"]
        if page not in placed_block and "before_line" not in target:
            placed_block[page] = plants.w1_block(body)[1]
        new = place_page(body, target, p["text"], placed_block.get(page))
        if target.get("op") != "after-next-paragraph" and "before_line" not in target:
            container = target.get("container", "paragraph")
            placed_block[page] = _wrap(p["text"], "paragraph" if container == "as-is" else container) or None
        path.write_bytes((front + new).encode("utf-8"))
    return docs


def w1_index(docs: Path, out: Path, embed: Any) -> tuple[Path, list[str]]:
    """The serving index for the copy: the committed vector for every chunk whose page and text are the
    committed corpus's, and a new one for every chunk that changed, from `embed(texts, data_class)`, which
    the run points at W1's gateway as the ingestion job (`w1-ingest`). Returns the file and the new chunks."""
    import numpy as np
    folders = [str(COMPANION / f) for f in FOLDERS["w1"]]
    sys.path[:0] = folders
    try:
        import ingest
        from embedding import SERVED_MODEL, prefixes
        committed = {c.chunk_id: c.text for c in ingest.ingest(COMPANION / W1 / "corpus" / "docs", "fixed")[0]}
        chunks, _ = ingest.ingest(docs, "fixed")
    finally:
        for f in folders:
            sys.path.remove(f)
    data = np.load(COMPANION / W1 / "index" / "qwen3-embedding-0.6b" / "fixed.npz", allow_pickle=False)
    rows = {str(c): i for i, c in enumerate(data["chunk_ids"])}
    vectors = np.zeros((len(chunks), data["vectors"].shape[1]), dtype=np.float32)
    changed = [i for i, c in enumerate(chunks) if committed.get(c.chunk_id) != c.text or c.chunk_id not in rows]
    for i, c in enumerate(chunks):
        if i not in changed:
            vectors[i] = data["vectors"][rows[c.chunk_id]]
    _, doc_prefix = prefixes(SERVED_MODEL)
    by_class: dict[str, list[int]] = {}
    for i in changed:
        by_class.setdefault(chunks[i].classification, []).append(i)
    for data_class, indices in sorted(by_class.items()):
        batch = embed([doc_prefix.format(title=chunks[i].title) + chunks[i].text for i in indices], data_class)
        vectors[indices] = batch
    path = out / "fixed.npz"
    np.savez_compressed(path, model=str(data["model"]), chunk_ids=[c.chunk_id for c in chunks], vectors=vectors,
                        question_ids=data["question_ids"], questions=data["questions"])
    return path, [chunks[i].chunk_id for i in changed]


# --- W2 and W3: the fakes ---------------------------------------------------------------------------------------

def _w2_alert(fakes: Any, target: dict[str, Any]) -> dict[str, Any]:
    if "index" in target:
        return fakes.W2_ALERTS[target["index"]]
    return next(a for a in fakes.W2_ALERTS if a["service"] == target["service"] and target["summary"] in a["summary"])


def apply_w2(fakes: Any, changes: Any, placements: list[dict[str, Any]]) -> None:
    for p in placements:
        target, text = p["target"], p["text"]
        store = target["store"]
        if store == "W2_ALERTS":
            alert = _w2_alert(fakes, target)
            field = target.get("field", "annotation")
            if target.get("append"):
                alert[field] = f"{alert[field]} {text}".strip()
            else:
                alert[field] = target.get("around", "{}").replace("{}", text) if text else text
        elif store in ("LOGS", "EVENTS"):
            rows = getattr(fakes, store)[target["service"]]
            if "add" in target:
                row = dict(target["add"])
                key = "line" if store == "LOGS" else "message"
                row[key] = row[key].replace("{}", text)
                rows.append(row)
            else:
                rows[target["index"]][target["field"]] = target["around"].replace("{}", text)
        elif store == "_LABELS":
            labels = fakes._LABELS.setdefault(target["service"], {})
            if text:
                labels[target["key"]] = text
            else:
                labels.pop(target["key"], None)
        elif store == "_CHANGES":
            if changes is None:
                raise LookupError("a ticket placement needs W3's changes module")
            records = changes._CHANGES[target["service"]]
            record = (next(r for r in records if r["number"] == target["number"]) if "number" in target
                      else records[target["index"]])
            field = target.get("field", "description")
            record[field] = f"{record[field]}: {text}" if target.get("append") else text
        else:
            raise ValueError(f"no W2 store {store!r}")


# --- W4: the GitHub fake ----------------------------------------------------------------------------------------

def apply_w4(github_fake: Any, placements: list[dict[str, Any]]) -> None:
    for p in placements:
        target, text = p["target"], p["text"]
        pr = github_fake._PULLS[target["change_ref"]]
        field = target["field"]
        if field == "labels":
            labels = list(pr["labels"])
            if target.get("add"):
                labels.append(text)
            elif text:
                labels[labels.index(target["label"])] = text
            else:
                labels.remove(target["label"])
            pr["labels"] = labels
        elif target.get("append"):
            pr[field] = f"{pr[field]} {text}".strip()
        else:
            pr[field] = text


# --- W5: the cloud, state, and cost fakes -------------------------------------------------------------------------

def _resource(cloud_fake: Any, account: str, resource_id: str) -> dict[str, Any]:
    kinds = cloud_fake._INVENTORY[account]
    for reservation in kinds["instances"]:
        for instance in reservation["Instances"]:
            if instance["InstanceId"] == resource_id:
                return instance
    ids = {"volumes": "VolumeId", "snapshots": "SnapshotId", "security_groups": "GroupId", "route_tables": "RouteTableId"}
    for kind, field in ids.items():
        for item in kinds[kind]:
            if item[field] == resource_id:
                return item
    raise LookupError(f"{resource_id} is not in {account}'s inventory")


def _event(cloud_fake: Any, target: dict[str, Any]) -> dict[str, Any]:
    return next(e for e in cloud_fake._EVENTS[target["account"]] if e["EventName"] == target["event_name"]
                and any(r["ResourceName"] == target["resource_id"] for r in e["Resources"]))


def apply_w5(modules: dict[str, Any], placements: list[dict[str, Any]]) -> None:
    cloud_fake, state_fake, cost_fake = modules.get("cloud_fake"), modules.get("state_fake"), modules.get("cost_fake")
    for p in placements:
        target, text, channel = p["target"], p["text"], p["channel"]
        if channel == "a tag" and cloud_fake is not None:
            tags = _resource(cloud_fake, target["account"], target["resource_id"])["Tags"]
            mine = [t for t in tags if t["Key"] == target["tag_key"]]
            if target.get("add") or not mine:
                tags.append({"Key": target["tag_key"], "Value": text})
            elif text:
                mine[0]["Value"] = text
            else:
                tags.remove(mine[0])
        elif channel == "a user agent" and cloud_fake is not None:
            event = _event(cloud_fake, target)
            record = json.loads(event["CloudTrailEvent"])
            if target["field"] == "userAgent":
                record["userAgent"] = text
            else:  # requestParameters.<name>
                record.setdefault("requestParameters", {})[target["field"].split(".", 1)[1]] = text
            event["CloudTrailEvent"] = json.dumps(record, separators=(",", ":"))
        elif channel == "a snapshot's description" and cloud_fake is not None:
            _resource(cloud_fake, target["account"], target["resource_id"])["Description"] = text
        elif channel == "a security group rule's description" and cloud_fake is not None:
            group = _resource(cloud_fake, target["account"], target["group_id"])
            rule = next(r for r in group["IpPermissions"] if r["FromPort"] == target["port"])
            rule["IpRanges"][0]["Description"] = text
        elif channel == "a Terraform state output" and state_fake is not None:
            for version in state_fake._BUCKET[state_fake.key_of(target["workspace"])]:
                outputs = version["Body"]["values"].setdefault("outputs", {})
                if target.get("add"):
                    outputs[target["output"]] = {"sensitive": False, "type": "string", "value": text}
                elif target["output"] in outputs:
                    if text:
                        outputs[target["output"]]["value"] = text
                    else:
                        del outputs[target["output"]]
        elif channel == "a cost line" and cost_fake is not None:
            number = cloud_fake.ACCOUNTS[target["account"]] if cloud_fake is not None else None
            rows = cost_fake._ROWS[target["billing_period"]]
            row = next(r for r in rows if r["line_item_usage_type"] == target["usage_type"]
                       and r["product_servicecode"] == target["service"]
                       and (number is None or r["line_item_usage_account_id"] == number))
            if target.get("add"):
                extra = dict(row)
                extra.update(line_item_usage_type=row["line_item_usage_type"] + "-2", line_item_unblended_cost=0.0,
                             line_item_line_item_description=text)
                rows.append(extra)
            else:
                row["line_item_line_item_description"] = text


# --- one entry point --------------------------------------------------------------------------------------------

def apply(workflow: str, modules: dict[str, Any], placements: list[dict[str, Any]], *, neutral: bool = False) -> None:
    """Put the placements into the fake modules already imported (`modules` by name)."""
    placements = _texts(placements, neutral)
    if workflow in ("w2", "w3"):
        apply_w2(modules["fakes"], modules.get("changes"), placements)
    elif workflow == "w4":
        apply_w4(modules["github_fake"], placements)
    elif workflow == "w5":
        apply_w5(modules, placements)
    else:
        raise ValueError(f"{workflow}: placed through a copy of the corpus (w1_docs), not in memory")


# The data each fake module serves from: what a placement edits, and what `placed` puts back.
STORES: dict[str, tuple[str, ...]] = {"fakes": ("W2_ALERTS", "LOGS", "EVENTS", "_LABELS"), "changes": ("_CHANGES",),
                                      "github_fake": ("_PULLS",), "cloud_fake": ("_INVENTORY", "_EVENTS"),
                                      "state_fake": ("_BUCKET",), "cost_fake": ("_ROWS",)}


def _restore(target: Any, saved: Any) -> None:
    """Put a store's saved content back into the same object, so every name bound to it sees the files' data."""
    if isinstance(target, dict):
        target.clear()
        target.update(saved)
    else:
        target[:] = saved


@contextmanager
def placed(workflow: str, placements: list[dict[str, Any]], *, neutral: bool = False) -> Iterator[dict[str, Any]]:
    """The workflow's fake modules with the placements in them, for the block. A module the caller had already
    imported is the same object here, so its stores are saved before the placement and put back after it; a module
    imported here is forgotten after the block (registry.isolated). Either way the next reader sees the files' data."""
    import copy
    import importlib
    sys.path.insert(0, str(HERE.parent / "layers"))
    import registry  # noqa: E402
    with registry.isolated(FOLDERS[workflow]):
        modules = {name: importlib.import_module(name) for name in MODULES[workflow]}
        saved = {(name, store): copy.deepcopy(getattr(module, store)) for name, module in modules.items()
                 for store in STORES.get(name, ()) if hasattr(module, store)}
        try:
            apply(workflow, modules, placements, neutral=neutral)
            yield modules
        finally:
            for (name, store), content in saved.items():
                _restore(getattr(modules[name], store), content)


# --- the hook ---------------------------------------------------------------------------------------------------

class _Finder(importlib.abc.MetaPathFinder):
    """Finds a fake module the way the rest of sys.meta_path would, and when it comes from the file a
    placement expects, applies the placement after the module runs."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.expected = {name: (COMPANION / rel).resolve() for name, rel in MODULES[spec["workflow"]].items()}
        self.loaded: dict[str, Any] = {}

    def find_spec(self, name: str, path: Any, target: Any = None) -> Any:
        if name not in self.expected:
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is not None:
                break
        else:
            return None
        if not spec.origin or Path(spec.origin).resolve() != self.expected[name] or spec.loader is None:
            return spec
        loader, run = spec.loader, spec.loader.exec_module

        def exec_module(module: Any) -> None:
            run(module)
            self.loaded[name] = module
            if self.spec["workflow"] == "w1":
                docs = Path(self.spec["docs"])
                module.DOCS_DIR = docs
                module.ingest.__defaults__ = (docs, "fixed")
            else:
                apply(self.spec["workflow"], {**self.loaded}, [p for p in self.spec["placements"]
                                                                if _module_for(self.spec["workflow"], p) == name])

        loader.exec_module = exec_module  # type: ignore[method-assign]
        return spec


def _module_for(workflow: str, placement: dict[str, Any]) -> str:
    """Which fake module a placement edits."""
    if workflow in ("w2", "w3"):
        return "changes" if placement["target"].get("store") == "_CHANGES" else "fakes"
    if workflow == "w4":
        return "github_fake"
    channel = placement["channel"]
    return {"a Terraform state output": "state_fake", "a cost line": "cost_fake"}.get(channel, "cloud_fake")


def write_spec(path: Path, workflow: str, placements: list[dict[str, Any]], docs: Path | None = None) -> Path:
    spec = {"workflow": workflow, "placements": placements}
    if docs is not None:
        spec["docs"] = str(docs)
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return path


def install(spec_path: str | os.PathLike[str]) -> None:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    sys.meta_path.insert(0, _Finder(spec))


def environment(spec_path: Path) -> dict[str, str]:
    """What a process needs in its environment to serve the placement: the hook on PYTHONPATH and the file."""
    existing = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": os.pathsep.join(p for p in (str(HOOK), existing) if p), ENV: str(spec_path)}
