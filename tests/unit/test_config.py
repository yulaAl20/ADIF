"""Tests for configuration loading.

These encode two process rules as executable checks, so a later careless edit
breaks the build instead of quietly changing a result.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from src.config import UnsetTunable, load_config, require
from tests.helpers import underived

CONFIG = "config/default.yaml"


def test_config_loads_and_records_its_own_hash() -> None:
    cfg = load_config(CONFIG)
    assert cfg.version
    assert cfg.source_sha256 is not None
    assert len(cfg.source_sha256) == 64


def test_derived_thresholds_are_present_and_in_range() -> None:
    """D11, post-derivation: the grid search has run, so none may be null, and
    every one must be a plausible 0-100 score rather than a stray placeholder.

    The calibration *method* is excluded from derivation: D6 decided it (Platt).
    """
    cfg = load_config(CONFIG)
    for stage in ("fuzzy", "semantic", "value"):
        threshold = getattr(cfg.matching.stages, stage).threshold
        assert threshold is not None and 0 < threshold <= 100, stage
    assert cfg.confidence.calibration == "platt"


def test_reading_an_unset_tunable_raises_rather_than_defaulting() -> None:
    cfg = underived(load_config(CONFIG))
    with pytest.raises(UnsetTunable, match="D11"):
        require(cfg.matching.stages.fuzzy.threshold, "matching.stages.fuzzy.threshold")


def test_unset_tunables_are_enumerated() -> None:
    pending = underived(load_config(CONFIG)).unset_tunables()
    assert "matching.stages.fuzzy.threshold" in pending
    assert "confidence.bands.auto_accept" in pending


def test_arbitration_is_cascade() -> None:
    """D17: the architecture is a strict fallback cascade, matching RQ4 (D13)."""
    assert load_config(CONFIG).matching.arbitration == "cascade"


def test_value_stage_is_declared_but_not_yet_enabled() -> None:
    """M6 is in scope (project.md §13: decide at B10, not before).

    It appears in ``stage_order`` because that is the declared architecture,
    but stays toggled off until B11 exists, so ``enabled_stages()`` can never
    claim a stage that has not been built. Flip both this assertion and the
    config toggle together when B11 lands.
    """
    cfg = load_config(CONFIG)
    assert "value" in cfg.matching.stage_order
    assert cfg.matching.stages.value.enabled is False


def test_enabled_stages_respects_toggles() -> None:
    assert load_config(CONFIG).enabled_stages() == ["alias", "fuzzy", "semantic"]


def test_unknown_config_key_is_rejected(tmp_path) -> None:
    """A typo in a frozen config file must fail loudly, not be ignored."""
    with open(CONFIG, "rb") as fh:
        data = yaml.safe_load(fh)
    data["matching"]["stages"]["fuzzy"]["thresholdd"] = 85
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(bad)
