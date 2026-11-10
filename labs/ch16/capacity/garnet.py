"""Garnet, a Redis-compatible store that runs natively on Windows: fetch the pinned release, check it, unpack it, run it.

Chapter 16, step 5b (companion #14, O-D8). Step 5 ran LiteLLM's rate limiter with no shared store, so each key's
window sat in the proxy's in-memory cache of 200 entries, which step 4's budget alerts filled half a minute into a
burst. LiteLLM keeps those windows in Redis when it has one, and this workstation runs neither WSL2 nor Docker, so the
lab runs Microsoft's Garnet, which speaks Redis's protocol and ships Windows builds. Its license is MIT ("Copyright (c)
Microsoft Corporation", LICENSE at the tag v2.2.5).

The pin is release v2.2.5's `win-x64-based-readytorun.zip`, a build for the .NET 10 runtime (10.0.14 on this
workstation). The project publishes no checksum file and no build attestation (`gh attestation verify` finds none);
GitHub records a SHA-256 digest for every release asset, which its release API returns, and that digest is pinned
below and read again at every fetch. Like step 4's digest for PostgreSQL, it catches a damaged or changed download,
though not a compromised host. `fetch` also records what Windows says of `GarnetServer.exe`'s Authenticode signature
(Microsoft Corporation's, on 4 November 2026); `lua54.dll` and `diskann_garnet.dll` carry none.

Only the server's own files are unpacked (`net10.0/` without the Windows service in `net10.0/Service/` and the
extensions), into `capacity/garnet/`, which git ignores. Every start checks the zip against the pin, and
`GarnetServer.exe` and `lua54.dll` against their copies in the zip.

`Server` runs one throwaway store: 127.0.0.1 only, a port chosen free, a password made for the run, Lua scripting on
and run as a transaction (`EnableLua`, `LuaTransactionMode`: Garnet locks a script's keys for the script's run, as
Redis runs a script whole), and nothing written to disk. Step 5b's probe also runs one store without the transaction
mode, to show what LiteLLM's scripts do there. The settings go in a config file that is deleted once the server is up,
so the password is never on a command line. It is stopped by its process id.

Run (from labs/ch16):  python capacity/garnet.py            # download once, check, unpack
                       python capacity/garnet.py --check    # check what is there, download nothing
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
from typing import Any

HERE = Path(__file__).resolve().parent
BUDGET = HERE.parent / "budget"  # step 4's procs.py stops a process by its id
if str(BUDGET) not in sys.path:
    sys.path.insert(0, str(BUDGET))
VERSION = "2.2.5"
ASSET = "win-x64-based-readytorun.zip"
URL = f"https://github.com/microsoft/garnet/releases/download/v{VERSION}/{ASSET}"
RELEASE_API = f"https://api.github.com/repos/microsoft/garnet/releases/tags/v{VERSION}"
# GitHub's digest for the asset, as the release API returned it on 4 November 2026 ("digest": "sha256:...").
SHA256 = "48103d4e02a90081d6050bc932227c0908947568ce1caed208e2daf095a798c3"
SIZE = 26_186_101
PREFIX = "net10.0/"
PROGRAMS = ("GarnetServer.exe", "lua54.dll")
DIR = HERE / "garnet"
ZIP = DIR / ASSET
ROOT = DIR / "net10.0"
EXE = ROOT / "GarnetServer.exe"
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


def wanted(name: str) -> bool:
    """The server's own files: everything directly under net10.0/, nothing in its subfolders."""
    inner = name[len(PREFIX):] if name.startswith(PREFIX) else ""
    return bool(inner) and "/" not in inner


def unpack(path: Path, dest: Path) -> int:
    count = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not wanted(info.filename):
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
    """GarnetServer.exe, after checking the zip against the pin and each program against the zip's copy."""
    if not path.is_file() or not (root / PROGRAMS[0]).is_file():
        raise FileNotFoundError(f"no pinned Garnet in {root.parent}; run python capacity/garnet.py")
    check_zip(path, expected)
    with zipfile.ZipFile(path) as archive:
        for program in PROGRAMS:
            inside, on_disk = member_digest(archive, PREFIX + program), sha256(root / program)
            if inside != on_disk:
                raise Mismatch(f"{program}: SHA-256 {on_disk}, but the pinned zip holds {inside}")
    return root / PROGRAMS[0]


def published_digest(url: str = RELEASE_API) -> str:
    """The digest GitHub records for the asset, read now from the release API."""
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.loads(response.read().decode("utf-8"))
    for asset in release.get("assets") or []:
        if asset.get("name") == ASSET:
            algorithm, _, digest = str(asset.get("digest") or "").partition(":")
            if algorithm != "sha256":
                raise Mismatch(f"the release API gives no SHA-256 for {ASSET}: {asset.get('digest')!r}")
            return digest.lower()
    raise Mismatch(f"release v{VERSION} has no asset named {ASSET}")


def authenticode(path: Path) -> dict:
    """What Windows says about a program's Authenticode signature (Windows only)."""
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
    """Download once, check against the pin and the digest GitHub gives now, unpack; what was checked."""
    DIR.mkdir(parents=True, exist_ok=True)
    published = published_digest()
    if published != SHA256:
        raise Mismatch(f"GitHub now gives {published} for {ASSET}; the pin is {SHA256}")
    if not ZIP.is_file():
        print(f"downloading {URL}")
        download(URL, ZIP)
    try:
        check_zip(ZIP)
    except Mismatch:
        ZIP.unlink()  # never keep a zip that isn't the pinned one
        raise
    if not EXE.is_file():
        unpack(ZIP, DIR)
    exe = verified()
    return {"version": VERSION, "asset": ASSET, "bytes": ZIP.stat().st_size, "sha256": SHA256,
            "published_sha256_matches": True, "authenticode_garnet_server_exe": authenticode(exe),
            "authenticode_lua54_dll": authenticode(ROOT / "lua54.dll")}


# --- a store on 127.0.0.1 ------------------------------------------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def settings(port: int, password: str, transaction_mode: bool = True) -> dict[str, Any]:
    """The server's configuration: loopback only, a password, Lua run as a transaction, small and in memory.
    `transaction_mode=False` is for the probe alone, which shows what LiteLLM's scripts do without it."""
    return {"Port": port, "Address": "127.0.0.1", "AuthenticationMode": "Password", "Password": password,
            "EnableLua": True, "LuaTransactionMode": transaction_mode, "LogMemorySize": "256m", "PageSize": "16m",
            "IndexMemorySize": "16m", "EnableAOF": False, "QuietMode": True, "LogLevel": "Warning"}


def _command(*args: str) -> bytes:
    return f"*{len(args)}\r\n".encode() + b"".join(f"${len(a.encode())}\r\n{a}\r\n".encode() for a in args)


def _ask(port: int, password: str, command: tuple[str, ...], expect: bytes, timeout: float) -> bool:
    """AUTH, then one command, over a raw socket, so that checking the store needs no client library."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.sendall(_command("AUTH", password) + _command(*command))
            reply = b""
            while reply.count(b"\r\n") < 2:
                chunk = conn.recv(256)
                if not chunk:
                    break
                reply += chunk
        return reply == b"+OK\r\n" + expect
    except OSError:
        return False


def ping(port: int, password: str, timeout: float = 1.0) -> bool:
    return _ask(port, password, ("PING",), b"+PONG\r\n", timeout)


def flushall(port: int, password: str, timeout: float = 5.0) -> bool:
    """Empty the store, so that a round starts with no window or counter from the round before."""
    return _ask(port, password, ("FLUSHALL",), b"+OK\r\n", timeout)


@dataclass
class Server:
    """One throwaway Garnet: settings written to a file in `work`, read at start, and deleted once it answers."""

    work: Path
    port: int = field(default_factory=free_port)
    password: str = field(default_factory=lambda: secrets.token_hex(16))
    exe: Path = EXE
    transaction_mode: bool = True
    process: subprocess.Popen | None = None
    starts: list[float] = field(default_factory=list)

    @property
    def host(self) -> str:
        return "127.0.0.1"

    @property
    def log(self) -> Path:
        return self.work / "garnet.log"

    def start(self, seconds: float = 60) -> float:
        self.work.mkdir(parents=True, exist_ok=True)
        conf = self.work / "garnet.conf.tmp"
        conf.write_text(json.dumps(settings(self.port, self.password, self.transaction_mode)), encoding="utf-8")
        started = time.monotonic()
        try:
            with self.log.open("a", encoding="utf-8") as out:
                self.process = subprocess.Popen([str(self.exe), "--config-import-path", str(conf)],
                                                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
            while time.monotonic() - started < seconds:
                if self.process.poll() is not None:
                    raise RuntimeError(f"Garnet exited {self.process.returncode}; see {self.log.name}")
                if ping(self.port, self.password):
                    took = round(time.monotonic() - started, 2)
                    self.starts.append(took)
                    return took
                time.sleep(0.2)
            raise RuntimeError(f"Garnet did not answer on 127.0.0.1:{self.port} in {seconds} s")
        finally:
            conf.unlink(missing_ok=True)

    def stop(self) -> None:
        """Stop the store by its process id and wait for it to go."""
        from procs import stop_tree

        if self.process is not None:
            stop_tree(self.process)
            self.process = None

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process is not None else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="check the zip and programs there; download nothing")
    args = parser.parse_args(argv)
    try:
        if args.check:
            exe = verified()
            print(f"{exe} is the pinned Garnet v{VERSION} (zip SHA-256 {SHA256})")
        else:
            print(json.dumps(fetch(), indent=2))
    except (Mismatch, FileNotFoundError) as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
