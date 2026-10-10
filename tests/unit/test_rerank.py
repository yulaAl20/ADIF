"""Second design iteration (D54): evidence-aware reranking.

Each test pins one rule of the v2 decision and, where it matters, checks that
the v1 cascade is untouched by it. Headers here are illustrative, not copied
from the development schemas, so the rules are tested as rules.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from eval.runner import load_overlay
from src.analyser.profile import analyse_frame
from src.cdm.registry import CdmRegistry
from src.config import effective_fingerprint, load_config
from src.matching.arbitration import run_cascade
from src.matching.models import NO_MAPPING, Stage
from src.matching.rerank import FieldExpectations, semantic_query_text
from src.matching.stage4_value import SignatureLibrary

BASE = load_config("config/default.yaml")
REG = CdmRegistry.load(BASE.paths.cdm_schema, BASE.paths.alias_vocabulary, BASE.normalisation)
LIB = SignatureLibrary.load(BASE.matching.stages.value.signatures)


def _cfg(name: str):
    overlay = {"cascade": "config/ablation/full_cascade_value.yaml",
               "rerank": "config/ablation/rerank_v2.yaml"}[name]
    cfg = load_overlay(overlay_path=overlay)
    cfg.matching.stages.semantic.enabled = False  # never the stub (D54 rule)
    return cfg


def _map(rule: str, columns: dict[str, list[str]]):
    analysis = analyse_frame(pd.DataFrame(columns), BASE)
    result = run_cascade(analysis, REG, _cfg(rule), None, LIB)
    return {r.raw_header: r for r in result.records}


GTINS = ["0012345678905", "0012345678912", "0012345678929", "0012345678936"]


def test_frozen_default_still_selects_the_cascade():
    assert BASE.matching.arbitration == "cascade"
    assert BASE.matching.rerank is None


def test_flag_column_is_not_the_thing_it_flags():
    out = _map("rerank", {"has_batch_no": ["1", "0", "1", "1"]})
    rec = out["has_batch_no"]
    assert rec.target_field == NO_MAPPING
    assert "flag" in rec.notes and rec.review_required


def test_cascade_behaviour_on_the_same_flag_is_unchanged():
    # v1 accepts the fuzzy match; that is the documented limitation, kept as is.
    assert _map("cascade", {"has_batch_no": ["1", "0", "1", "1"]})["has_batch_no"].target_field == "batchNumber"


def test_unit_column_is_not_a_quantity():
    # Decimal weights: whole-number grams would also fit the size signature
    # ('\d{2,3}'), a known weakness of the v1.0 signature library that both
    # decision rules share (recorded in D54).
    out = _map("rerank", {"weight_uom": ["kg", "kg", "kg", "kg"],
                          "weight_per_unit": ["0.180", "0.195", "0.240", "0.255"]})
    assert out["weight_uom"].target_field == NO_MAPPING
    assert out["weight_per_unit"].target_field == "netWeight"


def test_prose_is_not_an_identifier():
    out = _map("rerank", {"description": ["Relaxed fit cotton hoodie", "Slim fit linen shirt",
                                          "Classic denim jacket", "Ribbed knit beanie"]})
    assert out["description"].target_field != "productFamily"


def test_values_override_a_contradicted_alias():
    out = _map("rerank", {"Style_No": GTINS})
    rec = out["Style_No"]
    assert rec.target_field == "gtin"
    assert "overrides the header" in rec.notes


def test_erp_prefix_is_removed_before_alias_lookup():
    out = _map("rerank", {"x_studio_lot": ["L-1", "L-2", "L-3", "L-4"]})
    rec = out["x_studio_lot"]
    assert rec.target_field == "batchNumber" and rec.deciding_stage is Stage.ALIAS


def test_unit_suffix_is_removed_only_for_numeric_columns():
    numeric = _map("rerank", {"co2_kg": ["4.2", "4.5", "5.1", "5.3"]})
    assert numeric["co2_kg"].target_field == "carbonFootprint"
    text = _map("rerank", {"co2_kg": ["low", "low", "high", "mid"]})
    assert text["co2_kg"].target_field != "carbonFootprint"


def test_loser_takes_its_next_valid_candidate_not_nothing():
    # Both columns' values identify gtin; the exact alias wins it, and the other
    # column's next valid candidate is taken instead of dropping it.
    out = _map("rerank", {"barcode": GTINS, "Style_No": GTINS})
    assert out["barcode"].target_field == "gtin"
    assert out["Style_No"].target_field != "gtin"


def test_no_mapping_is_always_allowed_in_assignment():
    out = _map("rerank", {"barcode": GTINS, "ean_copy_zz": GTINS})
    assert out["barcode"].target_field == "gtin"
    rec = out["ean_copy_zz"]
    assert rec.target_field == NO_MAPPING and rec.conflict_flagged and rec.review_required


def test_sub_threshold_header_needs_corroboration_and_is_reviewed():
    out = _map("rerank", {"weight_per_unit": ["0.18", "0.19", "0.24", "0.25"]})
    rec = out["weight_per_unit"]
    assert rec.target_field == "netWeight" and rec.review_required
    assert "below threshold" in rec.notes


def test_every_rerank_decision_explains_itself():
    out = _map("rerank", {"colour_name": ["Navy", "Red", "Black", "Olive"], "zz_unknown": ["a", "b", "c", "d"]})
    assert all(r.notes for r in out.values())


def test_rerank_requires_its_settings():
    cfg = _cfg("rerank")
    cfg.matching.rerank = None
    analysis = analyse_frame(pd.DataFrame({"colour": ["Navy"]}), BASE)
    with pytest.raises(ValueError, match="matching.rerank"):
        run_cascade(analysis, REG, cfg, None, LIB)


def test_expectations_refuse_unknown_fields(tmp_path: Path):
    bad = tmp_path / "e.yaml"
    bad.write_text("quantity: [notAField]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="absent from the CDM"):
        FieldExpectations.load(bad, REG)


def test_enriched_semantic_query_adds_values_header_mode_does_not():
    cfg = _cfg("rerank")
    col = analyse_frame(pd.DataFrame({"x_studio_coo": ["LK", "LK", "BD", "IN"]}), BASE).columns[0]
    assert semantic_query_text(col, cfg.matching.rerank) == col.normalised_header
    cfg.matching.rerank.semantic_query = "enriched"
    text = semantic_query_text(col, cfg.matching.rerank)
    assert text.startswith("coo") and "LK" in text and "studio" not in text


def test_fingerprint_separates_rules_and_names_the_stub():
    a, b = effective_fingerprint(_cfg("cascade")), effective_fingerprint(_cfg("rerank"))
    assert a["sha256"] != b["sha256"] and b["decision"] == "rerank"
    stub = effective_fingerprint(_cfg("cascade"), "stub-deterministic")
    assert stub["semantic_is_real"] is False


def test_compare_refuses_the_sealed_heldout_directory():
    from eval.compare_decision import run

    with pytest.raises(SystemExit, match="REFUSED"):
        run(Path(BASE.paths.heldout_dir), Path("goldstandard"), real_model=False)


def test_api_runs_the_evaluated_configuration_and_never_the_stub():
    from fastapi.testclient import TestClient

    import src.api.main as api

    body = TestClient(api.app).get("/health").json()
    mc = body["matching_configuration"]
    assert "value" in mc["stages"]                       # value stage on, as evaluated
    assert not str(mc["embedder"]).startswith("stub")    # stub never substituted
    if "semantic" not in mc["stages"]:
        assert any("SEMANTIC STAGE OFF" in w for w in body["warnings"])
