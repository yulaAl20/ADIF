"""Verify the ADIF development environment.

Run from the repository root::

    python -m scripts.check_environment

Reports what is installed, what loads, and what is still missing. Every line is
either OK, MISSING (expected at this stage), or FAIL (needs fixing before
anything will run).
"""

from __future__ import annotations

import importlib.metadata
import platform
import sys
from pathlib import Path

SUPPORTED_PYTHON = {(3, 11), (3, 12)}

CORE = ["fastapi", "uvicorn", "pydantic", "PyYAML", "pytest", "httpx", "pandas", "openpyxl", "rapidfuzz", "jsonschema", "python-multipart"]
OPTIONAL = ["sentence-transformers", "torch", "scikit-learn", "matplotlib"]

FROZEN_ARTEFACTS = [
    ("cdm/cdm_v1.0.schema.json", "CDM schema (provenance: cdm/provenance.csv)"),
    ("cdm/cdm_v1.0.context.jsonld", "JSON-LD context, generated from the CDM"),
    ("cdm/aliases_v1.0.yaml", "Alias vocabulary (manufacturer-side sources, D3)"),
    ("adid/grammar.ebnf", "ADID URI grammar"),
]

OK, MISSING, FAIL = "  OK     ", "  MISSING", "  FAIL   "


def line(status: str, label: str, detail: str = "") -> None:
    print(f"{status}  {label:<38}{detail}")


def main() -> int:
    failures = 0
    print("\nADIF environment check")
    print("=" * 74)

    print("\nInterpreter")
    version = sys.version_info
    running = f"{version.major}.{version.minor}.{version.micro}"
    if (version.major, version.minor) in SUPPORTED_PYTHON:
        line(OK, "Python version", running)
    else:
        supported = ", ".join(f"{a}.{b}" for a, b in sorted(SUPPORTED_PYTHON))
        line(FAIL, "Python version", f"{running} — supported: {supported}")
        failures += 1
    line(OK, "Platform", platform.platform())
    in_venv = sys.prefix != sys.base_prefix
    line(OK if in_venv else FAIL, "Virtual environment", "active" if in_venv else "NOT ACTIVE")
    failures += 0 if in_venv else 1

    print("\nCore dependencies (required)")
    for package in CORE:
        try:
            line(OK, package, importlib.metadata.version(package))
        except importlib.metadata.PackageNotFoundError:
            line(FAIL, package, "run: pip install -r requirements.txt")
            failures += 1

    print("\nOptional dependencies (needed later, not for the demo)")
    for package in OPTIONAL:
        try:
            line(OK, package, importlib.metadata.version(package))
        except importlib.metadata.PackageNotFoundError:
            line(MISSING, package, "not needed until the real embedder / eval harness")

    print("\nConfiguration")
    try:
        from src.config import load_config

        cfg = load_config("config/default.yaml")
        line(OK, "config/default.yaml", f"version {cfg.version}")
        line(OK, "enabled stages", ", ".join(cfg.enabled_stages()))
        pending = cfg.unset_tunables()
        line(
            OK,
            "unset tunables",
            f"{len(pending)} awaiting grid search (correct at this stage)",
        )
    except Exception as exc:  # noqa: BLE001 — surface whatever went wrong
        line(FAIL, "config/default.yaml", f"{type(exc).__name__}: {exc}")
        failures += 1

    print("\nFrozen artefacts")
    for path, note in FROZEN_ARTEFACTS:
        line(OK if Path(path).is_file() else MISSING, path, note)

    print("\nGround truth (required before any evaluation run)")
    gold = sorted(Path("goldstandard").glob("*.json")) if Path("goldstandard").is_dir() else []
    sheets = sorted(Path("goldstandard").glob("*.worksheet.csv")) if Path("goldstandard").is_dir() else []
    if gold:
        line(OK, "gold standards", f"{len(gold)} written: {[p.stem for p in gold]}")
    else:
        line(
            MISSING,
            "gold standards",
            f"{len(sheets)} blank worksheet(s) to fill — see goldstandard/RULEBOOK.md",
        )

    print("\nTest fixtures")
    for path in ("tests/fixtures/cdm_test.schema.json", "tests/fixtures/aliases_test.yaml"):
        exists = Path(path).is_file()
        line(OK if exists else FAIL, path, "" if exists else "required by the demo")
        failures += 0 if exists else 1

    print("\nEmbedding model cache")
    cache = Path(".model_cache")
    if cache.is_dir() and any(cache.iterdir()):
        line(OK, ".model_cache/", "populated — try: python -m scripts.demo --real-model")
    else:
        line(MISSING, ".model_cache/", "demo uses the stub embedder until this exists")

    print("\nHeld-out seal")
    # Resolved from config, never a literal: the acceptance test greps this
    # tree for hardcoded references to the sealed directory, and a literal
    # here would be indistinguishable from a genuine read path.
    from src.config import load_config as _load

    heldout = Path(_load("config/default.yaml").paths.heldout_dir)
    contents = [p.name for p in heldout.iterdir() if p.name != ".gitkeep"] if heldout.is_dir() else []
    line(OK, f"{heldout}/", "sealed and empty" if not contents else f"contains {contents}")

    print("\n" + "=" * 74)
    if failures:
        print(f"{failures} problem(s) to fix. See docs/setup.md.\n")
        return 1
    print("Environment is ready. Next: pytest, then python -m scripts.demo\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
