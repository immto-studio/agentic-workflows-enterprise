"""Lint the pull-request job with actionlint, pinned and checked against its release's SHA-256 (chapter 15, step 7).

actionlint is rhysd's static checker for GitHub Actions workflow files: their syntax, the expressions, the runner
labels, the actions' inputs, and the shell in `run:` where shellcheck is installed. The lab runs v1.7.12 from its
GitHub release, for this workstation (Windows) or a Linux machine. Each archive's digest is pinned below as the
release's own checksum file, actionlint_1.7.12_checksums.txt, publishes it (read on 3 November 2026; the release
API gives the same digests), and nothing is unpacked from an archive that doesn't match. The archive stays beside
the binary in ci/bin/, which git ignores, and every run checks both: the archive against the pinned digest, and the
binary on disk against the one inside the archive, as chapter 16's collector/fetch.py checks the Collector.

Run (from labs/ch15):  python ci/actionlint.py           download once, check, and lint ci/regression.yml
                       python ci/actionlint.py --check   check what is there and lint, download nothing
"""

from __future__ import annotations

import argparse
import hashlib
import io
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "1.7.12"
RELEASE = f"https://github.com/rhysd/actionlint/releases/download/v{VERSION}"
# (system, machine) -> the release's archive for it and its SHA-256 from actionlint_1.7.12_checksums.txt
ASSETS = {
    ("windows", "amd64"): (f"actionlint_{VERSION}_windows_amd64.zip",
                           "6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9"),
    ("linux", "amd64"): (f"actionlint_{VERSION}_linux_amd64.tar.gz",
                         "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"),
}
BIN = HERE / "bin"
WORKFLOW = HERE / "regression.yml"
CHUNK = 1 << 20


class Mismatch(RuntimeError):
    """An archive or a binary that isn't the pinned one."""


def asset() -> tuple[str, str, str]:
    """The archive for this machine, its digest, and the binary's name inside it."""
    system = platform.system().lower()
    machine = {"x86_64": "amd64", "amd64": "amd64"}.get(platform.machine().lower(), platform.machine().lower())
    if (system, machine) not in ASSETS:
        raise SystemExit(f"no pinned actionlint for {system}/{machine}; the lab pins {sorted(ASSETS)}")
    name, digest = ASSETS[(system, machine)]
    return name, digest, "actionlint.exe" if system == "windows" else "actionlint"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def member(archive: Path, name: str) -> bytes:
    """The binary inside the archive, read without writing it anywhere."""
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            return z.read(name)
    with tarfile.open(archive, "r:gz") as t:
        stream = t.extractfile(t.getmember(name))
        if stream is None:
            raise Mismatch(f"{name} in {archive.name} isn't a regular file")
        return stream.read()


def verified() -> Path:
    """The binary, after checking the archive against the pinned digest and the binary against the archive."""
    name, digest, exe_name = asset()
    archive, exe = BIN / name, BIN / exe_name
    if not archive.is_file() or not exe.is_file():
        raise FileNotFoundError(f"no pinned actionlint in {BIN}; run python ci/actionlint.py")
    actual = sha256(archive.read_bytes())
    if actual != digest:
        raise Mismatch(f"{archive.name}: SHA-256 {actual}, expected {digest}")
    if sha256(exe.read_bytes()) != sha256(member(archive, exe_name)):
        raise Mismatch(f"{exe.name} on disk is not the binary inside the pinned {archive.name}")
    return exe


def fetch() -> Path:
    name, digest, exe_name = asset()
    BIN.mkdir(parents=True, exist_ok=True)
    archive = BIN / name
    if not archive.is_file():
        print(f"downloading {RELEASE}/{name}")
        with urllib.request.urlopen(f"{RELEASE}/{name}", timeout=60) as response:
            data = io.BytesIO()
            shutil.copyfileobj(response, data, CHUNK)
        if sha256(data.getvalue()) != digest:
            raise Mismatch(f"{name}: the download's SHA-256 is {sha256(data.getvalue())}, expected {digest}; nothing kept")
        archive.write_bytes(data.getvalue())
    exe = BIN / exe_name
    if not exe.is_file():
        exe.write_bytes(member(archive, exe_name))
        exe.chmod(0o755)
    return verified()


def lint(exe: Path, workflow: Path = WORKFLOW) -> subprocess.CompletedProcess:
    return subprocess.run([str(exe), "-no-color", str(workflow)], capture_output=True, text=True, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="check the archive and the binary there; download nothing")
    args = parser.parse_args(argv)
    try:
        exe = verified() if args.check else fetch()
    except (Mismatch, FileNotFoundError) as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2
    version = subprocess.run([str(exe), "-version"], capture_output=True, text=True).stdout.split("\n")[0]
    done = lint(exe)
    print(done.stdout + done.stderr, end="")
    where = WORKFLOW.relative_to(HERE.parent).as_posix()
    print(f"actionlint {version} (the pinned v{VERSION}) on {where}: "
          + ("no problem found" if done.returncode == 0 else f"exit {done.returncode}"))
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
