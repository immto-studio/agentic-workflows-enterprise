"""The exit drill's second store: sqlite-vec, restored from the JSON lines the first store dumps.

Chapter 3's drill dumps a knowledge store with its own export, restores the dump into a store of
another kind, and reruns the workflow's golden set (W1-D11). Here the first store is the NumPy one
and the second is a `vec0` table in SQLite with the sqlite-vec extension (0.1.9; it loads on
Windows from the standard `sqlite3`, LINKS.md, chapter 10, section G).

sqlite-vec has no list column, so a chunk's groups live in a side table, `chunk_acl`, and the
search takes `chunk_id IN (SELECT ...)`, which the extension applies before the search; the class
cap is an integer metadata column compared with `<=`, one of its documented operators. The text and
the rest of the metadata ride along as auxiliary columns. `search` has the same signature and the
same answer type as VectorStore's, so the drill compares like with like.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import sqlite_vec

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ingest"))
sys.path.insert(0, str(HERE))
from filters import sqlite_vec as acl_clause  # noqa: E402
from ingest import Chunk  # noqa: E402
from store import RANK, Hit  # noqa: E402

MAX_K = 4096  # vec0's ceiling on k


class SqliteVecStore:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        self.dimensions: int | None = None
        self.groups_seen: set[str] = set()

    def _create(self, dimensions: int) -> None:
        self.dimensions = dimensions
        self.db.execute(f"""create virtual table chunks using vec0(
            chunk_id integer primary key,
            embedding float[{dimensions}] distance_metric=cosine,
            class_rank integer,
            +payload text
        )""")
        self.db.execute("create table chunk_acl(chunk_id integer not null, access_group text not null)")
        self.db.execute("create index chunk_acl_group on chunk_acl(access_group)")

    @classmethod
    def restore(cls, dump: Path, path: str = ":memory:") -> "SqliteVecStore":
        """Load the JSON lines VectorStore.dump wrote: one chunk, its metadata and its vector a line."""
        store = cls(path)
        for rowid, line in enumerate(dump.read_text(encoding="utf-8").splitlines(), start=1):
            row = json.loads(line)
            vector = row.pop("vector")
            if store.dimensions is None:
                store._create(len(vector))
            store.db.execute("insert into chunks(chunk_id, embedding, class_rank, payload) values (?, ?, ?, ?)",
                             (rowid, sqlite_vec.serialize_float32(vector), RANK[row["classification"]], json.dumps(row)))
            store.db.executemany("insert into chunk_acl values (?, ?)", [(rowid, g) for g in row["access_groups"]])
            store.groups_seen.update(row["access_groups"])
        store.db.commit()
        return store

    def groups(self) -> frozenset[str]:
        return frozenset(self.groups_seen)

    def search(self, query: np.ndarray, k: int, groups: Iterable[str], max_class: str = "Restricted") -> list[Hit]:
        readable = sorted(set(groups) & self.groups_seen)
        if not readable or k <= 0:
            return []
        clause, params = acl_clause(readable)
        rows = self.db.execute(
            f"select payload, distance from chunks where embedding match ? and k = ? and class_rank <= ? and {clause} "
            "order by distance",
            (sqlite_vec.serialize_float32(np.asarray(query, dtype=np.float32).tolist()), min(k, MAX_K),
             RANK[max_class], *params)).fetchall()
        hits = []
        for payload, distance in rows:
            meta = json.loads(payload)
            meta["access_groups"] = tuple(meta["access_groups"])
            hits.append(Hit(Chunk(**meta), 1.0 - float(distance)))  # cosine similarity, as VectorStore reports it
        return hits
