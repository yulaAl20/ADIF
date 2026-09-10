"""CDM validation (M10) and JSON-LD serialisation (M12).

Validation reports rather than raises. An SME operator's first upload will not
be clean, and a validator that aborts on the first problem tells them one thing
per attempt. Collecting every error in one pass turns a series of failures into
a single worklist, which is the difference between the tool being usable and
being abandoned.

The ``@context`` is generated from the CDM schema rather than hand-maintained,
so it can never fall out of step with the field set it describes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from src.cdm.registry import CdmRegistry
from src.identity.adid import AdidIdentifier

__all__ = [
    "ValidationReport",
    "build_context",
    "serialise_jsonld",
    "validate_record",
]


@dataclass
class ValidationReport:
    """Everything wrong with one candidate DPP record (FR-10.1 to FR-10.5)."""

    schema_errors: list[str] = field(default_factory=list)
    vocabulary_errors: list[str] = field(default_factory=list)
    missing_mandatory: list[str] = field(default_factory=list)
    populated_fields: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not (self.schema_errors or self.vocabulary_errors or self.missing_mandatory)

    def mandatory_match_rate(self, registry: CdmRegistry) -> float:
        """Metric 2 — the share of mandatory CDM fields correctly populated.

        Distinct from the design-time "reference attribute set coverage" check
        performed once against the CDM schema itself (decisions.md D12). This
        one is per-run and per-input-schema.
        """
        mandatory = registry.mandatory_names()
        if not mandatory:
            return 1.0
        populated = set(self.populated_fields)
        return round(sum(1 for f in mandatory if f in populated) / len(mandatory), 6)

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.is_valid,
            "schema_errors": self.schema_errors,
            "vocabulary_errors": self.vocabulary_errors,
            "missing_mandatory": self.missing_mandatory,
            "populated_field_count": len(self.populated_fields),
        }


def _load_vocabularies(path: str | Path) -> dict[str, set[str]]:
    """Load controlled vocabularies from the shared signature library.

    Same file Stage 4 uses (FR-6.4 / FR-10.2). One copy, so a value the matcher
    accepts is never one the validator then rejects.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    vocabularies: dict[str, set[str]] = {}
    for cdm_field, specs in raw.items():
        terms = {
            str(v).lower()
            for spec in specs
            if spec.get("kind") == "vocabulary"
            for v in (spec.get("vocabulary") or [])
        }
        if terms:
            vocabularies[cdm_field] = terms
    return vocabularies


def validate_record(
    record: dict[str, Any],
    registry: CdmRegistry,
    vocabulary_path: str | Path | None = None,
) -> ValidationReport:
    """Validate one candidate DPP record against the CDM.

    Args:
        record: Field name to value, as assembled from a mapped row.
        registry: The loaded CDM registry.
        vocabulary_path: Optional controlled-vocabulary file. Vocabulary checks
            are skipped when absent, and their absence is not reported as
            success — an unchecked field is simply unchecked.

    Returns:
        A :class:`ValidationReport` listing every problem found in one pass.
    """
    report = ValidationReport()
    populated = {k: v for k, v in record.items() if v not in (None, "")}
    report.populated_fields = sorted(populated)

    validator = Draft202012Validator(registry.schema)
    for error in sorted(validator.iter_errors(record), key=lambda e: list(e.path)):
        location = ".".join(str(p) for p in error.path) or "(root)"
        report.schema_errors.append(f"{location}: {error.message}")

    report.missing_mandatory = [
        name for name in registry.mandatory_names() if name not in populated
    ]

    if vocabulary_path and Path(vocabulary_path).is_file():
        for cdm_field, allowed in _load_vocabularies(vocabulary_path).items():
            value = populated.get(cdm_field)
            if value is not None and str(value).lower() not in allowed:
                report.vocabulary_errors.append(
                    f"{cdm_field}: '{value}' is not in the controlled vocabulary "
                    f"({len(allowed)} permitted terms)"
                )
    return report


def build_context(registry: CdmRegistry, base_vocab: str) -> dict[str, Any]:
    """Generate the JSON-LD ``@context`` from the CDM schema (FR-12.2).

    Generated rather than hand-written so it cannot drift from the field set.
    """
    return {
        "@vocab": base_vocab,
        "adid": "https://adif.example/ns/adid#",
        **{name: f"{base_vocab}{name}" for name in registry.names()},
    }


def serialise_jsonld(
    record: dict[str, Any],
    identifier: AdidIdentifier,
    registry: CdmRegistry,
    base_vocab: str = "https://adif.example/ns/cdm#",
    context_path: str | Path | None = None,
) -> dict[str, Any]:
    """Serialise a validated record as a JSON-LD DPP document (FR-12.1–12.4).

    Args:
        record: Validated CDM field values.
        identifier: The ADID this record is addressed by.
        registry: The loaded CDM registry.
        base_vocab: Namespace IRI for CDM terms.
        context_path: Use a frozen context file if given, otherwise generate it.

    Returns:
        A JSON-LD document whose ``@id`` is the ADID URI. Identity comes from
        ADID and data from the CDM — the D9 split, made visible in the output.
    """
    if context_path and Path(context_path).is_file():
        context = json.loads(Path(context_path).read_text(encoding="utf-8"))
        context = context.get("@context", context)
    else:
        context = build_context(registry, base_vocab)

    document: dict[str, Any] = {
        "@context": context,
        "@id": identifier.uri(),
        "@type": "DigitalProductPassport",
        "adid:level": identifier.level,
        "adid:family": identifier.family,
    }
    if identifier.variant_key:
        document["adid:variant"] = identifier.variant_key
    if identifier.serial:
        document["adid:instance"] = identifier.serial
    if (parent := identifier.parent()) is not None:
        document["adid:parent"] = parent.uri()

    document.update({k: v for k, v in record.items() if v not in (None, "")})
    return document
