"""Tests for the evaluation harness, instrumentation and Stage 4 integration."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from eval.runner import discover_schemas, load_gold_standard, load_overlay
from src.cdm.registry import CdmRegistry
from src.config import UnsetTunable, load_config
from src.instrumentation.timing import StageProfiler
from src.matching.arbitration import run_cascade
from src.matching.confidence import Calibrator
from src.matching.models import MappingRecord, Stage
from src.matching.stage3_semantic import SemanticIndex, StubEmbedder
from src.matching.stage4_value import SignatureLibrary

from tests.helpers import underived  # noqa: E402

BASE = load_config("config/default.yaml")
REG = CdmRegistry.load(
    "tests/fixtures/cdm_test.schema.json",
    "tests/fixtures/aliases_test.yaml",
    BASE.normalisation,
)


def _analyse(*headers, values=None):
    import pandas as pd
    from src.analyser.profile import analyse_frame

    data = {h: (values or ["x"]) for h in headers}
    return analyse_frame(pd.DataFrame(data), BASE)


def _tuned(**toggles):
    cfg = BASE.model_copy(deep=True)
    cfg.matching.stages.fuzzy.threshold = 85.0
    cfg.matching.stages.semantic.threshold = 70.0
    cfg.matching.stages.value.threshold = 80.0
    for stage, enabled in toggles.items():
        getattr(cfg.matching.stages, stage).enabled = enabled
    return cfg


# --- Stage 4 integration ---------------------------------------------------

def test_value_stage_is_reached_and_rescues_an_uninformative_header():
    """The regression this exists to prevent: M6 built but never called."""
    cfg = _tuned(semantic=False, value=True)
    library = SignatureLibrary.load(cfg.matching.stages.value.signatures)
    analysis = _analyse("col_7", values=["LK", "IN", "BD", "VN"])
    result = run_cascade(analysis, REG, cfg, None, library)
    assert result.records[0].target_field == "countryOfOrigin"
    assert result.records[0].deciding_stage is Stage.VALUE
    assert result.stage_hits["value"] == 1


def test_value_stage_enabled_without_a_library_is_an_error():
    cfg = _tuned(semantic=False, value=True)
    with pytest.raises(ValueError, match="no SignatureLibrary"):
        run_cascade(_analyse("col_7"), REG, cfg, None, None)


def test_value_threshold_must_be_derived_like_the_others():
    cfg = underived(BASE)
    cfg.matching.stages.value.enabled = True
    cfg.matching.stages.fuzzy.threshold = 85.0
    cfg.matching.stages.semantic.enabled = False
    with pytest.raises(UnsetTunable, match="D11"):
        run_cascade(_analyse("col_7"), REG, cfg, None, SignatureLibrary.load(
            cfg.matching.stages.value.signatures))


def test_cascade_early_exit_means_value_never_sees_an_alias_hit():
    cfg = _tuned(semantic=False, value=True)
    library = SignatureLibrary.load(cfg.matching.stages.value.signatures)
    result = run_cascade(_analyse("baseColour"), REG, cfg, None, library)
    assert result.stage_hits["alias"] == 1
    assert result.stage_hits["value"] == 0


# --- instrumentation (FR-14.4) ---------------------------------------------

def test_profiler_records_per_stage_cost():
    cfg = _tuned(semantic=False)
    profiler = StageProfiler()
    run_cascade(_analyse("baseColour", "unknown_zz"), REG, cfg, None, None, profiler)
    costs = profiler.as_dict()
    assert "alias" in costs and costs["alias"]["calls"] == 2
    assert profiler.total_seconds() >= 0


def test_profiler_memory_tracing_is_opt_in():
    assert StageProfiler().trace_memory is False
    profiler = StageProfiler(trace_memory=True)
    with profiler.measure("x"):
        _ = [object() for _ in range(1000)]
    assert profiler.stages["x"].peak_kib > 0


# --- calibrator coverage ---------------------------------------------------

def _mapped(stage):
    return MappingRecord(
        source_position=0, raw_header="a", normalised_header="a",
        target_field="colour", deciding_stage=stage, raw_score=90.0,
    )


def test_strict_apply_raises_for_an_unfitted_stage():
    cal = Calibrator().fit([(Stage.ALIAS, 100.0, True)] * 10, "test")
    with pytest.raises(UnsetTunable, match="fuzzy"):
        cal.apply([_mapped(Stage.FUZZY)], strict=True)


def test_non_strict_apply_leaves_confidence_none_and_reports_the_gap():
    """An ablation condition may use a stage the calibrator never observed.

    Borrowing another stage's curve would be worse than reporting nothing.
    """
    cal = Calibrator().fit([(Stage.ALIAS, 100.0, True)] * 10, "test")
    record = _mapped(Stage.FUZZY)
    skipped = cal.apply([record], strict=False)
    assert skipped == {"fuzzy"}
    assert record.confidence is None


def test_covered_stages_reports_what_was_fitted():
    cal = Calibrator().fit(
        [(Stage.ALIAS, 100.0, True)] * 5 + [(Stage.FUZZY, 90.0, False)] * 5, "test")
    assert cal.covered_stages() == {"alias", "fuzzy"}


# --- runner ----------------------------------------------------------------

def test_discover_schemas_excludes_perturbation_logs(tmp_path):
    (tmp_path / "a.csv").write_text("h\n1\n")
    (tmp_path / "a.perturbation_log.json").write_text("{}")
    assert [p.name for p in discover_schemas(tmp_path)] == ["a.csv"]


def test_discover_schemas_fails_loudly_on_an_empty_directory(tmp_path):
    with pytest.raises(SystemExit, match="No schema files"):
        discover_schemas(tmp_path)


def test_gold_standard_requires_a_freeze_date(tmp_path):
    bad = tmp_path / "g.json"
    bad.write_text(json.dumps({"mappings": {"a": "colour"}}))
    with pytest.raises(ValueError, match="frozen_at"):
        load_gold_standard(bad)


def test_gold_standard_loads_with_a_date(tmp_path):
    good = tmp_path / "g.json"
    good.write_text(json.dumps({
        "schema": "s", "frozen_at": "2026-10-05", "rater": "xx",
        "mappings": {"a": "colour", "b": "NO_MAPPING"},
    }))
    gold = load_gold_standard(good)
    assert gold.frozen_at == "2026-10-05"
    assert gold.mappable_count() == 1


def test_ablation_overlay_toggles_stages():
    assert load_overlay(overlay_path="config/ablation/fuzzy_only.yaml").enabled_stages() == ["fuzzy"]
    assert load_overlay(
        overlay_path="config/ablation/full_cascade_value.yaml"
    ).enabled_stages() == ["alias", "fuzzy", "semantic", "value"]


def test_narrow_threshold_guard_ignores_disabled_stages():
    cfg = load_overlay(overlay_path="config/ablation/fuzzy_only.yaml",
                       fuzzy_threshold=85.0)
    assert cfg.unset_matching_thresholds() == []
    assert cfg.unset_tunables()  # bands still unset, and that is fine


# --- scripts refuse the dangerous things -----------------------------------

def _run(module, *args):
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True, text=True, cwd=".",
    )


def test_grid_search_refuses_the_sealed_directory():
    out = _run("eval.grid_search", "--schemas", "data/heldout")
    assert "REFUSED" in out.stdout + out.stderr


def test_grid_search_refuses_the_stub_embedder():
    out = _run("eval.grid_search", "--schemas", "data/dev")
    assert "stub embedder" in (out.stdout + out.stderr)


def test_fit_calibration_refuses_the_sealed_directory():
    out = _run("eval.fit_calibration", "--schemas", "data/heldout")
    assert "REFUSED" in out.stdout + out.stderr


def test_perturbation_is_reproducible_under_a_seed(tmp_path):
    source = tmp_path / "s.csv"
    source.write_text("Alpha_One,Beta_Two,Gamma_Three,Delta_Four\n1,2,3,4\n")
    for _ in range(2):
        _run("scripts.perturb_schema", str(source), "--level", "moderate",
             "--seed", "11", "--out", str(tmp_path / "out"))
    produced = (tmp_path / "out" / "s_moderate.csv").read_text()
    _run("scripts.perturb_schema", str(source), "--level", "moderate",
         "--seed", "11", "--out", str(tmp_path / "out2"))
    assert produced == (tmp_path / "out2" / "s_moderate.csv").read_text()


# --- Review threshold rule -------------------------------------------------

def test_review_threshold_is_lowest_confidence_reaching_target_accuracy():
    from src.matching.confidence import derive_review_threshold

    pairs = [(0.5, False), (0.6, True), (0.7, False), (0.8, True), (0.9, True), (0.95, True)]
    found = derive_review_threshold(pairs, 0.90)
    # >=0.7 -> 3/4 right (0.75); >=0.8 -> 3/3 right.
    assert found["threshold"] == 0.8
    assert found["accepted"] == 3 and found["total"] == 6
    assert found["accuracy"] == 1.0


def test_review_threshold_is_none_when_target_is_unreachable():
    from src.matching.confidence import derive_review_threshold

    assert derive_review_threshold([(0.9, False), (0.95, False)], 0.90) is None
    assert derive_review_threshold([], 0.90) is None


def test_grid_search_smoke_runs_three_thresholds_with_stub(tmp_path):
    out = tmp_path / "thresholds.yaml"
    result = _run("eval.grid_search", "--allow-stub", "--start", "80", "--stop", "90",
                  "--step", "10", "--out", str(out))
    assert result.returncode == 0, result.stderr
    import yaml
    stages = yaml.safe_load(out.read_text())["matching"]["stages"]
    assert set(stages) == {"fuzzy", "semantic", "value"}
