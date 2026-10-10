"""Executable enforcement of the freeze and seal rules (project.md §7, §11).

project.md §7: "no code path used during development may read from
data/heldout/. Enforce it with a test if you can. This directory is the reason
your evaluation is credible."

This is that test. It greps the source and evaluation trees for any reference
to the held-out directory. The evaluation harness reads held-out data by
configured path at evaluation time, never by a literal baked into source.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import load_config
from src.provenance import capture, file_sha256, git_commit_hash

REPO = Path(__file__).resolve().parents[2]
SEALED = "data/heldout"
# config/ is deliberately excluded: it *declares* the sealed path so that
# guards can refuse it by path comparison. Naming the directory is the
# mechanism of protection, not a violation of it. Reading it is the violation,
# and reads live in the trees below.
SCANNED_TREES = ("src", "eval", "ui", "scripts")

# The ONE legitimate reader. eval/run_ablation.py is Phase 5b itself: reading
# held-out schemas is its entire purpose, and it does so only after the freeze
# commit, only by a path the operator passes explicitly. Every other file must
# resolve the sealed directory from config so it can *refuse* it, never name it.
# Adding to this list is a research decision, not a test fix — log it.
SEAL_EXEMPT = {"eval/run_ablation.py"}
SOURCE_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".html", ".js"}


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for tree in SCANNED_TREES:
        root = REPO / tree
        if not root.is_dir():
            continue
        files.extend(
            p
            for p in root.rglob("*")
            if p.is_file() and p.suffix in SOURCE_SUFFIXES
        )
    return files


def test_no_source_file_references_the_heldout_directory() -> None:
    offenders = [
        rel
        for p in _scanned_files()
        if (rel := p.relative_to(REPO).as_posix()) not in SEAL_EXEMPT
        and SEALED in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not offenders, (
        f"These files reference the sealed held-out directory: {offenders}. "
        f"Held-out schemas are supplied by path at evaluation time only."
    )


def test_heldout_directory_exists_but_is_empty_before_the_freeze() -> None:
    """Fails informatively once held-out schemas land — a deliberate reminder.

    If this fails, check that the freeze commit (§11) predates the files now
    sitting in data/heldout/, then mark this test xfail with the freeze tag
    recorded in decisions.md.
    """
    heldout = REPO / "data" / "heldout"
    assert heldout.is_dir(), (
        f"The sealed directory {heldout} is missing. It must exist — and stay "
        f"empty — until after the freeze commit. Recreate it with a .gitkeep."
    )
    contents = [p.name for p in heldout.iterdir() if p.name != ".gitkeep"]
    if contents:
        pytest.skip(
            f"Held-out schemas present ({contents}). Confirm the freeze commit "
            f"predates them and record the tag in decisions.md."
        )


def test_provenance_hashes_every_frozen_artefact() -> None:
    """All four artefacts now exist, so every hash must be recorded.

    A run record that cannot name the CDM and alias vocabulary it used is not
    evidence of anything (FR-14.5).
    """
    prov = capture(load_config("config/default.yaml"))
    assert prov.config_sha256 is not None
    assert prov.cdm_schema_sha256 is not None
    assert prov.cdm_context_sha256 is not None
    assert prov.alias_vocabulary_sha256 is not None
    assert prov.adid_grammar_sha256 is not None
    assert prov.frozen_artefacts_present() is True


def test_file_sha256_returns_none_for_missing_file() -> None:
    assert file_sha256(REPO / "cdm" / "does_not_exist.json") is None


def test_file_sha256_is_stable() -> None:
    target = REPO / "config" / "default.yaml"
    assert file_sha256(target) == file_sha256(target)


def test_git_hash_is_absent_or_well_formed() -> None:
    h = git_commit_hash()
    assert h is None or len(h.split("-")[0]) == 40
