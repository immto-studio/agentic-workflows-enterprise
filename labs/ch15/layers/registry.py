"""Where each golden set, scorer, manifest, and kept run lives, and how to import a workflow's own code.

Chapter 15, step 2 (companion #13, E-D2, E-D3, E-D8). The lab reads six golden sets and every run the
workflows kept beside their results, and it reuses each workflow's scorer by importing it. Three of the
scorers are called score.py and two answer_eval.py, and two harnesses are answer.py, so two workflows'
modules can't sit in one interpreter's module table under their own names. `isolated` puts a workflow's
folders first on sys.path, and when the block ends it forgets every module the block imported from the
companion's own folders, so the next workflow imports its own. Third-party packages stay loaded. Anything
that calls a workflow's code runs inside the block, because some of that code imports more of its own
modules when it is called.

Hashes are taken with CRLF read as LF (`sha256_of`): a Windows checkout under core.autocrlf and a Linux
runner then hash the same bytes, the ones git stores.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]  # the companion repository
LAB = ROOT / "labs" / "ch15"
CASES = LAB / "cases"
W1 = "workflows/w1-knowledge-assistant"
W2 = "workflows/w2-ops-assistant"
W3 = "workflows/w3-incident"
W4 = "workflows/w4-change"
W5 = "workflows/w5-drift"


@dataclass(frozen=True)
class Workflow:
    id: str
    name: str             # how the book names it
    golden: str           # the golden set, repository-relative
    manifest: str         # the manifest the owner and the data class come from
    scorer: str           # the workflow's own scorer
    path: tuple[str, ...]  # folders put first on sys.path to import the scorer and what the layers reuse
    modules: tuple[str, ...]  # what the layers import, in order


WORKFLOWS: dict[str, Workflow] = {w.id: w for w in (
    # Chapter 5's skeleton, run as W2 with data class Internal; chapter 9's runner scores its kept runs.
    Workflow("skeleton", "chapter 5's skeleton", "labs/ch05/golden/golden-set.yaml",
             "labs/ch05/manifest/w2-ops-assistant.yaml", "labs/ch09/run_local_golden.py",
             ("labs/ch09",), ("run_local_golden",)),
    Workflow("w1", "W1, the knowledge assistant", f"{W1}/corpus/golden-questions.yaml",
             f"{W1}/manifest/w1-knowledge.yaml", f"{W1}/eval/answer_eval.py",
             (f"{W1}/eval",), ("answer_eval", "answer")),
    Workflow("w2", "W2, the operations assistant", f"{W2}/eval/golden-questions.yaml",
             f"{W2}/manifest/w2-ops-assistant.yaml", f"{W2}/eval/answer_eval.py",
             (f"{W2}/eval",), ("answer_eval", "answer", "common")),
    Workflow("w3", "W3, incident triage", f"{W3}/eval/incidents.yaml",
             f"{W3}/manifest/w3-incident.yaml", f"{W3}/eval/score.py",
             (f"{W3}/eval", f"{W3}/harness", f"{W3}/state", f"{W2}/servers"),
             ("score", "lab", "loop", "machine", "common")),
    Workflow("w4", "W4, change management", f"{W4}/eval/changes.yaml",
             f"{W4}/manifest/w4-change.yaml", f"{W4}/eval/score.py",
             (f"{W4}/eval", f"{W2}/servers"), ("score", "common")),
    Workflow("w5", "W5, drift and FinOps", f"{W5}/eval/nights.yaml",
             f"{W5}/manifest/w5-drift.yaml", f"{W5}/eval/score.py",
             (f"{W5}/eval",), ("score", "fixture_night")),
)}
ORDER = tuple(WORKFLOWS)


def path(relative: str) -> Path:
    return ROOT / relative


def rel(p: Path) -> str:
    """A repository-relative POSIX path, the same on every machine."""
    return p.resolve().relative_to(ROOT).as_posix()


def sha256_of(p: Path) -> str:
    """The file's SHA-256 with CRLF read as LF."""
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def read_jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_yaml(p: Path) -> Any:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def manifest(workflow: str) -> dict[str, Any]:
    return read_yaml(path(WORKFLOWS[workflow].manifest))


def _local(module: Any) -> bool:
    """A module loaded from the companion's own folders, the lab's own excepted."""
    file = getattr(module, "__file__", None)
    if not file:
        return False
    try:
        where = Path(file).resolve()
        where.relative_to(ROOT)
    except (ValueError, OSError):
        return False
    try:
        where.relative_to(LAB)
    except ValueError:
        return True
    return False


@contextmanager
def isolated(folders: tuple[str, ...]) -> Iterator[None]:
    """The folders first on sys.path for the block; afterwards sys.path as it was, and every module the
    block imported from the companion's folders forgotten."""
    saved = list(sys.path)
    before = set(sys.modules)
    sys.path[:0] = [str(path(f)) for f in folders]
    try:
        yield
    finally:
        sys.path[:] = saved
        for name in [n for n in sys.modules if n not in before]:
            if _local(sys.modules[name]):
                del sys.modules[name]


@contextmanager
def loaded(workflow: str) -> Iterator[SimpleNamespace]:
    """The workflow's own modules (Workflow.modules), imported under its own sys.path. Use them, and call
    their functions, only inside the block."""
    spec = WORKFLOWS[workflow]
    with isolated(spec.path):
        yield SimpleNamespace(**{name: importlib.import_module(name) for name in spec.modules})


# --- the kept runs -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Run:
    workflow: str
    model: str
    label: str            # where the run sits among the workflow's results, as the README tables name it
    folder: str           # repository-relative
    main: str             # the file that holds the outputs
    files: tuple[str, ...]  # every kept file the replay reads, repository-relative


_RUN_SUFFIX = re.compile(r"^(?P<model>.+?)-(?P<run>run\d+)$")


RESULTS = {"skeleton": "labs/ch09/results", "w1": f"{W1}/eval/results", "w2": f"{W2}/eval/results",
           "w3": f"{W3}/eval/results", "w4": f"{W4}/eval/results", "w5": f"{W5}/eval/results"}


def _results(workflow: str) -> Path:
    return path(RESULTS[workflow])


def _label(results: Path, folder: Path, extra: str = "") -> str:
    label = folder.relative_to(results).as_posix()
    return f"{label} {extra}".strip()


def kept_runs(workflow: str) -> list[Run]:
    """Every run the workflow kept, found by the file names its runners write."""
    results = _results(workflow)
    prefix = {"skeleton": "golden-", "w1": "answers-", "w2": "answers-", "w3": "runs-", "w4": "packs-",
              "w5": "packs-"}[workflow]
    pattern = f"*/{prefix}*.json" if workflow in ("skeleton", "w1", "w2", "w3") else f"**/{prefix}*.json"
    runs = []
    for main in results.glob(pattern):
        stem = main.stem.removeprefix(prefix)
        model, extra = stem, ""
        match = _RUN_SUFFIX.match(stem)
        if workflow == "w2" and match:
            model, extra = match["model"], match["run"]
        files = [main]
        if workflow in ("w4", "w5"):
            files += [p for p in (main.parent / f"results-{model}.json", main.parent / f"summary-{model}.json")
                      if p.exists()]
            for sub in (f"logs-{model}", f"nights-{model}"):
                if (main.parent / sub).is_dir():
                    files += sorted((main.parent / sub).iterdir())
        runs.append(Run(workflow, model, _label(results, main.parent, extra), rel(main.parent), rel(main),
                        tuple(rel(f) for f in files)))
    return sorted(runs, key=lambda r: (r.model, r.label))


# --- the outputs of a run, per case --------------------------------------------------------------------

def outputs(run: Run) -> dict[str, Any]:
    """The run's output for each case id the converted set uses."""
    data = read_json(path(run.main))
    if run.workflow == "skeleton":
        return {r["id"]: r for r in data["results"]}
    if run.workflow == "w1":
        return {f"{r['id']}/{r['persona']}": r for r in data["results"]}
    if run.workflow == "w2":
        return {r["id"]: r for r in data["results"]}
    if run.workflow == "w3":
        return {r["id"]: r for r in data["records"]}
    if run.workflow == "w4":
        logs = _logs(run)
        return {i: {"pack": pack, "logs": logs} for i, pack in data.items()}
    return _nights(run, data)


def stored_verdicts(run: Run) -> dict[str, bool]:
    """The verdict the run's own results file holds for each case, where it holds one."""
    folder = path(run.folder)
    data = read_json(path(run.main))
    if run.workflow == "skeleton":
        return {r["id"]: bool(r["tool_ok"] and r["facts_ok"]) for r in data["results"]}
    if run.workflow in ("w1", "w2"):
        key = (lambda r: f"{r['id']}/{r['persona']}") if run.workflow == "w1" else (lambda r: r["id"])
        return {key(r): bool(r["passed"]) for r in data["results"]}
    if run.workflow == "w3":
        failed = set(data["summary"]["failed"])
        return {r["id"]: r["id"] not in failed for r in data["records"]}
    results = folder / f"results-{run.model}.json"
    if not results.exists():
        return {}
    return {r["id"]: bool(r["pass"]) for r in read_json(results)}


def _logs(run: Run) -> dict[str, list[dict[str, Any]]] | None:
    """W4's agent logs kept beside the run (logs-<model>/), or None for a run kept before them."""
    folder = path(run.folder) / f"logs-{run.model}"
    if not folder.is_dir():
        return None
    return {p.stem: read_jsonl(p) for p in sorted(folder.glob("*.jsonl"))}


def _nights(run: Run, packs: dict[str, Any]) -> dict[str, Any]:
    """W5: per golden night, its record, the pull requests it wrote, the ledger after the run, and the log
    lines of its trace: the night's own log, the gateway's, and the four readers' one line per call."""
    folder = path(run.folder)
    nights = folder / f"nights-{run.model}"
    ledger_file = nights / "ledger.json"
    ledger = read_json(ledger_file) if ledger_file.exists() else None
    logs = folder / f"logs-{run.model}"
    lines = {p.stem: read_jsonl(p) for p in sorted(logs.glob("*.jsonl"))} if logs.is_dir() else {}
    readers = ("state-reader", "cloud-reader", "cost-reader", "policy-reader")
    out = {}
    for record_file in sorted(nights.glob("*.json")):
        if record_file.name == "ledger.json":
            continue
        record = read_json(record_file)
        trace = record.get("trace_id")
        own = [e for name, events in lines.items() if name.startswith(("night-", "alarm-"))
               for e in events if e.get("trace_id") == trace]
        out[record_file.stem] = {
            "record": record, "packs": packs.get(record_file.stem, {}), "ledger": ledger,
            "events": own if lines else None,
            "gateway": [e for e in lines.get("gateway", []) if e.get("trace_id") == trace] if lines else None,
            "readers": {r: [e for e in lines.get(r, []) if e.get("trace_id") == trace] for r in readers}
            if lines else None,
            "reader_starts": {r: [e for e in lines.get(r, []) if e.get("event") == "server_start"] for r in readers}
            if lines else None,
        }
    return out
