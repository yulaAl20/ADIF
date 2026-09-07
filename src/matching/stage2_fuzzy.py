"""Stage 2 — fuzzy string similarity via RapidFuzz (M4, FR-4.1 to FR-4.5).

Each CDM field is scored against *every* one of its aliases, and the field
takes its best alias score. Scoring only the canonical field name would waste
the vocabulary: a header reading ``fabric_comp`` is far closer to the alias
``fabric composition`` than to a canonical name like ``fibreComposition``.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from src.analyser.profile import ColumnProfile
from src.cdm.registry import CdmRegistry
from src.config import FuzzyStage
from src.matching.models import Candidate, Stage

__all__ = ["SCORERS", "match_fuzzy"]

SCORERS = {
    "ratio": fuzz.ratio,
    "token_sort_ratio": fuzz.token_sort_ratio,
    "partial_ratio": fuzz.partial_ratio,
}


def _partial_is_safe(header: str, alias: str, cfg: FuzzyStage) -> bool:
    """Whether partial matching can be trusted for this header/alias pair.

    ``partial_ratio`` finds the best-matching substring, so a short alias
    scores 100 against any longer string that happens to contain its letters.
    The alias ``po`` sits inside ``fabric compostion``; without this guard,
    purchase-order aliases capture fabric-composition columns at full
    confidence, and the conflict resolver then demotes the column that was
    actually right.

    The failure is silent and produces confident wrong mappings, which is the
    worst combination for an evaluation.
    """
    shorter, longer = sorted((len(header), len(alias)))
    if shorter < cfg.partial_min_length:
        return False
    return longer == 0 or (shorter / longer) >= cfg.partial_min_length_ratio


def _combine(scores: list[float], rule: str) -> float:
    if rule == "max":
        return max(scores)
    if rule == "weighted_mean":
        return sum(scores) / len(scores)
    raise ValueError(f"Unknown fuzzy combine rule: {rule}")


def match_fuzzy(
    column: ColumnProfile,
    registry: CdmRegistry,
    cfg: FuzzyStage,
) -> list[Candidate]:
    """Score a column against every CDM field and return the top K.

    Args:
        column: The analysed source column.
        registry: The loaded CDM registry.
        cfg: The fuzzy stage configuration (scorers, combine rule, top_k).

    Returns:
        Candidates sorted by descending score, longest first at equal score so
        the ordering is stable rather than dependent on dict iteration (NFR-5).
    """
    scorers = [SCORERS[name] for name in cfg.scorers]
    header = column.normalised_header
    candidates: list[Candidate] = []

    for field in registry.fields:
        best_score, best_alias = 0.0, ""
        for alias in field.aliases:
            safe_partial = _partial_is_safe(header, alias, cfg)
            scores = [
                float(scorer(header, alias))
                for name, scorer in zip(cfg.scorers, scorers)
                if name != "partial_ratio" or safe_partial
            ]
            if not scores:
                continue
            combined = _combine(scores, cfg.combine)
            if combined > best_score:
                best_score, best_alias = combined, alias
        candidates.append(
            Candidate(
                cdm_field=field.name,
                raw_score=best_score,
                stage=Stage.FUZZY,
                matched_on=best_alias,
            )
        )

    candidates.sort(key=lambda c: (-c.raw_score, c.cdm_field))
    return candidates[: cfg.top_k]
