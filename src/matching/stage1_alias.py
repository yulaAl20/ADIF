"""Stage 1 — deterministic alias lookup (M3, FR-3.1 to FR-3.5).

Exact match of the normalised header against the alias index. Deterministic by
construction, so its raw score is a constant rather than a similarity: there is
no gradation in an exact match, and pretending otherwise would put a
meaningless number into the calibration data.
"""

from __future__ import annotations

from src.analyser.profile import ColumnProfile
from src.cdm.registry import CdmRegistry
from src.matching.models import Candidate, Stage

__all__ = ["ALIAS_SCORE", "match_alias"]

ALIAS_SCORE = 100.0


def match_alias(column: ColumnProfile, registry: CdmRegistry) -> Candidate | None:
    """Return the alias-matched candidate for a column, or ``None``.

    Args:
        column: The analysed source column.
        registry: The loaded CDM registry.

    Returns:
        A :class:`Candidate` at :data:`ALIAS_SCORE`, or ``None`` on a miss.
    """
    field = registry.resolve_alias(column.compact_header)
    if field is None:
        return None
    return Candidate(
        cdm_field=field,
        raw_score=ALIAS_SCORE,
        stage=Stage.ALIAS,
        matched_on=column.compact_header,
    )
