"""Evidence-aware reranking — the second design iteration (D54).

The v1 decision rule (``arbitration.py``, D17) is a strict cascade: the first
stage whose best candidate clears its threshold decides the column, and no
later evidence can overturn it. On the development schemas that produced two
kinds of error the cascade cannot fix by itself:

* **Wrong acceptances.** ``has_batch_no`` (values ``1``) clears the fuzzy
  threshold for ``batchNumber``; ``weight_uom`` (values ``Kg``) for
  ``netWeight``; ``description`` (marketing copy) for ``productFamily``;
  ``Style_No`` (13-digit GTINs) is an exact alias of ``productIdentifier``.
  Each one is a header match the values contradict.
* **Lost columns.** When two columns claim one field, the loser is dropped to
  ``NO_MAPPING`` even when it had a perfectly good second candidate, and a
  header that scores just under threshold is discarded even when its values
  confirm it.

This module keeps the four matching techniques exactly as they are and
replaces only the decision taken from their output:

1. **Collect** candidates from every enabled stage — not just the first to
   fire — plus an exact alias lookup on the header with documented ERP
   custom-field prefixes and trailing unit tokens removed.
2. **Validate** each candidate against the column's values: a flag is not a
   value, a unit is not a quantity, prose is not a code, and a value
   signature that positively identifies a *different* field overrides the
   header (``goldstandard/RULEBOOK.md`` R3, turned into checks).
3. **Rank** the survivors by evidence tier, then value corroboration, then
   score. A sub-threshold header candidate survives only if its values
   corroborate it, and is always flagged for review.
4. **Assign** columns to CDM fields one-to-one, greedily in rank order, with
   ``NO_MAPPING`` always available, so a column that loses its first choice
   falls to its next *valid* candidate rather than to nothing — and never to
   an invalid one.

Every decision carries a plain-language reason in ``MappingRecord.notes``.

Confidence: the calibrator in ``config/calibrator.json`` was fitted on v1
cascade decisions. Its numbers are not valid for v2 decisions until it is
refitted on development data with this rule selected (proposal step "third").
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.analyser.profile import ColumnProfile, SchemaAnalysis
from src.cdm.registry import CdmRegistry
from src.config import AdifConfig, RerankSettings, require
from src.instrumentation.timing import StageProfiler
from src.matching.models import NO_MAPPING, Candidate, MappingRecord, Stage
from src.matching.stage1_alias import ALIAS_SCORE, match_alias
from src.matching.stage2_fuzzy import match_fuzzy
from src.matching.stage3_semantic import SemanticIndex, cosine
from src.matching.stage4_value import SignatureLibrary

__all__ = ["FieldExpectations", "run_rerank", "validate_candidate"]

#: Evidence tiers, strongest first. Mirrors v1's stage precedence so the two
#: rules disagree only where the extra evidence says they should.
TIER_ALIAS = 0
TIER_DERIVED_ALIAS = 1
TIER_FUZZY = 2
TIER_SEMANTIC = 3
TIER_VALUE = 4
TIER_CORROBORATED = 5

_STAGE_FOR_TIER = {
    TIER_ALIAS: Stage.ALIAS,
    TIER_DERIVED_ALIAS: Stage.ALIAS,
    TIER_FUZZY: Stage.FUZZY,
    TIER_SEMANTIC: Stage.SEMANTIC,
    TIER_VALUE: Stage.VALUE,
}

_NUMBER_WITH_UNIT = re.compile(r"^[-+]?\d+(?:[.,]\d+)?\s*[%A-Za-z ]{0,12}$")
_NUMBER = re.compile(r"^[-+]?\d+(?:[.,]\d+)?$")


@dataclass(frozen=True)
class FieldExpectations:
    """The value kind each CDM field expects (``config/rerank/field_expectations.yaml``)."""

    quantity: frozenset[str]
    code: frozenset[str]
    unit: frozenset[str] = frozenset()

    @classmethod
    def load(cls, path: str | Path, registry: CdmRegistry) -> FieldExpectations:
        """Load the expectation table, refusing field names the CDM does not have."""
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        quantity = frozenset(raw.get("quantity", []) or [])
        code = frozenset(raw.get("code", []) or [])
        unit = frozenset(raw.get("unit", []) or [])
        unknown = (quantity | code | unit) - set(registry.names())
        if unknown:
            raise ValueError(
                f"{path} names fields absent from the CDM: {sorted(unknown)}."
            )
        overlap = (quantity & code) | (quantity & unit) | (code & unit)
        if overlap:
            raise ValueError(f"{path} gives two kinds to: {sorted(overlap)}.")
        return cls(quantity=quantity, code=code, unit=unit)

    def kind(self, cdm_field: str) -> str:
        """Return ``quantity``, ``code``, ``unit`` or ``text``."""
        if cdm_field in self.unit:
            return "unit"
        if cdm_field in self.quantity:
            return "quantity"
        if cdm_field in self.code:
            return "code"
        return "text"


@dataclass
class _Evidence:
    """Everything known about one (column, CDM field) pairing."""

    cdm_field: str
    tier: int
    score: float
    matched_on: str
    value_score: float = 0.0
    corroborated: bool = False
    demoted: bool = False

    def sort_key(self, position: int) -> tuple:
        # A demoted header candidate ranks just after value evidence.
        rank = TIER_VALUE + 0.5 if self.demoted else self.tier
        return (rank, not self.corroborated, -self.score, position, self.cdm_field)

    def as_candidate(self) -> Candidate:
        stage = _STAGE_FOR_TIER.get(self.tier, Stage.FUZZY)
        return Candidate(
            cdm_field=self.cdm_field,
            raw_score=round(min(100.0, self.score), 4),
            stage=stage,
            matched_on=self.matched_on,
        )


# ---------------------------------------------------------------------------
# Value tests
# ---------------------------------------------------------------------------


def _values(column: ColumnProfile) -> list[str]:
    return [v.strip() for v in column.sample_values if v and v.strip()]


def is_flag(column: ColumnProfile, settings: RerankSettings) -> bool:
    """True when every sampled value is a boolean marker (R3.1)."""
    values = _values(column)
    if not values:
        return False
    flags = {f.lower() for f in settings.flag_values}
    return {v.lower() for v in values} <= flags


def is_unit_column(column: ColumnProfile, settings: RerankSettings) -> bool:
    """True when every sampled value is a unit of measure (R3.2)."""
    values = _values(column)
    if not values:
        return False
    units = {u.lower() for u in settings.unit_values}
    return {v.lower() for v in values} <= units


def is_numeric(column: ColumnProfile) -> bool:
    """True when the sampled values are quantities (bare or with a unit)."""
    values = _values(column)
    if not values:
        return False
    if column.datatype in ("integer", "float"):
        return True
    return sum(1 for v in values if _NUMBER_WITH_UNIT.match(v)) / len(values) >= 0.8


def is_prose(column: ColumnProfile, settings: RerankSettings) -> bool:
    """True when the values read as free text rather than codes (R3.3)."""
    values = _values(column)
    if not values:
        return False
    return statistics.median(len(v.split()) for v in values) >= settings.prose_min_words


def validate_candidate(
    column: ColumnProfile,
    cdm_field: str,
    kind: str,
    value_scores: dict[str, float],
    signature_fields: set[str],
    settings: RerankSettings,
    value_threshold: float | None,
) -> str | None:
    """Return the reason a candidate is invalid, or ``None`` if it survives.

    The checks look at what the column *contains*. None of them names a
    particular header.
    """
    if is_flag(column, settings):
        return f"values are a yes/no flag ({', '.join(sorted(set(_values(column))))}), not {cdm_field} (R3.1)"
    if kind != "unit" and is_unit_column(column, settings):
        sample = ", ".join(sorted(set(_values(column)))[:3])
        return f"the values ({sample}) are units of measure, which belong to a quantity column, not to {cdm_field} (R3.2)"
    if kind == "quantity" and not is_numeric(column):
        sample = ", ".join(sorted(set(_values(column)))[:3])
        return f"{cdm_field} is a quantity but the values ({sample}) are not numbers — likely a unit column (R3.2)"
    if kind == "code" and is_prose(column, settings):
        return f"{cdm_field} holds codes but the values are free text (R3.3)"
    if (
        value_threshold is not None
        and cdm_field in signature_fields
        and value_scores.get(cdm_field, 0.0) <= settings.contradiction_ceiling
    ):
        rivals = [
            f for f, s in value_scores.items()
            if f != cdm_field and s >= value_threshold
        ]
        if rivals:
            best = max(rivals, key=lambda f: (value_scores[f], f))
            return (
                f"the values do not fit {cdm_field} "
                f"({value_scores.get(cdm_field, 0.0):.0f}% conform) but fit {best} "
                f"({value_scores[best]:.0f}%) — the data overrides the header"
            )
    return None


# ---------------------------------------------------------------------------
# Header variants and semantic query
# ---------------------------------------------------------------------------


def derived_headers(column: ColumnProfile, settings: RerankSettings) -> list[tuple[str, str]]:
    """Header variants with ERP prefixes / trailing unit tokens removed.

    Returns ``(compact_key, description)`` pairs. A unit suffix is removed only
    from a numeric column, where it describes the values' unit rather than
    the column's meaning.
    """
    tokens = list(column.tokens)
    variants: list[tuple[list[str], str]] = []
    for prefix in sorted(settings.erp_prefixes, key=len, reverse=True):
        if len(tokens) > len(prefix) and tokens[: len(prefix)] == prefix:
            variants.append((tokens[len(prefix):], f"ERP prefix '{'_'.join(prefix)}_' removed"))
            break
    if is_numeric(column):
        for base, why in [(tokens, ""), *variants]:
            if len(base) > 1 and base[-1] in settings.unit_suffixes:
                variants.append((base[:-1], (why + "; " if why else "") + f"unit '{base[-1]}' removed"))
    out: list[tuple[str, str]] = []
    seen = {column.compact_header}
    for toks, why in variants:
        key = "".join(toks)
        if key and key not in seen:
            seen.add(key)
            out.append((key, why))
    return out


def semantic_query_text(column: ColumnProfile, settings: RerankSettings) -> str:
    """The text embedded for a column (improvement 5).

    ``header`` reproduces v1 exactly. ``enriched`` adds the cleaned header,
    the inferred datatype and a few sample values, so an opaque header such
    as ``x_studio_coo`` carries some meaning into the embedding.
    """
    if settings.semantic_query == "header":
        return column.normalised_header
    tokens = list(column.tokens)
    for prefix in sorted(settings.erp_prefixes, key=len, reverse=True):
        if len(tokens) > len(prefix) and tokens[: len(prefix)] == prefix:
            tokens = tokens[len(prefix):]
            break
    samples = list(dict.fromkeys(_values(column)))[:3]
    text = " ".join(tokens) or column.normalised_header
    if column.datatype not in ("string", "mixed", "unknown"):
        text += f" ({column.datatype})"
    if samples:
        text += ", for example " + ", ".join(samples)
    return text


def _semantic_ranked(
    index: SemanticIndex, column: ColumnProfile, settings: RerankSettings, top_k: int
) -> list[tuple[str, float]]:
    query = index.embedder.encode([semantic_query_text(column, settings)])[0]
    scored = [
        (name, round((cosine(query, vec) + 1.0) * 50.0, 4))
        for name, vec in zip(index.field_names, index.vectors)
    ]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored[:top_k]


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


def _collect(
    column: ColumnProfile,
    registry: CdmRegistry,
    cfg: AdifConfig,
    settings: RerankSettings,
    expectations: FieldExpectations,
    semantic_index: SemanticIndex | None,
    library: SignatureLibrary | None,
    thresholds: dict[str, float | None],
    profiler: StageProfiler,
) -> tuple[list[_Evidence], list[str]]:
    """Gather, validate and rank every candidate for one column."""
    stages = cfg.matching.stages
    enabled = set(cfg.enabled_stages())
    pool: dict[str, _Evidence] = {}
    header_scores: dict[str, float] = {}

    def offer(ev: _Evidence) -> None:
        held = pool.get(ev.cdm_field)
        if held is None or (ev.tier, -ev.score) < (held.tier, -held.score):
            pool[ev.cdm_field] = ev

    # --- value evidence first: every later check needs it ------------------
    value_scores: dict[str, float] = {}
    signature_fields: set[str] = set()
    if "value" in enabled and library is not None:
        with profiler.measure("value"):
            signature_fields = {s.cdm_field for s in library.signatures}
            for cand in library.match(column, top_k=len(signature_fields) or 1):
                value_scores[cand.cdm_field] = cand.raw_score

    # --- header stages ------------------------------------------------------
    if "alias" in enabled:
        with profiler.measure("alias"):
            cand = match_alias(column, registry)
            if cand is not None:
                offer(_Evidence(cand.cdm_field, TIER_ALIAS, ALIAS_SCORE, f"alias '{column.compact_header}'"))
            for key, why in derived_headers(column, settings):
                target = registry.resolve_alias(key)
                if target is not None:
                    offer(_Evidence(target, TIER_DERIVED_ALIAS, ALIAS_SCORE, f"alias '{key}' ({why})"))

    if "fuzzy" in enabled:
        with profiler.measure("fuzzy"):
            ranked = match_fuzzy(column, registry, stages.fuzzy)
        for c in ranked:
            header_scores[c.cdm_field] = max(header_scores.get(c.cdm_field, 0.0), c.raw_score)
            if c.raw_score >= thresholds["fuzzy"]:
                offer(_Evidence(c.cdm_field, TIER_FUZZY, c.raw_score, f"fuzzy on '{c.matched_on}'"))

    if "semantic" in enabled and semantic_index is not None:
        with profiler.measure("semantic"):
            ranked_sem = _semantic_ranked(semantic_index, column, settings, stages.semantic.top_k)
        for name, score in ranked_sem:
            header_scores[name] = max(header_scores.get(name, 0.0), score)
            if score >= thresholds["semantic"]:
                offer(_Evidence(name, TIER_SEMANTIC, score, "semantic similarity"))

    if value_scores and thresholds["value"] is not None:
        for name, score in value_scores.items():
            if score >= thresholds["value"]:
                offer(_Evidence(name, TIER_VALUE, score, "value signature"))

    # --- sub-threshold header evidence, accepted only with corroboration ----
    for name, score in header_scores.items():
        if name in pool or score < settings.header_floor:
            continue
        sig_ok = thresholds["value"] is not None and value_scores.get(name, 0.0) >= thresholds["value"]
        type_ok = expectations.kind(name) == "quantity" and is_numeric(column)
        if sig_ok or type_ok:
            basis = "its values match the field's signature" if sig_ok else "its values are numeric, as the field requires"
            offer(_Evidence(name, TIER_CORROBORATED, score,
                            f"header {score:.0f} (below threshold), corroborated: {basis}"))

    # --- corroboration and validation ---------------------------------------
    rejected: list[str] = []
    survivors: list[_Evidence] = []
    for ev in pool.values():
        ev.value_score = value_scores.get(ev.cdm_field, 0.0)
        ev.corroborated = (
            ev.tier != TIER_VALUE
            and thresholds["value"] is not None
            and ev.value_score >= thresholds["value"]
        ) or ev.tier == TIER_CORROBORATED
        reason = validate_candidate(
            column, ev.cdm_field, expectations.kind(ev.cdm_field), value_scores,
            signature_fields, settings, thresholds["value"],
        )
        if reason:
            rejected.append(f"{ev.cdm_field} rejected: {reason}")
        else:
            survivors.append(ev)
    # A fuzzy or semantic resemblance the values do not support must not
    # outrank a field the values positively identify (proposal: "a bad alias
    # or fuzzy match can block a better value-based interpretation"). Exact
    # aliases keep their place: they come from a curated vocabulary.
    if any(e.tier == TIER_VALUE for e in survivors):
        for ev in survivors:
            if ev.tier in (TIER_FUZZY, TIER_SEMANTIC) and not ev.corroborated:
                ev.demoted = True
    survivors.sort(key=lambda e: e.sort_key(column.position))
    return survivors, rejected


def run_rerank(
    analysis: SchemaAnalysis,
    registry: CdmRegistry,
    cfg: AdifConfig,
    semantic_index: SemanticIndex | None = None,
    signature_library: SignatureLibrary | None = None,
    profiler: StageProfiler | None = None,
):
    """Map a schema with the v2 decision rule. Same signature and result type as v1.

    Raises:
        ValueError: If ``matching.rerank`` settings are missing, or a stage is
            enabled without the index/library it needs.
        UnsetTunable: If an enabled stage's threshold is unset (D11).
    """
    from src.matching.arbitration import MappingResult  # local: avoids a cycle

    settings = cfg.matching.rerank
    if settings is None:
        raise ValueError("matching.arbitration is 'rerank' but matching.rerank is not configured.")
    stages = cfg.matching.stages
    enabled = set(cfg.enabled_stages())
    thresholds: dict[str, float | None] = {
        "fuzzy": require(stages.fuzzy.threshold, "matching.stages.fuzzy.threshold") if "fuzzy" in enabled else None,
        "semantic": require(stages.semantic.threshold, "matching.stages.semantic.threshold") if "semantic" in enabled else None,
        "value": require(stages.value.threshold, "matching.stages.value.threshold") if "value" in enabled else None,
    }
    if "semantic" in enabled and semantic_index is None:
        raise ValueError("The semantic stage is enabled but no SemanticIndex was supplied.")
    if "value" in enabled and signature_library is None:
        raise ValueError("The value stage is enabled but no SignatureLibrary was supplied.")
    expectations = FieldExpectations.load(settings.expectations, registry)

    profiler = profiler or StageProfiler()
    ranked: dict[int, list[_Evidence]] = {}
    rejections: dict[int, list[str]] = {}
    for column in analysis.columns:
        ranked[column.position], rejections[column.position] = _collect(
            column, registry, cfg, settings, expectations, semantic_index,
            signature_library, thresholds, profiler,
        )

    # --- global one-to-one assignment, NO_MAPPING always allowed -----------
    # Greedy in evidence order: the strongest (column, field) pair anywhere in
    # the file is fixed first. For the handful of columns in an ERP export this
    # matches the optimal assignment in practice and, unlike an LP solver, is
    # deterministic to the tie-break and explainable line by line.
    by_pos = {c.position: c for c in analysis.columns}
    pairs = sorted(
        ((ev.sort_key(pos), pos, ev) for pos, evs in ranked.items() for ev in evs),
        key=lambda x: x[0],
    )
    chosen: dict[int, _Evidence] = {}
    owner: dict[str, int] = {}
    for _, pos, ev in pairs:
        if pos in chosen or ev.cdm_field in owner:
            continue
        chosen[pos] = ev
        owner[ev.cdm_field] = pos

    records: list[MappingRecord] = []
    final_hits = {s: 0 for s in ("alias", "fuzzy", "semantic", "value")}
    fallthroughs = dict.fromkeys(final_hits, 0)
    for column in analysis.columns:
        pos = column.position
        evs = ranked[pos]
        ev = chosen.get(pos)
        notes: list[str] = []
        conflict = False
        review = False
        first = evs[0] if evs else None
        if first is not None and (ev is None or ev.cdm_field != first.cdm_field):
            conflict = True
            review = True
            taker = by_pos[owner[first.cdm_field]].raw_header
            notes.append(
                f"First choice {first.cdm_field} went to column '{taker}' (stronger evidence)"
                + (f"; reassigned to next valid candidate {ev.cdm_field}." if ev else "; no other valid candidate.")
            )
        if ev is not None:
            stage = _STAGE_FOR_TIER.get(ev.tier, Stage.FUZZY)
            final_hits[stage.value] += 1
            notes.insert(0, f"Accepted {ev.cdm_field}: {ev.matched_on}"
                         + (f"; values agree ({ev.value_score:.0f}% fit its signature)" if ev.corroborated and ev.tier != TIER_CORROBORATED else "")
                         + ".")
            if ev.tier == TIER_CORROBORATED:
                review = True
        else:
            review = True
            if not evs and not rejections[pos]:
                notes.append("No candidate cleared its stage threshold, and none below it was corroborated by the values.")
        for s in ("fuzzy", "semantic", "value"):
            if s in enabled and (ev is None or _STAGE_FOR_TIER.get(ev.tier) != Stage(s)):
                fallthroughs[s] += 1
        if rejections[pos]:
            if ev is None:
                review = True
            notes.append("Rejected: " + " | ".join(rejections[pos]) + ".")
        records.append(
            MappingRecord(
                source_position=pos,
                raw_header=column.raw_header,
                normalised_header=column.normalised_header,
                target_field=ev.cdm_field if ev else NO_MAPPING,
                deciding_stage=_STAGE_FOR_TIER.get(ev.tier, Stage.FUZZY) if ev else Stage.NONE,
                raw_score=round(min(100.0, ev.score), 4) if ev else 0.0,
                alternatives=[e.as_candidate() for e in evs if ev is None or e is not ev][:5],
                conflict_flagged=conflict,
                review_required=review,
                notes=" ".join(notes) or None,
            )
        )

    return MappingResult(
        records=records,
        stage_hits=final_hits,
        stage_fallthroughs=fallthroughs,
        embedder_name=semantic_index.embedder.name if semantic_index else None,
        stage_costs=profiler.as_dict(),
    )
