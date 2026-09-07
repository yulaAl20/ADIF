"""Arbitration — the cascade that turns stage scores into decisions (M7).

Implements D17: a strict fallback cascade with early exit. A stage that accepts
ends the search for that column; later stages never see it.

That is a real limitation, not an implementation detail, and it belongs in
Chapter 6 rather than being quietly absorbed. Once Stage 1 accepts a wrong
alias, no later stage can correct it. FR-7.5's conflict detection catches only
the subset where two columns claim the same CDM field — a single confidently
wrong alias produces no conflict and no signal at all. It is the price paid for
the ablation ladder's clean per-stage attribution.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.analyser.profile import SchemaAnalysis
from src.cdm.registry import CdmRegistry
from src.config import AdifConfig, require
from src.instrumentation.timing import StageProfiler
from src.matching.models import NO_MAPPING, Candidate, MappingRecord, Stage
from src.matching.stage1_alias import match_alias
from src.matching.stage2_fuzzy import match_fuzzy
from src.matching.stage3_semantic import SemanticIndex
from src.matching.stage4_value import SignatureLibrary

__all__ = ["MappingResult", "run_cascade"]


@dataclass
class MappingResult:
    """The outcome of mapping one uploaded schema."""

    records: list[MappingRecord]
    stage_hits: dict[str, int]
    stage_fallthroughs: dict[str, int]
    embedder_name: str | None
    stage_costs: dict[str, dict[str, float]] = None  # type: ignore[assignment]

    def mapped(self) -> list[MappingRecord]:
        """Records that proposed a CDM target."""
        return [r for r in self.records if r.is_mapped()]

    def unmapped_columns(self) -> list[str]:
        """Source columns with no proposed target (FR-8.5)."""
        return [r.raw_header for r in self.records if not r.is_mapped()]

    def unpopulated_mandatory(self, registry: CdmRegistry) -> list[str]:
        """Mandatory CDM fields no column mapped to (FR-8.5, FR-10.3)."""
        claimed = {r.target_field for r in self.mapped()}
        return [n for n in registry.mandatory_names() if n not in claimed]


def _accept(candidate: Candidate | None, threshold: float) -> bool:
    return candidate is not None and candidate.raw_score >= threshold


def run_cascade(
    analysis: SchemaAnalysis,
    registry: CdmRegistry,
    cfg: AdifConfig,
    semantic_index: SemanticIndex | None = None,
    signature_library: SignatureLibrary | None = None,
    profiler: StageProfiler | None = None,
) -> MappingResult:
    """Run the configured stage cascade over every analysed column.

    Args:
        analysis: Output of the schema analyser.
        registry: The loaded CDM registry.
        cfg: Loaded configuration. Disabled stages are skipped, which is how
            the ablation conditions are expressed.
        semantic_index: Pre-built index. Required when the semantic stage is
            enabled; ignored otherwise.
        signature_library: Value signatures. Required when the value stage is
            enabled; ignored otherwise.
        profiler: Optional per-stage cost collector (FR-14.4).

    Returns:
        A :class:`MappingResult` carrying per-column records and the per-stage
        hit and fall-through counts FR-14.3 requires.

    Raises:
        UnsetTunable: If an enabled stage's threshold has not been derived
            (D11). The cascade will not run on invented numbers.
        ValueError: If the semantic stage is enabled without an index.
    """
    if cfg.matching.arbitration == "rerank":
        # Second design iteration (D54). Opt-in through an overlay only; the
        # frozen default.yaml still selects the v1 cascade below, unchanged.
        from src.matching.rerank import run_rerank

        return run_rerank(analysis, registry, cfg, semantic_index, signature_library, profiler)

    stages = cfg.matching.stages
    enabled = set(cfg.enabled_stages())

    fuzzy_threshold = (
        require(stages.fuzzy.threshold, "matching.stages.fuzzy.threshold")
        if "fuzzy" in enabled
        else None
    )
    semantic_threshold = (
        require(stages.semantic.threshold, "matching.stages.semantic.threshold")
        if "semantic" in enabled
        else None
    )
    value_threshold = (
        require(stages.value.threshold, "matching.stages.value.threshold")
        if "value" in enabled
        else None
    )
    if "semantic" in enabled and semantic_index is None:
        raise ValueError(
            "The semantic stage is enabled but no SemanticIndex was supplied."
        )
    if "value" in enabled and signature_library is None:
        raise ValueError(
            "The value stage is enabled but no SignatureLibrary was supplied."
        )

    profiler = profiler or StageProfiler()
    hits = {s: 0 for s in ("alias", "fuzzy", "semantic", "value")}
    fallthroughs = {s: 0 for s in ("alias", "fuzzy", "semantic", "value")}
    records: list[MappingRecord] = []

    for column in analysis.columns:
        chosen: Candidate | None = None
        alternatives: list[Candidate] = []

        if "alias" in enabled:
            with profiler.measure("alias"):
                candidate = match_alias(column, registry)
            if candidate is not None:
                chosen, hits["alias"] = candidate, hits["alias"] + 1
            else:
                fallthroughs["alias"] += 1

        if chosen is None and "fuzzy" in enabled:
            with profiler.measure("fuzzy"):
                ranked = match_fuzzy(column, registry, stages.fuzzy)
            alternatives = ranked
            if ranked and _accept(ranked[0], fuzzy_threshold):
                chosen, hits["fuzzy"] = ranked[0], hits["fuzzy"] + 1
            else:
                fallthroughs["fuzzy"] += 1

        if chosen is None and "semantic" in enabled and semantic_index is not None:
            with profiler.measure("semantic"):
                ranked = semantic_index.match(column, stages.semantic)
            alternatives = ranked or alternatives
            if ranked and _accept(ranked[0], semantic_threshold):
                chosen, hits["semantic"] = ranked[0], hits["semantic"] + 1
            else:
                fallthroughs["semantic"] += 1

        # Stage 4 runs last and only on columns every header-based stage missed
        # (FR-6.3). It is the only stage that reads the column's *values*, so it
        # is the only one that can rescue a header carrying no information at
        # all — "col_7" full of ISO 3166 codes.
        if chosen is None and "value" in enabled and signature_library is not None:
            with profiler.measure("value"):
                ranked = signature_library.match(column, stages.value.top_k)
            alternatives = ranked or alternatives
            if ranked and _accept(ranked[0], value_threshold):
                chosen, hits["value"] = ranked[0], hits["value"] + 1
            else:
                fallthroughs["value"] += 1

        records.append(
            MappingRecord(
                source_position=column.position,
                raw_header=column.raw_header,
                normalised_header=column.normalised_header,
                target_field=chosen.cdm_field if chosen else NO_MAPPING,
                deciding_stage=chosen.stage if chosen else Stage.NONE,
                raw_score=chosen.raw_score if chosen else 0.0,
                alternatives=[c for c in alternatives if chosen is None or c != chosen][:5],
                review_required=chosen is None,
            )
        )

    _resolve_conflicts(records)
    return MappingResult(
        records=records,
        stage_hits=hits,
        stage_fallthroughs=fallthroughs,
        embedder_name=semantic_index.embedder.name if semantic_index else None,
        stage_costs=profiler.as_dict(),
    )


#: Conflict precedence, strongest first. This mirrors the cascade order, which
#: already encodes how much each stage's evidence is worth: an alias hit is an
#: exact match against a curated vocabulary, a value hit is an inference from
#: data shape. Both score 100, so without this a hex-looking HS code could take
#: "colour" away from a column literally named colour_name, on nothing more
#: than its position in the file.
_STAGE_RANK = {
    Stage.TEMPLATE: 0,   # a human already confirmed it
    Stage.ALIAS: 1,
    Stage.FUZZY: 2,
    Stage.SEMANTIC: 3,
    Stage.VALUE: 4,
    Stage.NONE: 9,
}


def _resolve_conflicts(records: list[MappingRecord]) -> None:
    """Flag columns competing for one CDM field (FR-7.5).

    The claimant with the strongest evidence keeps the field: stage precedence
    first, then raw score, then source position for reproducibility (NFR-5).
    Losers are demoted to ``NO_MAPPING`` and flagged for review rather than
    silently dropped, because a demoted column is exactly what a human reviewer
    needs to see.
    """
    by_target: dict[str, list[MappingRecord]] = {}
    for record in records:
        if record.is_mapped():
            by_target.setdefault(record.target_field, []).append(record)

    for target, claimants in by_target.items():
        if len(claimants) < 2:
            continue
        claimants.sort(
            key=lambda r: (_STAGE_RANK[r.deciding_stage], -r.raw_score, r.source_position)
        )
        for loser in claimants[1:]:
            loser.conflict_flagged = True
            loser.review_required = True
            loser.notes = (
                f"Lost '{target}' to column '{claimants[0].raw_header}' "
                f"({claimants[0].deciding_stage.value} match, stronger evidence)."
            )
            loser.target_field = NO_MAPPING
