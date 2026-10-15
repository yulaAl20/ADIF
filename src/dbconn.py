"""One place that opens every ADIF store's database connection.

Locally, and in every test, each store is a SQLite file (or ``:memory:``),
exactly as before. When the environment variable ``DATABASE_URL`` holds a
PostgreSQL connection string (for example a free Neon or Supabase database),
the same stores are kept online instead, so the hosted site keeps its
registered ADIDs, accounts and templates across restarts and redeploys.

Each former SQLite file becomes its own PostgreSQL *schema* named after the
file (``var/adir_node_lk-1.sqlite`` -> schema ``adir_node_lk_1``), so two
registry nodes never share tables, just as two files never did.

The stores were written against :mod:`sqlite3`, so the PostgreSQL connection
below offers the small part of that interface they use (``execute``,
``executemany``, ``executescript``, ``fetchone``/``fetchall``/iteration) and
translates the few SQLite-only phrases they contain. No store's SQL had to
change.

``:memory:`` always stays SQLite, so tests never touch a shared database.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

__all__ = ["connect", "using_postgres", "schema_for"]


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def using_postgres(db_path: str | Path | None = None) -> bool:
    """True when ``db_path`` will be stored in the online PostgreSQL database."""
    if db_path is not None and str(db_path) == ":memory:":
        return False
    return bool(_database_url())


def schema_for(db_path: str | Path) -> str:
    """PostgreSQL schema name for what used to be one SQLite file."""
    stem = Path(str(db_path)).stem.lower()
    name = re.sub(r"[^a-z0-9_]+", "_", stem).strip("_") or "adif"
    return name if name[0].isalpha() else f"s_{name}"


def connect(db_path: str | Path) -> Any:
    """Open the store at ``db_path`` (SQLite) or its online equivalent (PostgreSQL)."""
    db = str(db_path)
    if using_postgres(db):
        return PgConnection(_database_url(), schema_for(db))
    if db != ":memory:":
        Path(db).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db, check_same_thread=False, isolation_level=None)


# --------------------------------------------------------------------- Postgres
_QMARK = re.compile(r"\?")
_OR_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO", re.I)


def _translate(sql: str) -> str:
    """Turn the SQLite phrases used by the stores into PostgreSQL."""
    out = sql.replace("%", "%%")
    ignore = bool(_OR_IGNORE.match(out))
    if ignore:
        out = _OR_IGNORE.sub("INSERT INTO", out, count=1)
    out = out.replace("COLLATE NOCASE", "")
    out = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "SERIAL PRIMARY KEY", out, flags=re.I)
    out = _QMARK.sub("%s", out)
    if ignore:
        out = out.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return out


class _Result:
    """The rows of one statement, read eagerly (like a finished sqlite3 cursor)."""

    def __init__(self, rows: list[tuple] | None) -> None:
        self._rows = rows or []
        self._i = 0

    def fetchone(self) -> tuple | None:
        if self._i >= len(self._rows):
            return None
        row = self._rows[self._i]
        self._i += 1
        return row

    def fetchall(self) -> list[tuple]:
        rows = self._rows[self._i:]
        self._i = len(self._rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class PgConnection:
    """A sqlite3-shaped connection to one schema of a PostgreSQL database.

    Autocommit, like the stores' ``isolation_level=None`` SQLite connections:
    the stores send ``BEGIN``/``COMMIT``/``ROLLBACK`` themselves. A connection
    dropped while idle (free databases suspend after a few quiet minutes) is
    reopened and the statement retried, but never inside a transaction.
    """

    def __init__(self, url: str, schema: str) -> None:
        self.url = url
        self.schema = schema
        self._lock = threading.RLock()
        self._in_tx = False
        self._conn = None
        self._open()

    def _open(self) -> None:
        import psycopg  # imported here so SQLite-only installs never need it

        self._conn = psycopg.connect(self.url, autocommit=True, connect_timeout=15)
        with self._conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cur.execute(f'SET search_path TO "{self.schema}"')

    def _run(self, sql: str, params: Iterable[Any] = (), many: bool = False) -> _Result:
        import psycopg

        head = sql.lstrip()[:8].upper()
        if head.startswith("PRAGMA"):
            return _Result(None)
        word = head.split()[0] if head.split() else ""
        text = _translate(sql)
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.closed:
                        if self._in_tx:
                            raise psycopg.OperationalError("connection lost inside a transaction")
                        self._open()
                    with self._conn.cursor() as cur:
                        if many:
                            cur.executemany(text, [tuple(p) for p in params])
                            rows = None
                        else:
                            cur.execute(text, tuple(params))
                            rows = cur.fetchall() if cur.description else None
                    break
                except psycopg.OperationalError:
                    if self._in_tx or attempt == 2:
                        if word in ("COMMIT", "ROLLBACK"):
                            self._in_tx = False
                        raise
                    self._conn = None
            if word == "BEGIN":
                self._in_tx = True
            elif word in ("COMMIT", "ROLLBACK", "END"):
                self._in_tx = False
            return _Result(rows)

    # sqlite3.Connection surface used by the stores
    def execute(self, sql: str, params: Iterable[Any] = ()) -> _Result:
        return self._run(sql, params)

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> _Result:
        seq = list(seq)
        if not seq:
            return _Result(None)
        return self._run(sql, seq, many=True)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self._run(statement)

    def commit(self) -> None:  # autocommit: nothing to do
        return None

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
