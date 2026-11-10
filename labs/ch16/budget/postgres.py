"""PostgreSQL from its portable Windows binaries: fetch the pinned zip, check it, unpack it, run a cluster.

Chapter 16, step 4 (companion #14, O-D7). LiteLLM keeps key budgets, their resets and the key block in a
PostgreSQL database (fact sheet 8.1), and this workstation runs no Docker, so the lab runs PostgreSQL from
EnterpriseDB's zip of the server's binaries, the archive EDB's page "Binaries from installer" links for
version 16.15. LiteLLM's own Compose file runs `postgres:16`. The zip's SHA-256 is pinned below. EDB
publishes it in a file beside the zip on the same host (`<zip>.sha256`), so the pin guards against a
changed or damaged download, though not against that host. `fetch` reads the published file again and
refuses if it no longer says the same, and records whether Windows trusts the Authenticode signature on
`postgres.exe`.

The zip and what is unpacked from it stay in `budget/pg/`, which git ignores. Only the server's `bin`,
`lib` and `share` folders are unpacked; pgAdmin, StackBuilder and the headers stay in the zip. Every
start checks the zip against the pin and the three programs the lab runs against their copies inside the
zip, as step 3's `collector/fetch.py` does for the Collector.

Run (from labs/ch16):  python budget/postgres.py            # download once, check, unpack
                       python budget/postgres.py --check    # check what is there, download nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "16.15-5"
ASSET = f"postgresql-{VERSION}-windows-x64-binaries.zip"
URL = f"https://get.enterprisedb.com/postgresql/{ASSET}"
# EDB's page https://www.enterprisedb.com/download-postgresql-binaries links "Version 16.15", Windows x86-64,
# as https://sbp.enterprisedb.com/getfile.jsp?fileid=1260623, which redirects to URL. Read 3 November 2026.
PAGE_LINK = "https://sbp.enterprisedb.com/getfile.jsp?fileid=1260623"
# The published checksum file, URL + ".sha256", read on 3 November 2026: "<digest>  <asset>".
SHA256 = "43bb45f173a6f08cf1d29a97a6d8deb119e8e8093a24c00d2d1001a0ccaa8281"
SIZE = 373_254_386
PREFIX = "pgsql/"
UNPACKED = ("bin/", "lib/", "share/")
PROGRAMS = ("postgres.exe", "initdb.exe", "pg_ctl.exe")
PG = HERE / "pg"
ZIP = PG / ASSET
ROOT = PG / "pgsql"
BIN = ROOT / "bin"
CHUNK = 1 << 20


class Mismatch(RuntimeError):
    """A zip or a program that isn't the pinned one."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def check_zip(path: Path, expected: str = SHA256) -> None:
    actual = sha256(path)
    if actual != expected:
        raise Mismatch(f"{Path(path).name}: SHA-256 {actual}, expected {expected}")


def member_digest(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name) as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def unpack(path: Path, dest: Path) -> int:
    """Unpack the server's bin, lib and share folders; the zip's other folders stay in the zip."""
    count = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            inner = info.filename[len(PREFIX):] if info.filename.startswith(PREFIX) else ""
            if not inner.startswith(UNPACKED) or info.is_dir():
                continue
            target = (dest / info.filename).resolve()
            if dest.resolve() not in target.parents:  # no member may write outside the folder
                raise Mismatch(f"{info.filename} would unpack outside {dest}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out, CHUNK)
            count += 1
    return count


def verified(path: Path = ZIP, root: Path = ROOT, expected: str = SHA256) -> Path:
    """The bin folder, after checking the zip against the pin and each program against the zip's copy."""
    if not path.is_file() or not (root / "bin" / PROGRAMS[0]).is_file():
        raise FileNotFoundError(f"no pinned PostgreSQL in {root.parent}; run python budget/postgres.py")
    check_zip(path, expected)
    with zipfile.ZipFile(path) as archive:
        for program in PROGRAMS:
            inside = member_digest(archive, f"{PREFIX}bin/{program}")
            on_disk = sha256(root / "bin" / program)
            if inside != on_disk:
                raise Mismatch(f"{program}: SHA-256 {on_disk}, but the pinned zip holds {inside}")
    return root / "bin"


def published_digest(url: str = URL + ".sha256") -> str:
    """The digest EDB publishes beside the zip, read now."""
    with urllib.request.urlopen(url, timeout=60) as response:
        text = response.read().decode("ascii", "replace").strip()
    digest, _, name = text.partition("  ")
    if name.strip() != ASSET:
        raise Mismatch(f"{url} names {name.strip()!r}, not {ASSET}")
    return digest.lower()


def authenticode(path: Path) -> dict:
    """What Windows says about the program's Authenticode signature (Windows only)."""
    if os.name != "nt":
        return {"checked": False, "why": "Authenticode is checked on Windows only"}
    script = (f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; "
              "[pscustomobject]@{status = [string]$s.Status; signer = $s.SignerCertificate.Subject; "
              "issuer = $s.SignerCertificate.Issuer; timestamped = [bool]$s.TimeStamperCertificate} "
              "| ConvertTo-Json -Compress")
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=60)
    try:
        return {"checked": True, **json.loads(done.stdout)}
    except json.JSONDecodeError:
        return {"checked": False, "why": (done.stderr or done.stdout).strip()[:300]}


def download(url: str, dest: Path) -> None:
    partial = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out, CHUNK)
    partial.replace(dest)


def fetch() -> dict:
    """Download once, check against the pin and the published file, unpack; what was checked."""
    PG.mkdir(parents=True, exist_ok=True)
    published = published_digest()
    if published != SHA256:
        raise Mismatch(f"EDB now publishes {published} for {ASSET}; the pin is {SHA256}")
    if not ZIP.is_file():
        print(f"downloading {URL}")
        download(URL, ZIP)
    try:
        check_zip(ZIP)
    except Mismatch:
        ZIP.unlink()  # never keep a zip that isn't the pinned one
        raise
    if not (BIN / PROGRAMS[0]).is_file():
        unpack(ZIP, PG)
    verified()
    return {"version": VERSION, "asset": ASSET, "bytes": ZIP.stat().st_size, "sha256": SHA256,
            "published_sha256_matches": True, "authenticode_postgres_exe": authenticode(BIN / "postgres.exe")}


# --- a cluster on 127.0.0.1 ------------------------------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Cluster:
    """One throwaway cluster: initdb into `data`, listen on 127.0.0.1 only, with a password made per run."""

    data: Path
    port: int = field(default_factory=free_port)
    password: str = field(default_factory=lambda: secrets.token_hex(16))
    user: str = "postgres"
    bin: Path = BIN

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        done = subprocess.run([str(self.bin / args[0]), *args[1:]], capture_output=True, text=True,
                              timeout=180, env={**os.environ, "PGPASSWORD": self.password})
        if done.returncode:
            raise RuntimeError(f"{args[0]} exited {done.returncode}: {(done.stderr or done.stdout).strip()[:600]}")
        return done

    def init(self) -> None:
        self.data.parent.mkdir(parents=True, exist_ok=True)
        pwfile = self.data.parent / "pwfile.tmp"
        pwfile.write_text(self.password + "\n", encoding="ascii")
        try:
            self._run("initdb.exe", "-D", str(self.data), "-U", self.user, "-A", "scram-sha-256",
                      f"--pwfile={pwfile}", "-E", "UTF8", "--locale=C")
        finally:
            pwfile.unlink(missing_ok=True)

    @property
    def log(self) -> Path:
        return self.data.parent / "postgres.log"

    def start(self) -> None:
        # Not through a pipe: the server pg_ctl leaves running inherits pg_ctl's handles, so a captured
        # stdout would never reach its end and the caller would wait for ever.
        out = self.data.parent / "pg_ctl.log"
        with out.open("a", encoding="utf-8") as stream:
            done = subprocess.run([str(self.bin / "pg_ctl.exe"), "-D", str(self.data), "-l", str(self.log),
                                   "-w", "-t", "60", "-o", f"-p {self.port} -c listen_addresses=127.0.0.1",
                                   "start"], stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, timeout=120)
        if done.returncode:
            raise RuntimeError(f"pg_ctl start exited {done.returncode}; see {out.name}")

    def stop(self) -> None:
        if (self.data / "postmaster.pid").exists():
            self._run("pg_ctl.exe", "-D", str(self.data), "-m", "fast", "-w", "-t", "60", "stop")

    def url(self, database: str) -> str:
        return f"postgresql://{self.user}:{self.password}@127.0.0.1:{self.port}/{database}"

    def create_database(self, name: str) -> None:
        import psycopg

        with psycopg.connect(self.url("postgres"), autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')

    def wait(self, seconds: float = 30) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    return
            except OSError:
                time.sleep(0.3)
        raise RuntimeError(f"PostgreSQL did not listen on 127.0.0.1:{self.port}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="check the zip and programs there; download nothing")
    args = parser.parse_args(argv)
    try:
        if args.check:
            verified()
            print(f"{BIN} holds the pinned PostgreSQL {VERSION} (zip SHA-256 {SHA256})")
        else:
            print(json.dumps(fetch(), indent=2))
    except (Mismatch, FileNotFoundError) as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
