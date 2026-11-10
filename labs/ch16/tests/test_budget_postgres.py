"""PostgreSQL from its portable zip: the pin, the checks every start makes, and a cluster on 127.0.0.1.

The zip-handling tests build small zips of their own and download nothing. The cluster test runs the pinned
binaries when `budget/pg/` holds them, and skips otherwise.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

import postgres
import pytest


def test_the_pin_names_one_file_and_one_digest():
    assert postgres.URL == f"https://get.enterprisedb.com/postgresql/{postgres.ASSET}"
    assert postgres.ASSET == "postgresql-16.15-5-windows-x64-binaries.zip"
    assert re.fullmatch(r"[0-9a-f]{64}", postgres.SHA256)
    assert postgres.SIZE == 373_254_386


def make_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return path


def fake_zip(tmp_path: Path) -> Path:
    return make_zip(tmp_path / "pg.zip", {
        "pgsql/bin/postgres.exe": b"postgres", "pgsql/bin/initdb.exe": b"initdb", "pgsql/bin/pg_ctl.exe": b"pg_ctl",
        "pgsql/lib/libpq.dll": b"lib", "pgsql/share/timezone/America/Toronto": b"tz",
        "pgsql/pgAdmin 4/runtime/pgAdmin4.exe": b"admin", "pgsql/doc/readme.txt": b"doc"})


def test_only_the_servers_folders_are_unpacked(tmp_path):
    count = postgres.unpack(fake_zip(tmp_path), tmp_path / "out")
    unpacked = sorted(p.relative_to(tmp_path / "out").as_posix() for p in (tmp_path / "out").rglob("*") if p.is_file())
    assert count == 5
    assert unpacked == ["pgsql/bin/initdb.exe", "pgsql/bin/pg_ctl.exe", "pgsql/bin/postgres.exe",
                        "pgsql/lib/libpq.dll", "pgsql/share/timezone/America/Toronto"]


def test_a_member_that_would_land_outside_is_refused(tmp_path):
    evil = make_zip(tmp_path / "evil.zip", {"pgsql/bin/../../../outside.txt": b"x"})
    with pytest.raises(postgres.Mismatch, match="outside"):
        postgres.unpack(evil, tmp_path / "out")
    assert not (tmp_path / "outside.txt").exists()


def test_a_zip_other_than_the_pinned_one_is_refused(tmp_path):
    path = fake_zip(tmp_path)
    with pytest.raises(postgres.Mismatch, match="expected"):
        postgres.check_zip(path)
    postgres.check_zip(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_every_start_checks_the_programs_against_the_zip(tmp_path):
    path = fake_zip(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    postgres.unpack(path, tmp_path)
    assert postgres.verified(path, tmp_path / "pgsql", digest) == tmp_path / "pgsql" / "bin"
    (tmp_path / "pgsql" / "bin" / "pg_ctl.exe").write_bytes(b"replaced")
    with pytest.raises(postgres.Mismatch, match="pg_ctl.exe"):
        postgres.verified(path, tmp_path / "pgsql", digest)


def test_start_never_waits_on_a_pipe_the_server_inherits():
    source = Path(postgres.__file__).read_text(encoding="utf-8")
    start = source[source.index("    def start(self)"):source.index("    def stop(self)")]
    assert "capture_output" not in start and "stdout=stream" in start


@pytest.mark.skipif(not (postgres.BIN / "postgres.exe").is_file(), reason="the pinned PostgreSQL isn't in budget/pg/")
def test_a_cluster_starts_on_loopback_and_stops(tmp_path):
    import psycopg

    postgres.verified()
    cluster = postgres.Cluster(data=tmp_path / "pgdata")
    cluster.init()
    cluster.start()
    try:
        cluster.wait()
        cluster.create_database("litellm")
        with psycopg.connect(cluster.url("litellm"), connect_timeout=5) as conn:
            listen = conn.execute("SHOW listen_addresses").fetchone()[0]
            version = conn.execute("SHOW server_version").fetchone()[0]
        assert listen == "127.0.0.1" and version.startswith("16.15")
        with pytest.raises(psycopg.OperationalError):  # the password is made for the run; none other works
            psycopg.connect(cluster.url("litellm").replace(cluster.password, "wrong"), connect_timeout=5)
    finally:
        cluster.stop()
    assert not (tmp_path / "pgdata" / "postmaster.pid").exists()
