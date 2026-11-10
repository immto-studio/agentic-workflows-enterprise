"""The pull-request job's replay (chapter 15, step 7, E-D9): both layers over the recorded outputs, set against
the committed replay results check by check.

run_replay.replay runs the conversion check, then the workflows' scorers and both layers over every kept run, into
a scratch folder. Each file it writes is then read beside the committed one in the latest results folder: the
set's version and its source's hash, the scorer's and the lab code's hashes, the checks' definitions, and for
every run and case the scorer's verdict, the verdict the run stored, each check's ok and detail, what the
trajectory layer measured, and the differences between the layers and the scorer. Runs are matched by their label
and cases by their id, so a difference reads as a file, a run, a case, and a check. replay-summary.md is compared
as text.

A change to a scorer, a golden set, a manifest, a kept run, or a layer fails here until the replay is run again
and its new files are reviewed with the change (python run_replay.py --out results/<date>).

Run (from labs/ch15):  python ci/replay_check.py
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LAB = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import measure  # noqa: E402, F401  (puts the lab's folders on sys.path)
import registry  # noqa: E402
import run_replay  # noqa: E402

KEYS = ("run", "id", "path")  # what identifies an entry of a list: a run by its label, a case by its id, a file by its path


def latest_results(root: Path = LAB / "results") -> Path:
    """The results folder the replay's files are committed in: the latest dated one, as tests/test_replay.py reads it."""
    return sorted(p for p in root.iterdir() if p.is_dir())[-1]


def _keyed(items: list[Any]) -> dict[str, Any] | None:
    for key in KEYS:
        if items and all(isinstance(i, dict) and key in i for i in items):
            keys = [str(i[key]) for i in items]
            if len(set(keys)) == len(keys):
                return dict(zip(keys, items))
    return None


def differences(committed: Any, fresh: Any, at: str = "") -> Iterator[tuple[str, Any, Any]]:
    """(where, committed, now) for every value that differs, walking dicts by key and lists of runs, cases, or
    files by what identifies them."""
    if isinstance(committed, dict) and isinstance(fresh, dict):
        for key in list(committed) + [k for k in fresh if k not in committed]:
            where = f"{at}.{key}" if at else str(key)
            if key not in committed or key not in fresh:
                yield where, committed.get(key, "absent"), fresh.get(key, "absent")
            else:
                yield from differences(committed[key], fresh[key], where)
        return
    if isinstance(committed, list) and isinstance(fresh, list):
        a, b = _keyed(committed), _keyed(fresh)
        if a is not None and b is not None:
            for key in list(a) + [k for k in b if k not in a]:
                where = f"{at}[{key}]"
                if key not in a or key not in b:
                    yield where, "absent" if key not in a else "present", "absent" if key not in b else "present"
                else:
                    yield from differences(a[key], b[key], where)
            return
    if committed != fresh:
        yield at, committed, fresh


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + "..."


def check(committed: Path | None = None, scratch: Path | None = None) -> list[str]:
    """Every difference between a fresh replay and the committed one, one line each."""
    committed = committed or latest_results()
    with tempfile.TemporaryDirectory(prefix="ch15-replay-") as tmp:
        out = scratch or Path(tmp)
        try:
            run_replay.replay(out)
        except SystemExit as exc:  # the conversion check failed first, and nothing was replayed
            return [str(exc)]
        fresh_names = sorted(p.name for p in out.iterdir())
        kept_names = sorted(p.name for p in committed.iterdir() if p.name.startswith("replay-"))
        problems = [f"{name}: written by the replay and not committed" for name in fresh_names if name not in kept_names]
        problems += [f"{name}: committed and no longer written by the replay" for name in kept_names if name not in fresh_names]
        for name in (n for n in fresh_names if n in kept_names):
            if name.endswith(".md"):
                now = (out / name).read_text(encoding="utf-8")
                if (committed / name).read_text(encoding="utf-8").replace("\r\n", "\n") != now:
                    problems.append(f"{name}: the summary differs; run the replay again and review it")
                continue
            for where, before, after in differences(registry.read_json(committed / name), registry.read_json(out / name)):
                problems.append(f"{name} {where}: committed {_short(before)}, now {_short(after)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--committed", type=Path, help="the results folder to compare with; the latest by default")
    args = parser.parse_args(argv)
    committed = args.committed or latest_results()
    problems = check(committed)
    if problems:
        print(f"The replay differs from {registry.rel(committed)} in {len(problems)} place(s):")
        print("\n".join(f"- {p}" for p in problems))
        print("Run python run_replay.py --out results/<date> and review the new files with the change.")
        return 1
    print(f"The replay of every kept run matches {registry.rel(committed)}, check by check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
