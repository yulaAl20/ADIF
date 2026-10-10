"""Repair the Kaggle styles.csv so a strict CSV reader can open it.

    python -m scripts.repair_kaggle_styles <folder>/styles.csv <folder>/kaggle_styles.csv
    
The public file has a few rows with an unquoted comma inside the LAST column
(``productDisplayName``), giving 11 fields where the header declares 10. A strict
reader refuses the file. This is a data-preparation step that sits OUTSIDE the
frozen system: it changes no matcher, config or CDM, and it never touches the
original.

The repair is deterministic and minimal. For any row with too many fields, the
surplus fields are re-joined, with their commas, into the last column. Rows with
too FEW fields are not guessed at: the script stops and lists them.

It prints SHA-256 of the input and the output and every repaired line number, so
the step can be written into decisions.md and re-run by an examiner.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair Kaggle styles.csv (extra commas in last column)")
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    if args.out.resolve() == args.source.resolve():
        raise SystemExit("Refusing to overwrite the original. Choose a different output path.")

    repaired: list[int] = []
    too_short: list[int] = []
    rows: list[list[str]] = []
    with args.source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        width = len(header)
        rows.append(header)
        for row in reader:
            if len(row) > width:
                row = row[: width - 1] + [",".join(row[width - 1:])]
                repaired.append(reader.line_num)
            elif len(row) < width:
                too_short.append(reader.line_num)
                continue
            rows.append(row)

    if too_short:
        raise SystemExit(
            f"{len(too_short)} row(s) have FEWER than {width} fields (first lines: "
            f"{too_short[:10]}). Not guessed at - decide how to handle them first."
        )

    with args.out.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)

    print(f"Columns          : {width} ({', '.join(header)})")
    print(f"Data rows written: {len(rows) - 1}")
    print(f"Rows repaired    : {len(repaired)} (source lines {repaired[:20]}{' ...' if len(repaired) > 20 else ''})")
    print(f"SHA-256 input    : {sha256(args.source)}")
    print(f"SHA-256 output   : {sha256(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
