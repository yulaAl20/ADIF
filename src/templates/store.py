"""Manufacturer mapping templates (M9, FR-9.1 to FR-9.6).

A confirmed mapping is stored and reused on the next upload from the same
manufacturer, so a factory pays the review cost once rather than every season.

**Drift is the whole test.** decisions.md D8 rejects measuring reuse on an
identical re-upload: deterministic lookup cannot fail on an identical file, so
a 100% score there would prove nothing. Real second uploads rename a few
columns, add some, drop others. :meth:`TemplateStore.apply` therefore reports
three separate counts — reused, unchanged-but-missing, and new — because
"degraded gracefully" and "silently mismatched" look identical without them.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.matching.models import MappingRecord, Stage

__all__ = ["ReuseOutcome", "Template", "TemplateStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
    manufacturer_id TEXT NOT NULL,
    version         INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    cdm_sha256      TEXT,
    mappings        TEXT NOT NULL,
    PRIMARY KEY (manufacturer_id, version)
);
"""


@dataclass(frozen=True)
class Template:
    """A stored header-to-CDM mapping for one manufacturer."""

    manufacturer_id: str
    version: int
    created_at: str
    cdm_sha256: str | None
    mappings: dict[str, str]


@dataclass
class ReuseOutcome:
    """What happened when a template met a new upload (FR-9.4, Metric 4)."""

    reused: list[str]
    drifted_missing: list[str]
    new_columns: list[str]

    def reuse_rate(self) -> float:
        """Share of template entries still present and reapplied."""
        total = len(self.reused) + len(self.drifted_missing)
        return round(len(self.reused) / total, 6) if total else 0.0


class TemplateStore:
    """SQLite-backed template persistence."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def save(
        self,
        manufacturer_id: str,
        records: list[MappingRecord],
        cdm_sha256: str | None = None,
    ) -> Template:
        """Store confirmed mappings as a new template version (FR-9.1, FR-9.6).

        Only mapped records are stored. Versioning is append-only so an earlier
        evaluation run can always be reproduced against the template that was
        actually live at the time.
        """
        mappings = {r.raw_header: r.target_field for r in records if r.is_mapped()}
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM templates WHERE manufacturer_id = ?",
                (manufacturer_id,),
            ).fetchone()
            version = int(row[0]) + 1
            created = datetime.now(timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO templates VALUES (?, ?, ?, ?, ?)",
                (manufacturer_id, version, created, cdm_sha256, json.dumps(mappings)),
            )
        return Template(manufacturer_id, version, created, cdm_sha256, mappings)

    def latest(self, manufacturer_id: str) -> Template | None:
        """Return the most recent template for a manufacturer, if any."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT manufacturer_id, version, created_at, cdm_sha256, mappings "
                "FROM templates WHERE manufacturer_id = ? "
                "ORDER BY version DESC LIMIT 1",
                (manufacturer_id,),
            ).fetchone()
        if row is None:
            return None
        return Template(row[0], row[1], row[2], row[3], json.loads(row[4]))

    def versions(self, manufacturer_id: str) -> list[int]:
        """All stored versions for a manufacturer, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT version FROM templates WHERE manufacturer_id = ? ORDER BY version",
                (manufacturer_id,),
            ).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def apply(template: Template, records: list[MappingRecord]) -> ReuseOutcome:
        """Reapply a template to a fresh upload, in place (FR-9.2 to FR-9.5).

        Template hits are marked ``Stage.TEMPLATE`` at score 100 and cleared for
        review, because a human already confirmed this exact header once.

        Columns absent from the template keep whatever the cascade decided, so
        drift degrades to normal matching rather than to failure — which is the
        behaviour D8's drifted-upload test is designed to measure.
        """
        reused: list[str] = []
        seen: set[str] = set()

        for record in records:
            target = template.mappings.get(record.raw_header)
            if target is None:
                continue
            record.target_field = target
            record.deciding_stage = Stage.TEMPLATE
            record.raw_score = 100.0
            record.review_required = False
            record.notes = (
                f"Reused from template v{template.version} "
                f"({template.created_at})."
            )
            reused.append(record.raw_header)
            seen.add(record.raw_header)

        present = {r.raw_header for r in records}
        return ReuseOutcome(
            reused=sorted(reused),
            drifted_missing=sorted(set(template.mappings) - present),
            new_columns=sorted(present - set(template.mappings)),
        )
