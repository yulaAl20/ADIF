"""Shared machinery for every evaluation script (M14).

One place that knows how to assemble a run: load a config with an optional
ablation overlay, build the registry and matching components, execute the
cascade against a schema file, and score it against a frozen gold standard.

Grid search, calibration fitting and the ablation ladder all go through here so
they cannot drift apart. Three scripts each building their own pipeline is how
a tuning run and an evaluation run end up subtly different, which is a very
expensive bug to discover after the numbers are in a chapter.

**Gold standard format** — one JSON file per schema in ``goldstandard/``::

    {
      "schema": "manufacturer_a",
      "frozen_at": "2026-10-05",
      "rater": "initials",
      "mappings": { "Style_No": "productIdentifier", "junk_col": "NO_MAPPING" }
    }

Headers that legitimately have no canonical target are recorded explicitly as
``NO_MAPPING`` rather than omitted. An omitted header is silently excluded from
scoring, so distractor columns would cost nothing to get wrong — which is
precisely the behaviour Schema C is designed to test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.analyser.profile import analyse_frame
from src.cdm.registry import CdmRegistry
from src.config import AdifConfig, load_config
from src.ingestion.loader import load_tabular
from src.instrumentation.timing import StageProfiler
from src.matching.arbitration import MappingResult, run_cascade
from src.matching.stage3_semantic import Embedder, MiniLMEmbedder, SemanticIndex, StubEmbedder
from src.matching.stage4_value import SignatureLibrary

__all__ = [
    "GoldStandard",
    "discover_schemas",
    "RunContext",
    "build_context",
    "load_gold_standard",
    "load_overlay",
    "run_schema",
]

FIXTURE_SCHEMA = "tests/fixtures/cdm_test.schema.json"
FIXTURE_ALIASES = "tests/fixtures/aliases_test.yaml"


SCHEMA_SUFFIXES = {".csv", ".xlsx", ".json"}
#: Sidecar files that live beside schemas but are not themselves input data.
NON_SCHEMA_SUFFIXES = (".perturbation_log.json", ".gold.json", ".meta.json")


def discover_schemas(directory: str | Path) -> list[Path]:
    """List schema files in a directory, excluding sidecar metadata.

    Perturbation logs are JSON and sit next to the schemas they describe, so
    naive extension matching treats them as input. One shared implementation
    means grid search, calibration and the ablation run can never disagree
    about what counts as a schema.

    Raises:
        SystemExit: If the directory holds no schema files, which is almost
            always a wrong path rather than an empty experiment.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise SystemExit(f"'{directory}' is not a directory.")
    found = sorted(
        p for p in directory.iterdir()
        if p.suffix.lower() in SCHEMA_SUFFIXES
        and not any(p.name.endswith(s) for s in NON_SCHEMA_SUFFIXES)
    )
    if not found:
        raise SystemExit(
            f"No schema files (.csv/.xlsx/.json) found in '{directory}'."
        )
    return found


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge an ablation overlay into a base config mapping."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_overlay(
    base_path: str | Path = "config/default.yaml",
    overlay_path: str | Path | None = None,
    **tunables: float | None,
) -> AdifConfig:
    """Load the base config, apply an ablation overlay, then explicit tunables.

    Args:
        base_path: The frozen base configuration.
        overlay_path: An ablation condition file from ``config/ablation/``.
        **tunables: ``fuzzy_threshold``, ``semantic_threshold``,
            ``value_threshold``. Supplied by grid search while it is deriving
            them; after derivation they belong in the config file instead.

    Returns:
        A validated :class:`AdifConfig`.
    """
    cfg = load_config(base_path)
    if overlay_path:
        raw = yaml.safe_load(Path(base_path).read_text(encoding="utf-8"))
        overlay = yaml.safe_load(Path(overlay_path).read_text(encoding="utf-8")) or {}
        cfg = AdifConfig.model_validate(_deep_merge(raw, overlay))
        cfg.source_path = Path(base_path)
    if (v := tunables.get("fuzzy_threshold")) is not None:
        cfg.matching.stages.fuzzy.threshold = v
    if (v := tunables.get("semantic_threshold")) is not None:
        cfg.matching.stages.semantic.threshold = v
    if (v := tunables.get("value_threshold")) is not None:
        cfg.matching.stages.value.threshold = v
    return cfg


@dataclass
class GoldStandard:
    """A frozen, dated ground-truth mapping for one schema."""

    schema: str
    frozen_at: str
    rater: str
    mappings: dict[str, str]
    path: Path

    def mappable_count(self) -> int:
        return sum(1 for v in self.mappings.values() if v != "NO_MAPPING")


def load_gold_standard(path: str | Path) -> GoldStandard:
    """Load and validate a gold standard file.

    Raises:
        ValueError: If the file lacks a freeze date. An undated ground truth
            cannot evidence that it predates the run it scores, which is the
            whole point of freezing it (project.md §11).
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("frozen_at"):
        raise ValueError(
            f"{path} has no 'frozen_at' date. A gold standard must be dated so "
            f"it can be shown to predate the runs it scores."
        )
    return GoldStandard(
        schema=data.get("schema", path.stem),
        frozen_at=data["frozen_at"],
        rater=data.get("rater", "unrecorded"),
        mappings=data["mappings"],
        path=path,
    )


@dataclass
class RunContext:
    """Everything needed to execute cascade runs repeatedly."""

    cfg: AdifConfig
    registry: CdmRegistry
    semantic_index: SemanticIndex | None
    signature_library: SignatureLibrary | None
    using_fixture_cdm: bool
    embedder_name: str


def build_context(cfg: AdifConfig, real_model: bool = False) -> RunContext:
    """Assemble the registry, semantic index and signature library once.

    Args:
        cfg: The loaded configuration.
        real_model: Use ``all-MiniLM-L6-v2`` from the local cache rather than
            the deterministic stub.

    Returns:
        A reusable :class:`RunContext`.
    """
    schema_path, alias_path = cfg.paths.cdm_schema, cfg.paths.alias_vocabulary
    fixture = not (Path(schema_path).is_file() and Path(alias_path).is_file())
    if fixture:
        schema_path, alias_path = Path(FIXTURE_SCHEMA), Path(FIXTURE_ALIASES)
    registry = CdmRegistry.load(schema_path, alias_path, cfg.normalisation)

    index = None
    embedder_name = "none"
    if cfg.matching.stages.semantic.enabled:
        embedder: Embedder = (
            MiniLMEmbedder(
                cfg.matching.stages.semantic.model,
                str(cfg.paths.embedding_cache),
                cfg.matching.stages.semantic.model_revision,
            )
            if real_model
            else StubEmbedder()
        )
        index = SemanticIndex(registry, embedder)
        embedder_name = embedder.name

    library = None
    if cfg.matching.stages.value.enabled:
        library = SignatureLibrary.load(cfg.matching.stages.value.signatures)

    return RunContext(cfg, registry, index, library, fixture, embedder_name)


def run_schema(
    schema_path: str | Path,
    context: RunContext,
    trace_memory: bool = False,
) -> tuple[MappingResult, dict[str, Any]]:
    """Execute the cascade against one schema file.

    Returns:
        The mapping result and a dict of run facts for the record.
    """
    loaded = load_tabular(schema_path, context.cfg)
    analysis = analyse_frame(loaded.frame, context.cfg)
    profiler = StageProfiler(trace_memory=trace_memory)
    result = run_cascade(
        analysis,
        context.registry,
        context.cfg,
        context.semantic_index,
        context.signature_library,
        profiler,
    )
    return result, {
        "schema_file": str(schema_path),
        "rows": analysis.row_count,
        "columns": analysis.column_count,
        "source_format": loaded.source_format,
        "stage_costs": profiler.as_dict(),
        "total_seconds": profiler.total_seconds(),
    }
