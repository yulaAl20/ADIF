"""Perform the artefact freeze, with the §11 preconditions enforced.

    python -m scripts.freeze --check          # report readiness, change nothing
    python -m scripts.freeze --tag freeze-v1.0

The freeze is the single most important process step in this project
(project.md §11): the alias vocabulary, CDM, grammar and threshold configs are
fixed *before* the held-out evaluation schemas exist, and the commit history is
what proves the ordering to an examiner.

That makes it very easy to get wrong in a way nothing detects until viva. So the
preconditions are checked mechanically rather than trusted to a checklist:

- every frozen artefact exists
- every matching threshold has been derived
- a fitted calibrator exists
- gold standards exist for the development schemas
- the sealed evaluation directory (resolved from config) is still EMPTY — if
  held-out schemas already exist, the ordering has been lost and tagging now
  would misrepresent it
- the working tree is clean, so the tag means something specific

It records every artefact hash, so `decisions.md` can carry the exact state.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

from src.config import load_config
from src.provenance import file_sha256


def _git(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=15)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Artefact freeze (project.md §11)")
    parser.add_argument("--tag", help="Tag name, e.g. freeze-v1.0")
    parser.add_argument("--check", action="store_true", help="Report readiness only")
    args = parser.parse_args()

    cfg = load_config("config/default.yaml")
    blockers: list[str] = []
    artefacts: dict[str, str | None] = {}

    print("\nFreeze readiness (project.md §11)")
    print("=" * 66)

    print("\nFrozen artefacts")
    for label, path in [
        ("CDM schema", cfg.paths.cdm_schema),
        ("JSON-LD context", cfg.paths.cdm_context),
        ("Alias vocabulary", cfg.paths.alias_vocabulary),
        ("ADID grammar", cfg.paths.adid_grammar),
        ("Config", Path("config/default.yaml")),
        ("Value signatures", cfg.matching.stages.value.signatures),
    ]:
        digest = file_sha256(path)
        artefacts[str(path)] = digest
        print(f"  {'OK   ' if digest else 'MISS '} {label:<20}{path}")
        if digest is None:
            blockers.append(f"{label} is missing ({path})")

    print("\nDerived tunables")
    pending = cfg.unset_matching_thresholds()
    if pending:
        print(f"  MISS  thresholds still unset: {pending}")
        blockers.append(
            "matching thresholds not derived — run eval/grid_search.py on dev data "
            "and write the values into config/default.yaml"
        )
    else:
        print("  OK    all enabled stages have derived thresholds")

    calibrator = Path("config/calibrator.json")
    if calibrator.is_file():
        fitted = json.loads(calibrator.read_text(encoding="utf-8")).get("fitted_on")
        print(f"  OK    calibrator fitted on: {fitted}")
        artefacts[str(calibrator)] = file_sha256(calibrator)
    else:
        print("  MISS  no fitted calibrator")
        blockers.append("no calibrator — run eval/fit_calibration.py on dev data")

    print("\nGround truth")
    gold = sorted(Path("goldstandard").glob("*.json"))
    gold = [g for g in gold if not g.name.endswith(".agreement.json")]
    dev = sorted(Path("data/dev").glob("*.csv")) if Path("data/dev").is_dir() else []
    missing = [d.stem for d in dev if not (Path("goldstandard") / f"{d.stem}.json").is_file()]
    print(f"  {'OK   ' if gold else 'MISS '} {len(gold)} gold standard(s) written")
    if missing:
        print(f"  WARN  dev schemas without ground truth: {missing}")
    if not gold:
        blockers.append("no gold standards — nothing can be evaluated")

    print(f"\nSealed directory ({cfg.paths.heldout_dir})")
    heldout = Path(cfg.paths.heldout_dir)
    contents = (
        [p.name for p in heldout.iterdir() if p.name != ".gitkeep"]
        if heldout.is_dir() else []
    )
    if contents:
        print(f"  FAIL  already contains: {contents}")
        blockers.append(
            "HELD-OUT SCHEMAS ALREADY EXIST. The freeze must predate them "
            "(§11). Tagging now would claim an ordering the history does not "
            "show. Move them out, tag, then put them back — and record honestly "
            "in decisions.md that they were constructed before the tag if that "
            "is what happened."
        )
    else:
        print("  OK    empty")

    print("\nGit")
    code, _ = _git("rev-parse", "--git-dir")
    if code != 0:
        print("  FAIL  not a git repository")
        blockers.append("git repository not initialised — the freeze needs a commit history")
    else:
        code, dirty = _git("status", "--porcelain")
        if dirty:
            n = len(dirty.splitlines())
            print(f"  WARN  {n} uncommitted change(s)")
            blockers.append("working tree is dirty — commit first so the tag is unambiguous")
        else:
            print("  OK    working tree clean")

    print("\n" + "=" * 66)
    if blockers:
        print(f"NOT READY — {len(blockers)} blocker(s):\n")
        for b in blockers:
            print(f"  - {b}")
        return 1

    print("READY TO FREEZE")
    record = {
        "frozen_on": date.today().isoformat(),
        "artefacts": artefacts,
        "gold_standards": [g.stem for g in gold],
        "git_commit": _git("rev-parse", "HEAD")[1],
    }

    if args.check or not args.tag:
        print("\nCheck only. Re-run with --tag <name> to create the tag.")
        print(json.dumps(record, indent=2))
        return 0

    code, out = _git("tag", "-a", args.tag, "-m", f"Artefact freeze {record['frozen_on']}")
    if code != 0:
        print(f"\nTag failed: {out}")
        return 1
    record["tag"] = args.tag
    Path("decisions_freeze_record.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nTagged {args.tag}")
    print("Wrote decisions_freeze_record.json — paste its contents into decisions.md.")
    print(f"\nNow, and only now, add the held-out schemas to {cfg.paths.heldout_dir}/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
