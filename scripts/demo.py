"""End-to-end demonstration of the ADIF pipeline as built so far.

Run from the repository root::

    python -m scripts.demo                      # built-in sample file
    python -m scripts.demo --file my_export.csv # your own manufacturer export

Pipeline exercised: ingestion (M1) → schema analysis (M2) → alias lookup (M3)
→ fuzzy matching (M4) → semantic matching (M5) → cascade arbitration (M7).

**This is a demonstration, not an evaluation.** Two things make it so, and both
are printed in the banner rather than buried here:

*The CDM is a test fixture.* Six invented fields, not the canonical model. The
real CDM is derived from ESPR Annex III, EPCIS 2.0 and UNTP through the
procedure in ``cdm/EXTRACTION.md``, which is not finished.

*The thresholds are invented.* Config ships them as ``null`` on purpose
(decisions.md D11); this script supplies values so the cascade will run at all.
They are not derived from a grid search and no number produced here is a
result.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from src.analyser.profile import analyse_frame
from src.cdm.registry import CdmRegistry
from src.config import AdifConfig, load_config
from src.ingestion.errors import IngestionError
from src.ingestion.loader import load_tabular
from eval.runner import build_context, load_overlay
from src.matching.arbitration import run_cascade
from src.matching.confidence import Calibrator

#: The complete gateway, value stage included, as the final system runs.
DEMO_OVERLAY = "config/ablation/full_cascade_value.yaml"
CALIBRATOR_PATH = Path("config/calibrator.json")

# FALLBACK VALUES ONLY, used when config/default.yaml still holds null
# thresholds. Never copy these into config/default.yaml.
DEMO_FUZZY_THRESHOLD = 85.0
DEMO_SEMANTIC_THRESHOLD = 99.0
DEMO_VALUE_THRESHOLD = 80.0

SAMPLE = pd.DataFrame(
    {
        "Design_Code": ["TOP-A", "TOP-A"],
        "Style_No": ["0012345678905", "0012345678912"],
        "baseColour": ["Navy", "Red"],
        "SIZE": ["M", "L"],
        "Fabric_Compostion": ["80% Cotton 20% Polyester", "100% Cotton"],
        "origin": ["LK", "LK"],
        "made in": ["Sri Lanka", "Sri Lanka"],
        "internal_ref_zz": ["A1", "A2"],
    }
)


def reject_if_sealed(path: Path, cfg: AdifConfig) -> None:
    """Refuse to read anything inside the sealed evaluation directory.

    The freeze discipline (project.md §11) is only credible if held-out data is
    genuinely untouched during development. A convenience script pointed at it
    by accident is exactly how that gets broken, so the refusal is enforced
    here rather than left to the operator's memory.
    """
    sealed = Path(cfg.paths.heldout_dir).resolve()
    if sealed in path.resolve().parents:
        sys.exit(
            f"REFUSED: '{path}' is inside the sealed evaluation directory "
            f"({sealed}).\nHeld-out schemas are opened by the evaluation "
            f"harness after the freeze commit, never by a demo script."
        )


def build_config() -> tuple[AdifConfig, bool]:
    """Load the config with the value stage on; fall back only if thresholds are null.

    Returns:
        The config, and whether any threshold had to be invented to run at all.
    """
    cfg = load_overlay(overlay_path=DEMO_OVERLAY)
    invented = bool(cfg.unset_matching_thresholds())
    stages = cfg.matching.stages
    if stages.fuzzy.threshold is None:
        stages.fuzzy.threshold = DEMO_FUZZY_THRESHOLD
    if stages.semantic.threshold is None:
        stages.semantic.threshold = DEMO_SEMANTIC_THRESHOLD
    if stages.value.threshold is None:
        stages.value.threshold = DEMO_VALUE_THRESHOLD
    return cfg, invented


def main() -> int:
    parser = argparse.ArgumentParser(description="ADIF pipeline demonstration")
    parser.add_argument("--file", type=Path, help="A .csv, .xlsx or flat .json export")
    parser.add_argument(
        "--real-model",
        action="store_true",
        help="Use all-MiniLM-L6-v2 from the local cache instead of the stub embedder",
    )
    args = parser.parse_args()

    cfg, invented = build_config()

    if args.file:
        reject_if_sealed(args.file, cfg)
        try:
            loaded = load_tabular(args.file, cfg)
        except IngestionError as exc:
            print(f"Could not read that file:\n  {exc}")
            return 1
        frame, origin = loaded.frame, str(args.file)
        detail = f"{loaded.source_format}, encoding={loaded.encoding}, delimiter={loaded.delimiter!r}"
    else:
        frame, origin = SAMPLE, "built-in sample"
        detail = "in-memory DataFrame"

    context = build_context(cfg, real_model=args.real_model)
    registry = context.registry
    analysis = analyse_frame(frame, cfg)
    result = run_cascade(
        analysis, registry, cfg, context.semantic_index, context.signature_library
    )

    calibrated = CALIBRATOR_PATH.is_file()
    if calibrated:
        Calibrator.load(CALIBRATOR_PATH).apply(result.records, strict=False)
        review_below = cfg.confidence.bands.review
        if review_below is not None:
            for record in result.records:
                if record.confidence is not None and record.confidence < review_below:
                    record.review_required = True

    stages = cfg.matching.stages
    cdm_label = (
        f"{len(registry.fields)} invented fields, TEST FIXTURE"
        if context.using_fixture_cdm else f"{len(registry.fields)} fields"
    )
    print("=" * 86)
    print("ADIF pipeline demonstration — NOT AN EVALUATION")
    print(f"  CDM        : {'tests/fixtures/cdm_test.schema.json' if context.using_fixture_cdm else cfg.paths.cdm_schema}  ({cdm_label})")
    print(f"  Thresholds : fuzzy={stages.fuzzy.threshold} semantic={stages.semantic.threshold} "
          f"value={stages.value.threshold}  "
          f"({'INVENTED fallback, not grid-searched' if invented else 'from config/default.yaml'})")
    print(f"  Confidence : {'calibrated (config/calibrator.json)' if calibrated else 'none - no calibrator fitted'}"
          f"; review below {cfg.confidence.bands.review}")
    print(f"  Embedder   : {context.embedder_name}")
    print(f"  Input      : {origin}  ({detail})")
    print(f"  Rows/cols  : {analysis.row_count} x {analysis.column_count}")
    print("=" * 86)

    print(f"\n{'source column':<24}{'CDM field':<26}{'stage':<10}{'score':>8}{'conf':>8}  note")
    print("-" * 90)
    for record in result.records:
        note = (
            "CONFLICT — demoted"
            if record.conflict_flagged
            else ("needs review" if record.review_required else "")
        )
        conf = f"{record.confidence:.3f}" if record.confidence is not None else "-"
        print(
            f"{record.raw_header[:23]:<24}{record.target_field:<26}"
            f"{record.deciding_stage.value:<10}{record.raw_score:>8.1f}{conf:>8}  {note}"
        )

    print(f"\nstage hits          : {result.stage_hits}")
    print(f"stage fall-throughs : {result.stage_fallthroughs}")
    print(f"unmapped columns    : {result.unmapped_columns() or 'none'}")
    print(f"mandatory not filled: {result.unpopulated_mandatory(registry) or 'none'}")

    for record in result.records:
        if record.conflict_flagged and record.notes:
            print(f"\nconflict detail     : {record.raw_header} — {record.notes}")

    provisional = []
    if context.using_fixture_cdm:
        provisional.append("the CDM is a test fixture, not the canonical model")
    if invented:
        provisional.append("thresholds are invented, not grid-searched")
    if not args.real_model:
        provisional.append("the embedder is a stub - pass --real-model")
    if not calibrated:
        provisional.append("no confidence is reported until a calibrator is fitted")
    if provisional:
        print("\nStill provisional:\n  - " + "\n  - ".join(provisional))
    print(
        "\nFor validation, ADID identifiers, JSON-LD output and the review UI, "
        "run the API:\n  uvicorn src.api.main:app --reload   "
        "then open http://127.0.0.1:8000/review"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
