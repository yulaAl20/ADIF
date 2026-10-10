"""Non-functional requirement acceptance tests (project.md §10, §14).

These are the tests Definition of Done #2 means by "all non-functional
requirements are verified, including the offline test with networking disabled".
Each one asserts a claim the dissertation makes, so a failure here is a claim
that cannot be made.
"""

from __future__ import annotations

import socket
import time

import pandas as pd
import pytest

from src.analyser.profile import analyse_frame
from src.cdm.registry import CdmRegistry
from src.config import load_config
from src.matching.arbitration import run_cascade
from src.matching.stage3_semantic import SemanticIndex, StubEmbedder
from src.matching.stage4_value import SignatureLibrary

BASE = load_config("config/default.yaml")


def _registry():
    return CdmRegistry.load(
        BASE.paths.cdm_schema, BASE.paths.alias_vocabulary, BASE.normalisation
    )


def _tuned(**toggles):
    cfg = BASE.model_copy(deep=True)
    cfg.matching.stages.fuzzy.threshold = 85.0
    cfg.matching.stages.semantic.threshold = 70.0
    cfg.matching.stages.value.threshold = 80.0
    for stage, enabled in toggles.items():
        getattr(cfg.matching.stages, stage).enabled = enabled
    return cfg


# --- NFR-1: fully offline at runtime ---------------------------------------

class _BlockedSocket:
    """Any attempt to open a socket is a test failure."""

    def __init__(self, *args, **kwargs):
        raise AssertionError(
            "NFR-1 VIOLATED: the pipeline attempted a network connection at "
            "runtime. Every artefact must load from local disk. Check for a "
            "library reaching for a remote cache or a model download."
        )


def test_full_pipeline_runs_with_networking_disabled(monkeypatch, tmp_path):
    """NFR-1 — the acceptance test, not an assumption (project.md §10).

    Sockets are replaced rather than the interface being brought down, which is
    both reproducible in CI and stricter: it fails on the *attempt*, so a library
    that would silently fall back to a cache still trips it.
    """
    monkeypatch.setattr(socket, "socket", _BlockedSocket)
    monkeypatch.setattr(socket, "create_connection", _BlockedSocket)

    source = tmp_path / "offline.csv"
    source.write_text(
        "Design_Code,Style_No,baseColour,SIZE,Fabric_Composition,origin\n"
        "TOP-A,0012345678905,Navy,M,80% Cotton 20% Polyester,LK\n",
        encoding="utf-8",
    )

    cfg = _tuned(value=True)
    registry = _registry()
    from src.ingestion.loader import load_tabular
    from src.identity.adid import AdidIdentifier
    from src.validation.validator import serialise_jsonld, validate_record

    analysis = analyse_frame(load_tabular(source, cfg).frame, cfg)
    result = run_cascade(
        analysis,
        registry,
        cfg,
        SemanticIndex(registry, StubEmbedder()),
        SignatureLibrary.load(cfg.matching.stages.value.signatures),
    )
    mapped = {r.target_field: "x" for r in result.records if r.is_mapped()}
    validate_record(mapped, registry, cfg.matching.stages.value.signatures)
    serialise_jsonld(mapped, AdidIdentifier("m", "TOP-A", "Navy", "M"), registry)

    assert result.mapped(), "pipeline produced no mappings offline"


def test_no_source_module_imports_a_network_client():
    """NFR-1, statically. A runtime network call usually starts as an import."""
    from pathlib import Path

    forbidden = ("import requests", "import urllib.request", "import httpx",
                 "from requests", "urlopen(")
    offenders = []
    for path in Path("src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path}: {token}")
    assert not offenders, (
        f"NFR-1: network client usage in src/: {offenders}. The pipeline must "
        f"read every artefact from local disk."
    )


# --- NFR-4: performance on commodity hardware ------------------------------

def test_fifty_columns_by_one_thousand_rows_within_budget():
    """NFR-4 — 50 x 1,000 end to end within the stated budget (project.md §10).

    Budget is 60s excluding one-time model load. The stub embedder is used so
    the figure measures *pipeline* cost rather than model inference; the real
    model's cost is reported separately from instrumented runs (FR-14.4).
    """
    registry = _registry()
    cfg = _tuned(value=True)
    names = registry.names()
    frame = pd.DataFrame({
        f"col_{i}_{names[i % len(names)]}": [f"v{r}" for r in range(1000)]
        for i in range(50)
    })

    index = SemanticIndex(registry, StubEmbedder())
    library = SignatureLibrary.load(cfg.matching.stages.value.signatures)

    start = time.perf_counter()
    analysis = analyse_frame(frame, cfg)
    result = run_cascade(analysis, registry, cfg, index, library)
    elapsed = time.perf_counter() - start

    assert len(result.records) == 50
    assert elapsed < 60.0, (
        f"NFR-4 VIOLATED: {elapsed:.1f}s for 50x1000, budget 60s. "
        f"Record the measured figure and the test machine spec in Chapter 6."
    )


# --- NFR-5: deterministic and reproducible ---------------------------------

def test_identical_input_and_config_give_byte_identical_output(tmp_path):
    """NFR-5 — the acceptance-level repeat-run test (project.md §10)."""
    import json

    source = tmp_path / "repeat.csv"
    source.write_text(
        "Design_Code,Style_No,baseColour,SIZE,Fabric_Compostion,col_9,zz\n"
        "TOP-A,0012345678905,Navy,M,80% Cotton,LK,junk\n",
        encoding="utf-8",
    )
    from src.ingestion.loader import load_tabular

    cfg = _tuned(value=True)
    registry = _registry()
    library = SignatureLibrary.load(cfg.matching.stages.value.signatures)

    outputs = []
    for _ in range(2):
        analysis = analyse_frame(load_tabular(source, cfg).frame, cfg)
        result = run_cascade(
            analysis, registry, cfg, SemanticIndex(registry, StubEmbedder()), library
        )
        outputs.append(json.dumps(
            [r.model_dump(mode="json") for r in result.records], sort_keys=True
        ))

    assert outputs[0] == outputs[1], "NFR-5 VIOLATED: output is not reproducible"


# --- NFR-6: no magic numbers outside config --------------------------------

def test_no_threshold_literals_in_matching_source():
    """NFR-6 — every tunable externalised (project.md §10 'grep for magic numbers').

    Scoped to the matching package, where a stray literal would silently become
    an untracked tunable that no run record captures.
    """
    import re
    from pathlib import Path

    offenders = []
    for path in Path("src/matching").rglob("*.py"):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            code = line.split("#")[0]
            if re.search(r"threshold\s*[=<>]+\s*\d", code):
                offenders.append(f"{path}:{number}: {line.strip()}")
    assert not offenders, f"NFR-6: hardcoded threshold comparison: {offenders}"


# --- NFR-10: type hints and docstrings on public functions -----------------

def test_public_functions_have_docstrings():
    """NFR-10 — docstrings on all modules and public functions."""
    import ast
    from pathlib import Path

    missing = []
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if ast.get_docstring(tree) is None and path.name != "__init__.py":
            missing.append(f"{path}: module")
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_") and ast.get_docstring(node) is None:
                    missing.append(f"{path}:{node.lineno}: {node.name}()")
    assert not missing, f"NFR-10: missing docstrings: {missing[:10]}"
