"""Command-line entry point for the ADIF prototype.

Two commands, deliberately separated by what they require:

``inspect``
    Ingest and profile a manufacturer file. Needs no CDM and no thresholds, so
    it runs correctly today and its output is not provisional.

``map``
    Run the full matching cascade. Requires a CDM, an alias vocabulary, and
    thresholds. Because the thresholds have not been derived yet (D11), they
    must be passed explicitly on the command line, and any run that does so is
    stamped ``EXPLORATORY`` in its output and run record. That stamp exists so
    a demo run can never be mistaken for a result: the numbers it produces are
    not evaluation evidence, and Chapter 6 must not cite them.

Usage::

    python -m src.cli inspect data/dev/manufacturer_a.csv
    python -m src.cli map data/dev/manufacturer_a.csv \\
        --cdm tests/fixtures/cdm_test.schema.json \\
        --aliases tests/fixtures/aliases_test.yaml \\
        --fuzzy-threshold 85 --no-semantic
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.analyser.profile import analyse_frame
from src.cdm.registry import CdmRegistry, CdmVocabularyError
from src.config import DEFAULT_CONFIG_PATH, load_config
from src.ingestion.errors import IngestionError
from src.ingestion.loader import load_tabular
from src.matching.arbitration import run_cascade
from src.matching.stage3_semantic import MiniLMEmbedder, SemanticIndex, StubEmbedder
from src.provenance import capture

EXPLORATORY_BANNER = (
    "EXPLORATORY RUN — thresholds were supplied on the command line, not "
    "derived by grid search (decisions.md D11). These numbers are not "
    "evaluation evidence and must not be cited as results."
)


def _print_table(rows: list[tuple[str, ...]], headers: tuple[str, ...]) -> None:
    widths = [
        max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))


def cmd_inspect(args: argparse.Namespace) -> int:
    """Ingest and profile a file. No CDM or thresholds required."""
    cfg = load_config(args.config)
    load_result = load_tabular(args.file, cfg, sheet_name=args.sheet)
    analysis = analyse_frame(load_result.frame, cfg)

    delimiter = repr(load_result.delimiter) if load_result.delimiter else "-"
    print(
        f"\n{load_result.source_format.upper()}  "
        f"rows={analysis.row_count}  columns={analysis.column_count}  "
        f"encoding={load_result.encoding or '-'}  "
        f"delimiter={delimiter}\n"
    )
    if analysis.duplicate_headers_renamed:
        print(f"Duplicate headers renamed: {analysis.duplicate_headers_renamed}")
    if analysis.empty_headers_named:
        print(f"Empty headers named: {analysis.empty_headers_named}")
    if analysis.duplicate_headers_renamed or analysis.empty_headers_named:
        print()

    _print_table(
        [
            (
                c.raw_header,
                c.normalised_header,
                c.datatype,
                f"{c.null_rate:.0%}",
                str(c.distinct_count),
                (c.sample_values[0][:32] if c.sample_values else ""),
            )
            for c in analysis.columns
        ],
        ("SOURCE HEADER", "NORMALISED", "TYPE", "NULL", "DISTINCT", "SAMPLE"),
    )

    if args.json:
        Path(args.json).write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nWrote analysis to {args.json}")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    """Run the full cascade over a file."""
    cfg = load_config(args.config)

    # Thresholds are null in the shipped config by design (D11). Accepting them
    # here keeps the prototype usable without ever writing an underived number
    # into the frozen configuration file.
    if args.fuzzy_threshold is not None:
        cfg.matching.stages.fuzzy.threshold = args.fuzzy_threshold
    if args.semantic_threshold is not None:
        cfg.matching.stages.semantic.threshold = args.semantic_threshold
    if args.no_semantic:
        cfg.matching.stages.semantic.enabled = False
    if args.no_alias:
        cfg.matching.stages.alias.enabled = False
    if args.no_fuzzy:
        cfg.matching.stages.fuzzy.enabled = False

    print(f"\n*** {EXPLORATORY_BANNER} ***\n")

    registry = CdmRegistry.load(args.cdm, args.aliases, cfg.normalisation)
    if "fixtures" in str(args.cdm):
        print(
            "NOTE: running against the TEST FIXTURE CDM. This is six invented "
            "fields for exercising the pipeline, not the canonical data model.\n"
        )

    index = None
    if cfg.matching.stages.semantic.enabled:
        if args.embedder == "minilm":
            embedder = MiniLMEmbedder(
                cfg.matching.stages.semantic.model,
                str(cfg.paths.embedding_cache),
                cfg.matching.stages.semantic.model_revision,
            )
        else:
            embedder = StubEmbedder()
            print(
                "NOTE: using the STUB embedder. Its similarities are "
                "hash-derived and semantically meaningless — it exercises the "
                "plumbing only. Pass --embedder minilm for real matching.\n"
            )
        index = SemanticIndex(registry, embedder)

    analysis = analyse_frame(load_tabular(args.file, cfg, args.sheet).frame, cfg)
    result = run_cascade(analysis, registry, cfg, index)

    _print_table(
        [
            (
                r.raw_header,
                r.target_field,
                r.deciding_stage.value,
                f"{r.raw_score:.1f}",
                "CONFLICT" if r.conflict_flagged else ("review" if r.review_required else ""),
            )
            for r in result.records
        ],
        ("SOURCE COLUMN", "CDM FIELD", "STAGE", "SCORE", "FLAG"),
    )

    print(f"\nStage hits        : {result.stage_hits}")
    print(f"Fall-throughs     : {result.stage_fallthroughs}")
    print(f"Unmapped columns  : {result.unmapped_columns() or 'none'}")
    print(f"Mandatory missing : {result.unpopulated_mandatory(registry) or 'none'}")
    print(f"Enabled stages    : {cfg.enabled_stages()}")

    record_dir = Path(cfg.paths.run_records)
    record_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record_path = record_dir / f"run_{stamp}.json"
    record_path.write_text(
        json.dumps(
            {
                "status": "EXPLORATORY",
                "warning": EXPLORATORY_BANNER,
                "input_file": str(args.file),
                "cdm_schema_sha256": registry.schema_sha256,
                "alias_vocabulary_sha256": registry.alias_sha256,
                "embedder": result.embedder_name,
                "thresholds_supplied_on_cli": {
                    "fuzzy": args.fuzzy_threshold,
                    "semantic": args.semantic_threshold,
                },
                "stage_hits": result.stage_hits,
                "stage_fallthroughs": result.stage_fallthroughs,
                "provenance": capture(cfg).model_dump(),
                "records": [r.model_dump(mode="json") for r in result.records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nRun record        : {record_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``inspect`` and ``map`` commands."""
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="ADIF — Apparel DPP Interoperability Framework prototype.",
    )
    parser.add_argument(
        "--config", default=str(DEFAULT_CONFIG_PATH), help="Path to the config YAML."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="Ingest and profile a file (no CDM needed).")
    inspect.add_argument("file", help="CSV, XLSX or flat JSON.")
    inspect.add_argument("--sheet", default=None, help="Excel sheet name.")
    inspect.add_argument("--json", default=None, help="Write the analysis to this path.")
    inspect.set_defaults(func=cmd_inspect)

    mapper = sub.add_parser("map", help="Run the full matching cascade.")
    mapper.add_argument("file", help="CSV, XLSX or flat JSON.")
    mapper.add_argument("--sheet", default=None)
    mapper.add_argument("--cdm", required=True, help="Path to the CDM JSON Schema.")
    mapper.add_argument("--aliases", required=True, help="Path to the alias vocabulary.")
    mapper.add_argument("--fuzzy-threshold", type=float, default=None)
    mapper.add_argument("--semantic-threshold", type=float, default=None)
    mapper.add_argument("--embedder", choices=["stub", "minilm"], default="stub")
    mapper.add_argument("--no-alias", action="store_true", help="Ablation: disable Stage 1.")
    mapper.add_argument("--no-fuzzy", action="store_true", help="Ablation: disable Stage 2.")
    mapper.add_argument("--no-semantic", action="store_true", help="Ablation: disable Stage 3.")
    mapper.set_defaults(func=cmd_map)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the selected subcommand.

    Ingestion and vocabulary errors are caught and reported as messages rather
    than tracebacks: they describe a problem with the *input file* or the
    *vocabulary*, which the operator can fix, and a stack trace buries that.
    """
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (IngestionError, CdmVocabularyError) as exc:
        print(f"\nError: {exc}\n", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"\nFile not found: {exc}\n", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
