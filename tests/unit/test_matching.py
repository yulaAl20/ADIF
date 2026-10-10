"""Matching cascade tests — M3, M4, M5, M7."""

from __future__ import annotations

import pandas as pd
import pytest

from src.analyser.profile import analyse_frame
from src.cdm.registry import AliasCollisionError, CdmRegistry, CdmVocabularyError
from src.config import UnsetTunable, load_config
from src.matching.arbitration import run_cascade
from src.matching.models import NO_MAPPING, Stage
from src.matching.stage2_fuzzy import match_fuzzy
from src.matching.stage3_semantic import SemanticIndex, StubEmbedder

SCHEMA = "tests/fixtures/cdm_test.schema.json"
ALIASES = "tests/fixtures/aliases_test.yaml"
from tests.helpers import underived  # noqa: E402

BASE = load_config("config/default.yaml")
REG = CdmRegistry.load(SCHEMA, ALIASES, BASE.normalisation)


def tuned(**stage_updates):
    """Config with EXPLICIT TEST-ONLY thresholds.

    These values exist so the pipeline can be exercised. They are not derived
    and must never be copied into config/default.yaml — see decisions.md D11.
    """
    cfg = BASE.model_copy(deep=True)
    cfg.matching.stages.fuzzy.threshold = 85.0
    cfg.matching.stages.semantic.threshold = 60.0
    for stage, enabled in stage_updates.items():
        getattr(cfg.matching.stages, stage).enabled = enabled
    return cfg


def frame(*headers):
    return pd.DataFrame([["x"] * len(headers)], columns=list(headers))


def analyse(*headers):
    return analyse_frame(frame(*headers), BASE)


def index():
    return SemanticIndex(REG, StubEmbedder())


# --- registry guards -------------------------------------------------------

def test_alias_pointing_at_a_missing_cdm_field_fails_fast(tmp_path):
    """FR-3.6: a stale vocabulary must not silently half-work."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("noSuchField: ['x']\n", encoding="utf-8")
    with pytest.raises(CdmVocabularyError, match="do not exist"):
        CdmRegistry.load(SCHEMA, bad, BASE.normalisation)


def test_colliding_aliases_are_rejected(tmp_path):
    """Two fields claiming one normalised key would make Stage 1 order-dependent."""
    bad = tmp_path / "collide.yaml"
    bad.write_text("colour: ['Product_Colour']\nsize: ['product colour']\n", encoding="utf-8")
    with pytest.raises(AliasCollisionError, match="reproducible"):
        CdmRegistry.load(SCHEMA, bad, BASE.normalisation)


def test_aliases_are_normalised_with_the_same_function_as_headers():
    """If the two sides normalised differently, Stage 1 would never fire."""
    analysis = analyse("Fabric_Composition", "fabric-composition", "fabricComposition")
    for column in analysis.columns:
        assert REG.resolve_alias(column.compact_header) == "fibreComposition"


# --- stage behaviour -------------------------------------------------------

def test_alias_stage_hits_exactly_and_scores_deterministically():
    result = run_cascade(analyse("Country_of_Origin"), REG, tuned(), index())
    record = result.records[0]
    assert record.target_field == "countryOfOrigin"
    assert record.deciding_stage is Stage.ALIAS
    assert record.raw_score == 100.0


def test_fuzzy_catches_a_near_miss_the_alias_table_lacks():
    """'fabric_compostion' is a typo present in no alias list."""
    cfg = tuned(alias=False, semantic=False)
    result = run_cascade(analyse("fabric_compostion"), REG, cfg, None)
    assert result.records[0].target_field == "fibreComposition"
    assert result.records[0].deciding_stage is Stage.FUZZY


def test_fuzzy_returns_top_k_sorted_and_stable():
    column = analyse("colour").columns[0]
    ranked = match_fuzzy(column, REG, tuned().matching.stages.fuzzy)
    assert len(ranked) == BASE.matching.stages.fuzzy.top_k
    assert ranked == sorted(ranked, key=lambda c: (-c.raw_score, c.cdm_field))


def test_unmatchable_column_yields_no_mapping_and_needs_review():
    cfg = tuned(semantic=False)
    result = run_cascade(analyse("internal_batch_ref_zz"), REG, cfg, None)
    assert result.records[0].target_field == NO_MAPPING
    assert result.records[0].review_required is True


# --- cascade semantics -----------------------------------------------------

def test_cascade_exits_early_so_later_stages_never_see_an_alias_hit():
    result = run_cascade(analyse("Country_of_Origin"), REG, tuned(), index())
    assert result.stage_hits["alias"] == 1
    assert result.stage_hits["fuzzy"] == 0
    assert result.stage_fallthroughs["fuzzy"] == 0


def test_disabling_a_stage_changes_which_stage_decides():
    """This toggle is how the D10 ablation conditions are expressed."""
    full = run_cascade(analyse("Country_of_Origin"), REG, tuned(), index())
    no_alias = run_cascade(analyse("Country_of_Origin"), REG, tuned(alias=False), index())
    assert full.records[0].deciding_stage is Stage.ALIAS
    assert no_alias.records[0].deciding_stage is not Stage.ALIAS


def test_cascade_refuses_to_run_on_underived_thresholds():
    """D11 enforced at the point it matters, not just at config load."""
    with pytest.raises(UnsetTunable, match="D11"):
        run_cascade(analyse("colour"), REG, underived(BASE), index())


def test_semantic_stage_requires_an_index():
    with pytest.raises(ValueError, match="no SemanticIndex"):
        run_cascade(analyse("colour"), REG, tuned(), None)


# --- conflicts and reporting ----------------------------------------------

def test_two_columns_claiming_one_field_conflict_and_the_loser_is_flagged():
    """FR-7.5 — the loser is surfaced for review, never silently dropped."""
    result = run_cascade(analyse("Country_of_Origin", "origin"), REG, tuned(), index())
    targets = [r.target_field for r in result.records]
    assert targets.count("countryOfOrigin") == 1
    loser = next(r for r in result.records if r.conflict_flagged)
    assert loser.target_field == NO_MAPPING
    assert loser.review_required is True
    assert "Lost" in (loser.notes or "")


def test_unpopulated_mandatory_fields_are_reported():
    result = run_cascade(analyse("baseColour"), REG, tuned(), index())
    missing = result.unpopulated_mandatory(REG)
    assert {"productFamily", "productIdentifier", "fibreComposition"} <= set(missing)


def test_run_is_reproducible():
    """NFR-5: identical input and config give identical output."""
    a = run_cascade(analyse("GTIN", "baseColour", "zz_unknown"), REG, tuned(), index())
    b = run_cascade(analyse("GTIN", "baseColour", "zz_unknown"), REG, tuned(), index())
    assert [r.model_dump() for r in a.records] == [r.model_dump() for r in b.records]


def test_semantic_index_detects_a_stale_cdm(tmp_path):
    """FR-5.7 — rebuild rather than score against the wrong field set."""
    idx = index()
    assert idx.is_stale(REG) is False
    other = tmp_path / "other.json"
    other.write_text(
        '{"type":"object","required":[],"properties":{"colour":{"type":"string"}}}',
        encoding="utf-8",
    )
    empty = tmp_path / "empty.yaml"
    empty.write_text("colour: ['shade']\n", encoding="utf-8")
    assert idx.is_stale(CdmRegistry.load(other, empty, BASE.normalisation)) is True


def test_short_alias_cannot_capture_a_longer_header_via_partial_match():
    """Regression: 'po' sits inside 'fabric compostion'.

    Without the length guard, partial_ratio scored purchaseOrderReference at
    100 against a fabric-composition column, which then won the conflict and
    demoted the column that was actually correct. Confident, silent, and wrong.
    """
    from src.matching.stage2_fuzzy import _partial_is_safe

    cfg = BASE.matching.stages.fuzzy
    assert _partial_is_safe("fabric compostion", "po", cfg) is False
    assert _partial_is_safe("fabric compostion", "fabric composition", cfg) is True
    assert _partial_is_safe("colour", "color", cfg) is True


def test_real_cdm_maps_a_typo_to_fibre_composition_not_a_short_alias():
    from pathlib import Path

    import pandas as pd

    from src.analyser.profile import analyse_frame
    from src.matching.stage2_fuzzy import match_fuzzy

    if not Path("cdm/cdm_v1.0.schema.json").is_file():
        pytest.skip("real CDM not present")
    registry = CdmRegistry.load(
        "cdm/cdm_v1.0.schema.json", "cdm/aliases_v1.0.yaml", BASE.normalisation
    )
    column = analyse_frame(pd.DataFrame({"Fabric_Compostion": ["80% Cotton"]}), BASE).columns[0]
    top = match_fuzzy(column, registry, BASE.matching.stages.fuzzy)[0]
    assert top.cdm_field == "fibreComposition"


def test_minilm_embedder_passes_revision_and_survives_old_signatures(monkeypatch) -> None:
    """Regression: the real embedder crashed on sentence-transformers 2.x.

    Two defects are pinned here. ``local_files_only`` does not exist on
    SentenceTransformer 2.x, so passing it unconditionally raised TypeError and
    the grid search could never run. And ``revision`` was accepted by
    MiniLMEmbedder, written into every run record, and then never handed to the
    loader — so the reproducibility pin was decorative. Both are asserted
    against a fake whose signature mimics 2.x.
    """
    import sys
    import types

    from src.matching import stage3_semantic

    captured: dict[str, object] = {}

    class FakeOldSentenceTransformer:
        # No local_files_only: this is the 2.x signature that broke the run.
        def __init__(self, model_name_or_path, cache_folder=None, revision=None):
            captured["model"] = model_name_or_path
            captured["cache_folder"] = cache_folder
            captured["revision"] = revision

        def encode(self, texts, normalize_embeddings=True):
            return [[1.0] + [0.0] * 383 for _ in texts]

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = FakeOldSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    embedder = stage3_semantic.MiniLMEmbedder(
        "sentence-transformers/all-MiniLM-L6-v2", ".model_cache", revision="deadbeef"
    )

    assert captured["revision"] == "deadbeef", "the pinned revision must reach the loader"
    assert captured["cache_folder"] == ".model_cache"
    assert embedder.name.endswith("@deadbeef")
