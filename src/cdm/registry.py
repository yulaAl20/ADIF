"""Canonical Data Model registry — the contract every matching stage codes against.

Nothing downstream of this module knows what the CDM *contains*. Stages score
headers against whatever :class:`CanonicalField` list is loaded, the ADID
constructor builds identifiers rather than data, and the API serialises
whatever validated. That separation is what lets the prototype be built before
the field list is extracted from the standards, and it means the real CDM
arrives as a data drop rather than a code change.

Two load-time checks exist because both failure modes are silent and would
otherwise surface as depressed matching accuracy that looks like an algorithm
problem:

**Aliases are normalised with the same function as headers.** Stage 1 is an
exact match between a normalised header and a normalised alias. If the two
sides were canonicalised differently, Stage 1 would simply never fire, every
field would fall through to fuzzy and semantic matching, and the ablation would
report that the alias stage contributes nothing.

**Colliding aliases are rejected.** ``Product_Name`` and ``product name``
normalise to the same key. If they pointed at different CDM fields, Stage 1's
result would depend on dictionary ordering — a reproducibility failure under
NFR-5 that would be very hard to trace back to the vocabulary file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.analyser.normalise import normalise_header
from src.config import Normalisation
from src.provenance import file_sha256

__all__ = ["AliasCollisionError", "CanonicalField", "CdmRegistry", "CdmVocabularyError"]


class CdmVocabularyError(ValueError):
    """The alias vocabulary is inconsistent with the frozen CDM schema (FR-3.6)."""


class AliasCollisionError(CdmVocabularyError):
    """Two CDM fields claim aliases that normalise to the same key."""


@dataclass(frozen=True)
class CanonicalField:
    """One CDM field, as the matching stages see it."""

    name: str
    description: str
    datatype: str
    mandatory: bool
    aliases: tuple[str, ...] = ()

    def embedding_text(self) -> str:
        """Return the string the semantic stage encodes (FR-5.2).

        Field name *and* description, because ``all-MiniLM-L6-v2`` is trained
        on natural language: "fibre composition by percentage weight" embeds
        far more usefully than ``fibreComposition``.
        """
        return f"{self.description}" if self.description else self.name


class CdmRegistry:
    """The loaded CDM schema and alias vocabulary."""

    def __init__(
        self,
        fields: list[CanonicalField],
        schema: dict,
        schema_sha256: str | None = None,
        alias_sha256: str | None = None,
    ) -> None:
        self.fields = fields
        self.schema = schema
        self.schema_sha256 = schema_sha256
        self.alias_sha256 = alias_sha256
        self._by_name = {f.name: f for f in fields}
        self._alias_index = self._build_alias_index(fields)

    @staticmethod
    def _build_alias_index(fields: list[CanonicalField]) -> dict[str, str]:
        index: dict[str, str] = {}
        for field in fields:
            for alias in field.aliases:
                if alias in index and index[alias] != field.name:
                    raise AliasCollisionError(
                        f"Alias key '{alias}' is claimed by both "
                        f"'{index[alias]}' and '{field.name}'. Normalised alias "
                        f"keys must be unique, otherwise Stage 1's result "
                        f"depends on load order and runs stop being "
                        f"reproducible (NFR-5)."
                    )
                index[alias] = field.name
        return index

    def by_name(self, name: str) -> CanonicalField:
        """Return one field by CDM name."""
        return self._by_name[name]

    def names(self) -> list[str]:
        """Return all CDM field names, in schema order."""
        return [f.name for f in self.fields]

    def mandatory_names(self) -> list[str]:
        """Return names of mandatory fields (FR-10.3 coverage reporting)."""
        return [f.name for f in self.fields if f.mandatory]

    def resolve_alias(self, compact_header: str) -> str | None:
        """Return the CDM field a normalised header exactly matches, if any."""
        return self._alias_index.get(compact_header)

    def alias_count(self) -> int:
        """Total alias entries across all fields."""
        return len(self._alias_index)

    @classmethod
    def load(
        cls,
        schema_path: str | Path,
        alias_path: str | Path,
        normalisation: Normalisation,
    ) -> CdmRegistry:
        """Load the frozen CDM schema and alias vocabulary.

        Args:
            schema_path: Path to ``cdm_v1.0.schema.json``.
            alias_path: Path to ``aliases_v1.0.yaml``, mapping CDM field names
                to lists of raw alias strings.
            normalisation: The normalisation config, applied to aliases so both
                sides of the Stage 1 comparison are canonicalised identically.

        Returns:
            A populated :class:`CdmRegistry`.

        Raises:
            CdmVocabularyError: If an alias maps to a field absent from the
                schema (FR-3.6), or two fields claim the same normalised alias.
        """
        schema_path, alias_path = Path(schema_path), Path(alias_path)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        raw_aliases: dict[str, list[str]] = (
            yaml.safe_load(alias_path.read_text(encoding="utf-8")) or {}
        )

        properties: dict[str, dict] = schema.get("properties", {})
        required = set(schema.get("required", []))

        unknown = set(raw_aliases) - set(properties)
        if unknown:
            raise CdmVocabularyError(
                f"The alias vocabulary maps to CDM fields that do not exist in "
                f"the frozen schema: {sorted(unknown)}. Fix the vocabulary or "
                f"the schema — do not let a run proceed with either out of date."
            )

        fields: list[CanonicalField] = []
        for name, spec in properties.items():
            aliases = [name, *raw_aliases.get(name, [])]
            normalised = {
                normalise_header(a, normalisation).compact for a in aliases
            }
            fields.append(
                CanonicalField(
                    name=name,
                    description=spec.get("description", ""),
                    datatype=spec.get("type", "string"),
                    mandatory=name in required,
                    aliases=tuple(sorted(normalised)),
                )
            )

        return cls(
            fields=fields,
            schema=schema,
            schema_sha256=file_sha256(schema_path),
            alias_sha256=file_sha256(alias_path),
        )
