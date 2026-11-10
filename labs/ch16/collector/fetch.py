"""Fetch the pinned OpenTelemetry Collector, check it against the published SHA-256, and unpack it.

Chapter 16, step 3 (companion #14, O-D3). The lab runs the contrib distribution of the Collector, v0.164.0,
from its Windows tarball on the GitHub release (fact sheet 8.4). The tarball's digest is pinned below, as
the release's own checksum file publishes it, and nothing is unpacked from a tarball that doesn't match.
The tarball stays next to the binary in `collector/bin/`, which git ignores, and every start checks both:
the tarball against the pinned digest, and the binary on disk against the binary inside the tarball. A
binary that was replaced, or a tarball that was, stops the run before the Collector starts (`verified`).

Run (from labs/ch16):  python collector/fetch.py            # download once, check, unpack
                       python collector/fetch.py --check    # check what is there, download nothing
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "0.164.0"
ASSET = f"otelcol-contrib_{VERSION}_windows_amd64.tar.gz"
URL = f"https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v{VERSION}/{ASSET}"
# The release's checksum file for the tarball, otelcol-contrib_0.164.0_windows_amd64.tar.gz.sha256, read on
# 3 November 2026 (fact sheet 8.4); the release API gives the same digest.
SHA256 = "1fb8163f9036126a1bdc59eab2d7aef4e6cda36f6c1e618f2359663cae8b0f4a"
EXE_NAME = "otelcol-contrib.exe"
BIN = HERE / "bin"
TARBALL = BIN / ASSET
EXE = BIN / EXE_NAME
CHUNK = 1 << 20


class Mismatch(RuntimeError):
    """A tarball or a binary that isn't the pinned one."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def check_tarball(path: Path, expected: str = SHA256) -> None:
    actual = sha256(path)
    if actual != expected:
        raise Mismatch(f"{Path(path).name}: SHA-256 {actual}, expected {expected}")


def member_digest(tarball: Path, name: str = EXE_NAME) -> str:
    """The SHA-256 of one file inside the tarball, read without writing it anywhere."""
    with tarfile.open(tarball, "r:gz") as archive:
        member = archive.getmember(name)
        stream = archive.extractfile(member)
        if stream is None:
            raise Mismatch(f"{name} in {Path(tarball).name} isn't a regular file")
        digest = hashlib.sha256()
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
        return digest.hexdigest()


def unpack(tarball: Path, dest: Path, name: str = EXE_NAME) -> Path:
    """Unpack the one binary the lab runs; the tarball's other files stay in the tarball."""
    with tarfile.open(tarball, "r:gz") as archive:
        archive.extract(archive.getmember(name), dest, filter="data")
    return dest / name


def verified(tarball: Path = TARBALL, exe: Path = EXE, expected: str = SHA256) -> Path:
    """The binary, after checking the tarball against the pinned digest and the binary against the tarball."""
    if not tarball.is_file() or not exe.is_file():
        raise FileNotFoundError(f"no pinned Collector in {exe.parent}; run python collector/fetch.py")
    check_tarball(tarball, expected)
    inside, on_disk = member_digest(tarball, exe.name), sha256(exe)
    if inside != on_disk:
        raise Mismatch(f"{exe.name}: SHA-256 {on_disk}, but the pinned tarball holds {inside}")
    return exe


def download(url: str, dest: Path) -> None:
    partial = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out, CHUNK)
    partial.replace(dest)


def fetch() -> Path:
    BIN.mkdir(parents=True, exist_ok=True)
    if not TARBALL.is_file():
        print(f"downloading {URL}")
        download(URL, TARBALL)
    try:
        check_tarball(TARBALL)
    except Mismatch:
        TARBALL.unlink()  # never keep a tarball that isn't the pinned one
        raise
    if not EXE.is_file():
        unpack(TARBALL, BIN)
    return verified()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="check the tarball and binary there; download nothing")
    args = parser.parse_args(argv)
    try:
        exe = verified() if args.check else fetch()
    except (Mismatch, FileNotFoundError) as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2
    print(f"{exe} is the pinned Collector v{VERSION} (tarball SHA-256 {SHA256})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
