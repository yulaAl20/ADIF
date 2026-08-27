"""Provenance capture for run records.

FR-14.5 requires every run record to embed the git commit hash, CDM version
hash, alias vocabulary version hash, embedding model revision, and a full
config snapshot. §11 leans on this: the freeze discipline is only credible if
each result can be traced back to the exact artefact that produced it.

Missing artefacts hash to ``None`` rather than raising. Early in Phase 4 the
CDM, alias vocabulary and ADID grammar do not exist yet, and a ``None`` here is
honest information — it says "this run happened before that artefact existed",
which is exactly what the freeze audit needs to see.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.config import AdifConfig

__all__ = ["RunProvenance", "capture", "file_sha256", "git_commit_hash"]

_CHUNK = 65536


def file_sha256(path: str | Path) -> str | None:
    """Return the SHA-256 of a file, or ``None`` if it does not exist.

    Args:
        path: File to hash.

    Returns:
        Lowercase hex digest, or ``None`` when the file is absent.
    """
    p = Path(path)
    if not p.is_file():
        return None
    digest = hashlib.sha256()
    with p.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit_hash() -> str | None:
    """Return the current git commit hash, or ``None`` outside a repository.

    A ``-dirty`` suffix is appended when the working tree has uncommitted
    changes, so a run record cannot silently claim to come from a clean commit.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    return f"{head}-dirty" if dirty else head


class RunProvenance(BaseModel):
    """Everything needed to reproduce or audit a single run (FR-14.5)."""

    model_config = ConfigDict(extra="forbid")

    captured_at: str
    git_commit: str | None
    config_version: str
    config_path: str | None
    config_sha256: str | None
    cdm_schema_sha256: str | None
    cdm_context_sha256: str | None
    alias_vocabulary_sha256: str | None
    adid_grammar_sha256: str | None
    embedding_model: str
    embedding_model_revision: str | None
    enabled_stages: list[str]
    unset_tunables: list[str]
    python_version: str
    platform: str

    def frozen_artefacts_present(self) -> bool:
        """True when all four artefacts frozen at the freeze gate (§11) exist."""
        return all(
            h is not None
            for h in (
                self.cdm_schema_sha256,
                self.cdm_context_sha256,
                self.alias_vocabulary_sha256,
                self.adid_grammar_sha256,
            )
        )


def capture(cfg: AdifConfig) -> RunProvenance:
    """Snapshot the current artefact state for embedding in a run record.

    Args:
        cfg: The loaded configuration, carrying its own file hash.

    Returns:
        A :class:`RunProvenance` describing this execution environment.
    """
    return RunProvenance(
        captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        git_commit=git_commit_hash(),
        config_version=cfg.version,
        config_path=str(cfg.source_path) if cfg.source_path else None,
        config_sha256=cfg.source_sha256,
        cdm_schema_sha256=file_sha256(cfg.paths.cdm_schema),
        cdm_context_sha256=file_sha256(cfg.paths.cdm_context),
        alias_vocabulary_sha256=file_sha256(cfg.paths.alias_vocabulary),
        adid_grammar_sha256=file_sha256(cfg.paths.adid_grammar),
        embedding_model=cfg.matching.stages.semantic.model,
        embedding_model_revision=cfg.matching.stages.semantic.model_revision,
        enabled_stages=cfg.enabled_stages(),
        unset_tunables=cfg.unset_tunables(),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
    )
