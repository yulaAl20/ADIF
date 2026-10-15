"""Named, versioned mapping templates for the manufacturer portal (D50).

A manufacturer can save its column choices under a name ("Spring export").
Saving under a name that already exists **never overwrites**: it adds the next
version. Restoring an old version also adds a new version (a copy), so the
version list is a complete, append-only record of what was live when — the
same reproducibility argument the gateway's own TemplateStore makes (FR-9.6).
Templates are private to the registrar that saved them.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.dbconn import connect
from src.templates.store import Template

__all__ = ["NamedTemplate", "TemplateLibrary", "TemplateLibraryError"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mapping_templates (
    registrar     TEXT NOT NULL,
    name          TEXT NOT NULL COLLATE NOCASE,
    version       INTEGER NOT NULL,
    mappings      TEXT NOT NULL,
    cdm_sha256    TEXT,
    source_file   TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    created_by    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (registrar, name, version)
);
"""


class TemplateLibraryError(Exception):
    """A template operation was refused."""


@dataclass(frozen=True)
class NamedTemplate:
    registrar: str
    name: str
    version: int
    mappings: dict[str, str]
    cdm_sha256: str | None
    source_file: str
    note: str
    created_by: str
    created_at: str

    def as_template(self) -> Template:
        """Adapter for :meth:`TemplateStore.apply`."""
        return Template(self.registrar, self.version, self.created_at, self.cdm_sha256, self.mappings)


class TemplateLibrary:
    """Append-only, per-registrar template versions."""

    def __init__(self, db_path: str | Path) -> None:
        db = str(db_path)
        if db != ":memory:":
            Path(db).parent.mkdir(parents=True, exist_ok=True)
        self._conn = connect(db)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.RLock()

    def _q(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    @staticmethod
    def _row(r: tuple) -> NamedTemplate:
        return NamedTemplate(r[0], r[1], r[2], json.loads(r[3]), r[4], r[5], r[6], r[7], r[8])

    def save(
        self, registrar: str, name: str, mappings: dict[str, str], created_by: str,
        cdm_sha256: str | None = None, source_file: str = "", note: str = "",
    ) -> NamedTemplate:
        """Save as the next version of ``name`` (version 1 if new)."""
        name = name.strip()
        if not name:
            raise TemplateLibraryError("Give the template a name.")
        if not mappings:
            raise TemplateLibraryError("There are no matched columns to save.")
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM mapping_templates WHERE registrar=? AND name=?",
                (registrar, name),
            ).fetchone()
            version = row[0] + 1
            self._conn.execute(
                "INSERT INTO mapping_templates VALUES (?,?,?,?,?,?,?,?,?)",
                (registrar, name, version, json.dumps(mappings, sort_keys=True), cdm_sha256, source_file,
                 note.strip(), created_by, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
        return self.get(registrar, name, version)

    def get(self, registrar: str, name: str, version: int | None = None) -> NamedTemplate | None:
        if version is None:
            rows = self._q(
                "SELECT * FROM mapping_templates WHERE registrar=? AND name=? ORDER BY version DESC LIMIT 1",
                (registrar, name),
            )
        else:
            rows = self._q(
                "SELECT * FROM mapping_templates WHERE registrar=? AND name=? AND version=?",
                (registrar, name, version),
            )
        return self._row(rows[0]) if rows else None

    def latest_all(self, registrar: str) -> list[tuple[NamedTemplate, int]]:
        """Latest version of each template, with its version count."""
        names = [r[0] for r in self._q(
            "SELECT name FROM mapping_templates WHERE registrar=? GROUP BY name ORDER BY MAX(created_at) DESC",
            (registrar,),
        )]
        out = []
        for n in names:
            latest = self.get(registrar, n)
            out.append((latest, latest.version))
        return out

    def versions(self, registrar: str, name: str) -> list[NamedTemplate]:
        return [self._row(r) for r in self._q(
            "SELECT * FROM mapping_templates WHERE registrar=? AND name=? ORDER BY version DESC",
            (registrar, name),
        )]

    def restore(self, registrar: str, name: str, version: int, created_by: str) -> NamedTemplate:
        """Make an old version current by copying it forward (never rewriting)."""
        old = self.get(registrar, name, version)
        if old is None:
            raise TemplateLibraryError(f"Template '{name}' has no version {version}.")
        return self.save(registrar, name, old.mappings, created_by, old.cdm_sha256, old.source_file,
                         f"Restored from version {version}.")
