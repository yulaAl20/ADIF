"""Schema perturbation tool — generates drifted variants (D8, D2).

    python -m scripts.perturb_schema input.csv --level moderate --out data/dev/
    python -m scripts.perturb_schema input.csv --level drift --seed 7 --out data/dev/

Applies a documented, seeded, reproducible set of header perturbations and
writes a **perturbation log** alongside the output.

Two distinct uses, and the difference matters:

``--level moderate`` / ``--level heavy``
    Build Schemas B and C (~40-50% and ~70%+ of fields perturbed). **The
    perturbed headers must still come from manufacturer-side source material**
    (ERP field lists, buyer tech packs, certification forms) — never from
    ESPR/GS1/UNTP documents, which are what the CDM itself is derived from
    (circularity guard, D3). This tool perturbs *what you give it*; it cannot
    enforce where you got it.

``--level drift``
    Build the "season two" variant for the template-reuse test. A few renames,
    an addition, a drop — not a wholesale rewrite. D8 requires reuse to be
    measured on a drifted upload rather than an identical one, because
    deterministic lookup cannot fail on an identical file and a 100% score
    there would prove nothing.

The perturbation log is written for the researcher's records. It must **not**
be given to the second rater checking ground truth: a rater who can see which
columns were renamed is not independently verifying the mapping, they are
reading the answer key (methodology.md, Ground truth).
"""

from __future__ import annotations

import argparse
import json
import random
import re
from datetime import date
from pathlib import Path

import pandas as pd

ABBREVIATIONS = {
    "number": "no", "quantity": "qty", "description": "desc", "product": "prod",
    "material": "mat", "composition": "comp", "reference": "ref", "code": "cd",
    "country": "ctry", "manufacture": "mfg", "identifier": "id", "percentage": "pct",
}
DISTRACTORS = [
    "internal_batch_ref", "legacy_sys_key", "wh_bin_location", "qc_pass_flag",
    "last_edited_by", "row_checksum", "export_lot_no", "print_queue_id",
]


def _snake(h: str) -> str:
    return re.sub(r"[\s-]+", "_", h.strip()).lower()


def _camel(h: str) -> str:
    parts = re.split(r"[\s_-]+", h.strip().lower())
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _abbreviate(h: str) -> str:
    out = h
    for long, short in ABBREVIATIONS.items():
        out = re.sub(long, short, out, flags=re.IGNORECASE)
    return out


def _spaced_caps(h: str) -> str:
    return re.sub(r"[_-]+", " ", h).upper()


def _truncate(h: str) -> str:
    return h[: max(4, len(h) // 2)]


TRANSFORMS = {
    "snake_case": _snake,
    "camelCase": _camel,
    "abbreviated": _abbreviate,
    "SPACED CAPS": _spaced_caps,
    "truncated": _truncate,
}

LEVELS = {"drift": 0.20, "moderate": 0.45, "heavy": 0.75}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a perturbed schema variant")
    parser.add_argument("source", type=Path)
    parser.add_argument("--level", choices=sorted(LEVELS), default="moderate")
    parser.add_argument("--seed", type=int, default=42,
                        help="Seeded so the perturbation is reproducible (NFR-5)")
    parser.add_argument("--out", type=Path, default=Path("data/dev"))
    parser.add_argument("--distractors", type=int, default=None,
                        help="Extra junk columns; default 0 for drift, 2 moderate, 5 heavy")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    frame = pd.read_csv(args.source, dtype=str, keep_default_na=False)
    originals = list(frame.columns)
    rate = LEVELS[args.level]
    n_distractors = args.distractors if args.distractors is not None else {
        "drift": 0, "moderate": 2, "heavy": 5}[args.level]

    # Select an EXACT count, not a per-column coin flip. methodology.md states
    # perturbation levels as rates ("~40-50% of fields perturbed"), and on a
    # schema of seven columns independent coin flips routinely deliver 15% or
    # 45% from a 20% setting. A stated rate the generator does not actually hit
    # is a methodology claim that does not survive inspection.
    target_count = round(rate * len(originals))
    chosen = set(rng.sample(range(len(originals)), min(target_count, len(originals))))

    log: list[dict[str, str]] = []
    renamed: list[str] = []
    for index, header in enumerate(originals):
        if index in chosen:
            for name in rng.sample(sorted(TRANSFORMS), len(TRANSFORMS)):
                new = TRANSFORMS[name](header)
                if new != header:
                    log.append({"original": header, "new": new, "transform": name})
                    renamed.append(new)
                    break
            else:
                renamed.append(header)
        else:
            renamed.append(header)
    frame.columns = renamed

    dropped: list[str] = []
    if args.level == "drift" and len(originals) > 3:
        victim = rng.choice(renamed)
        dropped.append(victim)
        frame = frame.drop(columns=[victim])

    added: list[str] = []
    for name in rng.sample(DISTRACTORS, min(n_distractors, len(DISTRACTORS))):
        frame[name] = [f"x{i}" for i in range(len(frame))]
        added.append(name)

    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.source.stem}_{args.level}"
    out_csv = args.out / f"{stem}.csv"
    frame.to_csv(out_csv, index=False)

    log_path = args.out / f"{stem}.perturbation_log.json"
    log_path.write_text(json.dumps({
        "source": str(args.source),
        "level": args.level,
        "seed": args.seed,
        "generated_on": date.today().isoformat(),
        "perturbation_rate_target": rate,
        "headers_renamed": log,
        "headers_dropped": dropped,
        "distractors_added": added,
        "_warning": (
            "Do NOT give this log to the second rater checking ground truth. "
            "A rater who can see which columns were renamed is reading the "
            "answer key, not independently verifying the mapping."
        ),
    }, indent=2), encoding="utf-8")

    actual = len(log) / len(originals) if originals else 0
    print(f"Wrote {out_csv}")
    print(f"  renamed {len(log)}/{len(originals)} headers ({actual:.0%}, target {rate:.0%})")
    print(f"  dropped {len(dropped)}, added {len(added)} distractor(s)")
    print(f"  log: {log_path}")
    print("\nNext: write the gold standard for this schema by hand, from the "
          "rulebook and CDM spec — not from the log above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
