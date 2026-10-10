"""CDM coverage of the research-defined regulatory reference set (O2; D12 as refined by D59 and D66).

Scope (D66): the reference set is built from primary regulatory text only:
ESPR Annex III (a)-(l), Art 7(5) and Art 5(1), plus Reg. (EU) 1007/2011. This
narrows D12, which also named the Commission's preparatory study and CIRPASS
outputs; a set including those was never built or evaluated. The figure is
coverage of this research-defined set, NOT coverage of a legally mandatory
list of textile DPP attributes (none exists until the textiles delegated act
is adopted), and coverage of the 12 Annex III points is a different measure
from coverage of attributes.

    python -m scripts.coverage_report

Reads ``cdm/corrections/reference_attribute_set.csv`` and the frozen CDM
schema, checks every ``covered_by`` name really is a CDM field, and prints
three figures so no one of them can be quoted as if it were the others:

* **Annex III points** — lettered points (a)-(l) with at least one CDM field.
  The v1.0 extraction claimed 11/11; the corrected denominator is 12, because
  point (l) was missing from the transcription.
* **Core reference attributes** — Annex III attributes, expanded through
  Art 7(5) substance attributes, plus fibre composition (Reg. 1007/2011).
* **Core + parameter aspects** — adds the Art 5(1) aspects. These apply only
  where a delegated act selects them, and the textiles act is not adopted, so
  this is reported as a sensitivity figure, not the O2 headline.

Art 5(1)(g) (substances of concern) is not listed among the parameter aspects
because Art 7(5) already expands it into eight attributes in the core set.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REFERENCE = Path("cdm/corrections/reference_attribute_set.csv")
TRANSCRIPTION = Path("cdm/corrections/annex_iii_transcription_v1.1.csv")
SCHEMA = Path("cdm/cdm_v1.0.schema.json")


def compute() -> dict:
    """Return the three coverage figures and the uncovered attributes."""
    fields = set(json.loads(SCHEMA.read_text(encoding="utf-8"))["properties"])
    rows = list(csv.DictReader(REFERENCE.open(encoding="utf-8")))
    for row in rows:
        for name in filter(None, row["covered_by"].split(";")):
            if name not in fields:
                raise SystemExit(f"{row['ref_id']}: '{name}' is not a CDM v1.0 field.")

    points = list(csv.DictReader(TRANSCRIPTION.open(encoding="utf-8")))
    covered_points = [p["point"] for p in points if p["cdm_fields_v1.0"].strip()]
    for p in points:
        for name in filter(None, p["cdm_fields_v1.0"].split(";")):
            if name not in fields:
                raise SystemExit(f"Annex III ({p['point']}): '{name}' is not a CDM v1.0 field.")

    def share(subset: list[dict]) -> tuple[int, int]:
        return sum(1 for r in subset if r["covered_by"].strip()), len(subset)

    core = [r for r in rows if r["scope"] == "core"]
    return {
        "annex_iii_points": (len(covered_points), len(points)),
        "core": share(core),
        "core_plus_parameters": share(rows),
        "uncovered_core": [f"{r['ref_id']} {r['attribute']} ({r['clause']})" for r in core if not r["covered_by"].strip()],
        "uncovered_points": [p["point"] for p in points if p["point"] not in covered_points],
    }


def main() -> int:
    """Print the coverage report."""
    out = compute()
    def pct(pair: tuple[int, int]) -> str:
        return f"{pair[0]}/{pair[1]} = {100 * pair[0] / pair[1]:.1f}%"
    print("CDM v1.0 coverage of the research-defined regulatory reference set (D59, D66)\n")
    print(f"  Annex III lettered points (a)-(l)          {pct(out['annex_iii_points'])}")
    print(f"  Core reference attributes                  {pct(out['core'])}   <- O2 figure (target >= 80%; research-defined set)")
    print(f"  Core + Art 5(1) parameter aspects          {pct(out['core_plus_parameters'])}   (sensitivity only)")
    print("\n  Uncovered Annex III points: " + (", ".join(out["uncovered_points"]) or "none"))
    print("  Uncovered core attributes:")
    for line in out["uncovered_core"]:
        print(f"    - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
