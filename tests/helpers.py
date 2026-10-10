"""Shared test helpers."""

from __future__ import annotations

from src.config import AdifConfig


def underived(cfg: AdifConfig) -> AdifConfig:
    """A copy of ``cfg`` in its pre-derivation state: thresholds and bands null.

    The committed config now carries grid-searched thresholds, but the D11
    guards (an unset tunable raises rather than defaulting) must still be
    exercised. They are tested against this copy, never by editing the config.
    """
    cfg = cfg.model_copy(deep=True)
    for stage in ("fuzzy", "semantic", "value"):
        getattr(cfg.matching.stages, stage).threshold = None
    for band in ("auto_accept", "review", "reject"):
        setattr(cfg.confidence.bands, band, None)
    return cfg
