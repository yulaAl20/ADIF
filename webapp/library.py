from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = "var/template_library.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_templates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    company       TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    source_file   TEXT NOT NULL DEFAULT '',
    cdm_sha256    TEXT,
    mappings      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""


class LibraryError(Exception):
    pass


@dataclass(frozen=True)
class SavedTemplate:
    id: int
    name: str
    company: str
    notes: str
    source_file: str
    cdm_sha256: str | None
    mappings: dict[str, str]
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(row: tuple) -> SavedTemplate:
    return SavedTemplate(
        id=row[0],
        name=row[1],
        company=row[2],
        notes=row[3],
        source_file=row[4],
        cdm_sha256=row[5],
        mappings=json.loads(row[6]),
        created_at=row[7],
        updated_at=row[8],
    )


_COLUMNS = "id, name, company, notes, source_file, cdm_sha256, mappings, created_at, updated_at"


class TemplateLibrary:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _clean_name(name: str) -> str:
        name = " ".join(name.split())
        if not name:
            raise LibraryError("Please give the template a name.")
        if len(name) > 80:
            raise LibraryError("Please keep the name under 80 characters.")
        return name

    def save(
        self,
        name: str,
        mappings: dict[str, str],
        company: str = "",
        notes: str = "",
        source_file: str = "",
        cdm_sha256: str | None = None,
    ) -> int:
        name = self._clean_name(name)
        if not mappings:
            raise LibraryError("A template needs at least one column.")
        now = _now()
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO saved_templates (name, company, notes, source_file, cdm_sha256, mappings, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, company, notes, source_file, cdm_sha256, json.dumps(mappings), now, now),
                )
                return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            raise LibraryError(f"You already have a template called '{name}'. Please choose another name.") from None

    def list(self, query: str = "") -> list[SavedTemplate]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM saved_templates ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        items = [_row(r) for r in rows]
        needle = query.strip().lower()
        if not needle:
            return items
        return [
            t
            for t in items
            if needle in t.name.lower()
            or needle in t.company.lower()
            or needle in t.notes.lower()
            or any(needle in h.lower() or needle in f.lower() for h, f in t.mappings.items())
        ]

    def get(self, template_id: int) -> SavedTemplate | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM saved_templates WHERE id = ?", (template_id,)
            ).fetchone()
        return _row(row) if row else None

    def rename(self, template_id: int, new_name: str) -> None:
        new_name = self._clean_name(new_name)
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE saved_templates SET name = ?, updated_at = ? WHERE id = ?",
                    (new_name, _now(), template_id),
                )
        except sqlite3.IntegrityError:
            raise LibraryError(f"You already have a template called '{new_name}'.") from None
        if cur.rowcount == 0:
            raise LibraryError("That template no longer exists.")

    def delete(self, template_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM saved_templates WHERE id = ?", (template_id,))

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM saved_templates").fetchone()[0])

    @staticmethod
    def _as_dict(t: SavedTemplate) -> dict:
        return {
            "name": t.name,
            "company": t.company,
            "notes": t.notes,
            "source_file": t.source_file,
            "cdm_sha256": t.cdm_sha256,
            "mappings": t.mappings,
        }

    def _export(self, templates: list[SavedTemplate]) -> str:
        return json.dumps(
            {"format": "adif-template-library", "version": 1, "templates": [self._as_dict(t) for t in templates]},
            indent=2,
        )

    def export_json(self) -> str:
        return self._export(self.list())

    def export_one(self, template_id: int) -> str:
        template = self.get(template_id)
        if template is None:
            raise LibraryError("That template no longer exists.")
        return self._export([template])

    def _unique_name(self, name: str) -> str:
        existing = {t.name.lower() for t in self.list()}
        candidate, n = name, 2
        while candidate.lower() in existing:
            candidate = f"{name} ({n})"
            n += 1
        return candidate

    def import_json(self, text: str) -> int:
        try:
            data = json.loads(text)
            items = data["templates"] if isinstance(data, dict) else data
            parsed = [
                (str(i["name"]), {str(k): str(v) for k, v in i["mappings"].items()}, i)
                for i in items
            ]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise LibraryError("This file is not a template backup made by this app.") from None
        added = 0
        for name, mappings, item in parsed:
            self.save(
                self._unique_name(self._clean_name(name)),
                mappings,
                company=str(item.get("company", "")),
                notes=str(item.get("notes", "")),
                source_file=str(item.get("source_file", "")),
                cdm_sha256=item.get("cdm_sha256"),
            )
            added += 1
        return added

    def import_csv(self, text: str, name: str, valid_fields: set[str]) -> int:
        reader = csv.DictReader(io.StringIO(text))
        cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
        if "source_column" not in cols or "cdm_field" not in cols:
            raise LibraryError("The CSV needs two columns named source_column and cdm_field.")
        mappings: dict[str, str] = {}
        bad: list[str] = []
        for row in reader:
            header = (row[cols["source_column"]] or "").strip()
            field_name = (row[cols["cdm_field"]] or "").strip()
            if not header:
                continue
            if field_name not in valid_fields:
                bad.append(f"{header} → {field_name or '(blank)'}")
                continue
            mappings[header] = field_name
        if bad:
            raise LibraryError("These rows use a field name that is not recognised: " + "; ".join(bad[:8]))
        self.save(self._unique_name(self._clean_name(name)), mappings)
        return len(mappings)


@lru_cache(maxsize=1)
def get_library() -> TemplateLibrary:
    return TemplateLibrary(os.environ.get("ADIF_LIBRARY_PATH", DEFAULT_PATH))