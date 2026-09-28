"""Metric 4 — template reuse on a drifted second upload (D8, FR-9.1 to FR-9.5).

    python -m eval.run_template_reuse --schemas <held-out directory> --real-model --status EVALUATION

For every ``<schema>`` / ``<schema>_drift`` pair in the directory, under every
ablation condition, this simulates a manufacturer's second season:

1. A template is stored for the original upload.
2. The drifted file is uploaded: the cascade runs on it, then the template is
   reapplied on top, exactly as the API does.
3. Two numbers are scored against the drifted file's own gold standard.

**Template reuse rate (Metric 4a).** Of the columns whose header is *unchanged*
between the two seasons and which have a real CDM target, the share that came
back correctly *and automatically* — decided by the template, so never routed
to review. methodology.md target: >= 95%.

**Delta-field F1 (Metric 4b).** F1 over the columns whose header is *new* in the
drifted file — renamed, split or added. The template cannot help with these;
the cascade has to re-match them. Target: >= 0.80.

Reporting decisions this script makes, which Chapter 3 must state
---------------------------------------------------------------------
**Where the template comes from.** By default it is built from the original
schema's gold standard: the template a reviewer would have saved after
correcting every mistake. That isolates Metric 4 from Metric 1 — a template
built from raw cascade output would carry every original mapping error into the
reuse score, and the two metrics would stop measuring different things. Pass
``--template-from cascade`` to store the uncorrected cascade output instead; it
is the pessimistic case (no reviewer corrections) and is worth reporting
alongside, labelled as such.

**The 4a denominator excludes unchanged columns whose gold target is
NO_MAPPING.** A template stores only mapped columns, so it never claims those;
they are not reuse successes or failures, they are not the template's business.
Their count is still printed so nothing disappears silently.

**With the default gold template, 4a is close to 100% by construction — say so.**
An unchanged header meets a template entry a reviewer already corrected, and
lookup is deterministic, so 4a measures that the mechanism works, not how well
the system copes with drift. That is exactly D8's warning about identical
re-uploads, surviving at column level. The informative Metric 4 numbers are
therefore **4b** (can the cascade re-match what the template cannot cover?) and
**4a under** ``--template-from cascade`` (how much a stored template helps when
nobody corrected it). Report all three, and do not present a ~100% gold-template
4a as evidence of robustness. It is evidence that the template store works.

**Metric 4 is not computed by** ``eval/run_ablation.py`` **, which leaves the
field empty.** Cite this script's run record for Metric 4.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from eval.metrics import mapping_f1
from eval.run_ablation import LADDER
from eval.runner import (
    build_context,
    discover_schemas,
    load_gold_standard,
    load_overlay,
    run_schema,
)
from src.config import load_config
from src.matching.arbitration import MappingResult
from src.matching.models import NO_MAPPING, MappingRecord, Stage
from src.provenance import capture
from src.templates.store import Template, TemplateStore

DRIFT_SUFFIX = "_drift"


@dataclass
class ReuseScore:
    """Metric 4 for one schema pair under one condition."""

    schema: str
    condition: str
    template_from: str
    unchanged_mappable: int
    unchanged_unmappable: int
    reused_correct: int
    reuse_rate: float | None
    delta_columns: int
    delta_mappable: int
    delta_precision: float | None
    delta_recall: float | None
    delta_f1: float | None
    template_entries_missing_from_drift: int


def score_reuse(
    original_headers: set[str],
    drift_records: list[MappingRecord],
    drift_gold: dict[str, str],
    *,
    schema: str = "",
    condition: str = "",
    template_from: str = "gold",
    template_missing: int = 0,
    stage_hits: dict[str, int] | None = None,
) -> ReuseScore:
    """Score Metric 4a and 4b from records the template has already been applied to.

    Kept free of I/O so the definition can be unit-tested directly — this is
    the function whose behaviour Chapter 3 describes.
    """
    drift_headers = {r.raw_header for r in drift_records}
    by_header = {r.raw_header: r for r in drift_records}

    unchanged = drift_headers & original_headers
    unchanged_mappable = [h for h in unchanged if drift_gold.get(h, NO_MAPPING) != NO_MAPPING]
    unchanged_unmappable = len(unchanged) - len(unchanged_mappable)

    reused_correct = sum(
        1
        for h in unchanged_mappable
        if by_header[h].deciding_stage == Stage.TEMPLATE
        and by_header[h].target_field == drift_gold[h]
    )
    reuse_rate = (
        round(reused_correct / len(unchanged_mappable), 6) if unchanged_mappable else None
    )

    delta = sorted(drift_headers - original_headers)
    delta_gold = {h: drift_gold[h] for h in delta if h in drift_gold}
    delta_mappable = sum(1 for v in delta_gold.values() if v != NO_MAPPING)
    if delta_mappable:
        subset = MappingResult(
            records=[by_header[h] for h in delta],
            stage_hits=stage_hits or {},
            stage_fallthroughs={},
            embedder_name=None,
        )
        p, r, f = mapping_f1(subset, delta_gold)
    else:
        p = r = f = None

    return ReuseScore(
        schema=schema,
        condition=condition,
        template_from=template_from,
        unchanged_mappable=len(unchanged_mappable),
        unchanged_unmappable=unchanged_unmappable,
        reused_correct=reused_correct,
        reuse_rate=reuse_rate,
        delta_columns=len(delta),
        delta_mappable=delta_mappable,
        delta_precision=p,
        delta_recall=r,
        delta_f1=f,
        template_entries_missing_from_drift=template_missing,
    )


def find_pairs(directory: Path) -> list[tuple[Path, Path]]:
    """Match each ``*_drift`` schema with its original in the same directory."""
    schemas = {s.stem: s for s in discover_schemas(directory)}
    pairs = []
    for stem, drift in sorted(schemas.items()):
        if not stem.endswith(DRIFT_SUFFIX):
            continue
        base = stem[: -len(DRIFT_SUFFIX)]
        if base not in schemas:
            raise SystemExit(
                f"'{drift.name}' has no original '{base}.*' beside it. A drifted "
                f"upload is only meaningful against the season it drifted from."
            )
        pairs.append((schemas[base], drift))
    if not pairs:
        raise SystemExit(
            f"No '<schema>{DRIFT_SUFFIX}' files in '{directory}'. Metric 4 needs a "
            f"drifted second upload (D8); an identical re-upload proves nothing."
        )
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description="Metric 4 — template reuse on drift (D8)")
    parser.add_argument("--schemas", type=Path, default=Path("data/dev"))
    parser.add_argument("--gold", type=Path, default=Path("goldstandard"))
    parser.add_argument("--out", type=Path, default=Path("runs"))
    parser.add_argument("--status", choices=["EXPLORATORY", "EVALUATION"],
                        default="EXPLORATORY")
    parser.add_argument("--template-from", choices=["gold", "cascade"], default="gold",
                        help="gold = reviewer-corrected template (default); "
                             "cascade = uncorrected cascade output (pessimistic case)")
    parser.add_argument("--conditions", nargs="*",
                        help="Subset of ladder conditions; default is the full ladder")
    parser.add_argument("--real-model", action="store_true")
    args = parser.parse_args()

    base = load_config("config/default.yaml")
    if args.status == "EVALUATION":
        blockers = []
        if not Path(base.paths.cdm_schema).is_file():
            blockers.append("the frozen CDM schema does not exist")
        if base.unset_matching_thresholds():
            blockers.append(f"thresholds unset: {base.unset_matching_thresholds()}")
        if not args.real_model:
            blockers.append("--real-model not given; a stub-embedder run is not citable")
        if blockers:
            raise SystemExit("REFUSED: cannot label this run EVALUATION.\n  - "
                             + "\n  - ".join(blockers))

    conditions = [c for c in LADDER if not args.conditions or c[0] in args.conditions]
    pairs = find_pairs(args.schemas)
    scores: list[ReuseScore] = []

    for name, overlay in conditions:
        cfg = load_overlay(overlay_path=overlay)
        if cfg.unset_matching_thresholds():
            raise SystemExit(
                f"Condition '{name}': {cfg.unset_matching_thresholds()} unset. "
                f"Run eval/grid_search.py and set them in config/default.yaml (D11)."
            )
        context = build_context(cfg, real_model=args.real_model)
        cdm_sha = context.registry.schema_sha256

        for original, drift in pairs:
            original_gold = load_gold_standard(args.gold / f"{original.stem}.json")
            drift_gold = load_gold_standard(args.gold / f"{drift.stem}.json")

            if args.template_from == "gold":
                template = Template(
                    manufacturer_id=original.stem,
                    version=1,
                    created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    cdm_sha256=cdm_sha,
                    mappings={h: t for h, t in original_gold.mappings.items()
                              if t != NO_MAPPING},
                )
                original_headers = set(original_gold.mappings)
            else:
                original_result, _ = run_schema(original, context)
                # var/ is gitignored runtime state; a scratch store here can
                # never end up in a commit alongside the run record.
                store = TemplateStore(Path("var") / "reuse_scratch.sqlite")
                template = store.save(original.stem, original_result.records, cdm_sha)
                original_headers = {r.raw_header for r in original_result.records}

            drift_result, _ = run_schema(drift, context)
            outcome = TemplateStore.apply(template, drift_result.records)

            score = score_reuse(
                original_headers,
                drift_result.records,
                drift_gold.mappings,
                schema=original.stem,
                condition=name,
                template_from=args.template_from,
                template_missing=len(outcome.drifted_missing),
                stage_hits=drift_result.stage_hits,
            )
            scores.append(score)
            rate = "n/a" if score.reuse_rate is None else f"{score.reuse_rate:.4f}"
            df1 = "n/a" if score.delta_f1 is None else f"{score.delta_f1:.4f}"
            print(f"  {name:<20} {original.stem:<24} reuse={rate} "
                  f"({score.reused_correct}/{score.unchanged_mappable})  "
                  f"deltaF1={df1} over {score.delta_mappable} mappable new column(s)")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = args.out / f"template_reuse_{stamp}.json"
    provenance = capture(base).model_dump()
    path.write_text(json.dumps({
        "status": args.status,
        "metric": "Metric 4 — template reuse on drifted upload (D8)",
        "template_from": args.template_from,
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scores": [asdict(s) for s in scores],
        "provenance": provenance,
    }, indent=2), encoding="utf-8")

    if args.template_from == "gold":
        print("\nNOTE: with --template-from gold, reuse on unchanged columns is ~100% by "
              "construction\n(deterministic lookup of reviewer-corrected entries). The "
              "informative numbers\nare deltaF1, and reuse under --template-from cascade. "
              "Report all three.")
    print(f"\nRun record: {path}  [{args.status}]")
    if args.status == "EXPLORATORY":
        print("This run is EXPLORATORY. Do not cite these numbers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
