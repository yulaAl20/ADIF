"""Generate a blank ground-truth worksheet for one schema.

    python -m scripts.make_gold_worksheet data/dev/manufacturer_b_erpnext.csv

Writes ``goldstandard/<schema>.worksheet.csv`` with one row per source column,
carrying the header and its sample values so the decision can be made from the
data itself.

**It deliberately does not run the matcher.** The worksheet shows you what the
column contains, never what the system thinks it is. Ground truth written from
a matcher's proposals measures nothing: it records the system's own answer and
relabels it truth. See goldstandard/RULEBOOK.md.

The valid CDM field names are printed alongside, so the decision is a choice
from a closed list rather than free text.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from src.analyser.profile import analyse_frame
from src.cdm.registry import CdmRegistry
from src.config import load_config
from src.ingestion.loader import load_tabular


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a ground-truth worksheet")
    parser.add_argument("schema", type=Path)
    parser.add_argument("--out", type=Path, default=Path("goldstandard"))
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()

    cfg = load_config("config/default.yaml")
    registry = CdmRegistry.load(
        cfg.paths.cdm_schema, cfg.paths.alias_vocabulary, cfg.normalisation
    )
    analysis = analyse_frame(load_tabular(args.schema, cfg).frame, cfg)

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{args.schema.stem}.worksheet.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["raw_header", "datatype", "sample_values", "cdm_field", "rationale"])
        for column in analysis.columns:
            writer.writerow([
                column.raw_header,
                column.datatype,
                " | ".join(column.sample_values[: args.samples]),
                "",   # <- you fill this
                "",   # <- and this
            ])

    reference = args.out / "CDM_FIELDS.txt"
    reference.write_text(
        "Valid values for the cdm_field column.\n"
        "Anything not in this list, plus NO_MAPPING, is rejected on conversion.\n"
        "Field descriptions and source clauses: cdm/cdm_v1.0.schema.json\n\n"
        "NO_MAPPING\n" + "\n".join(registry.names()) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {path} - {len(analysis.columns)} rows to decide.")
    print(f"Valid field names: {reference}")
    print("\nFill cdm_field and rationale for EVERY row, then run:")
    print(f"    python -m scripts.build_gold_standard {path}")
    print("\nRead goldstandard/RULEBOOK.md first. Do not run the matcher beforehand.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
