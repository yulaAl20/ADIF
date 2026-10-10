"""Generate the JSON-LD @context from the CDM schema (FR-12.2).

    python -m scripts.build_cdm_context

Reads ``cdm/cdm_v1.0.schema.json`` and writes ``cdm/cdm_v1.0.context.jsonld``.

Generated, never hand-written. A context maintained by hand drifts from the
schema it describes the first time a field is renamed, and the resulting
JSON-LD is silently wrong in a way no test catches — the document still parses,
it just means something different.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.cdm.registry import CdmRegistry
from src.config import load_config
from src.validation.validator import build_context

DEFAULT_VOCAB = "https://adif.example/ns/cdm#"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the CDM JSON-LD context")
    parser.add_argument("--vocab", default=DEFAULT_VOCAB,
                        help="Namespace IRI for CDM terms")
    args = parser.parse_args()

    cfg = load_config("config/default.yaml")
    schema, aliases = Path(cfg.paths.cdm_schema), Path(cfg.paths.alias_vocabulary)

    if not schema.is_file():
        raise SystemExit(
            f"{schema} does not exist yet.\n"
            f"The CDM schema is derived from ESPR Annex III, Annex I, EPCIS 2.0 "
            f"and UNTP — see cdm/EXTRACTION.md. This script generates the "
            f"context FROM that schema; it cannot invent the field list."
        )
    if not aliases.is_file():
        raise SystemExit(f"{aliases} does not exist yet. See cdm/EXTRACTION.md.")

    registry = CdmRegistry.load(schema, aliases, cfg.normalisation)
    out = Path(cfg.paths.cdm_context)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"@context": build_context(registry, args.vocab)}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {out} with {len(registry.fields)} terms.")
    print("Regenerate this whenever the CDM schema changes, and re-freeze both together.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
