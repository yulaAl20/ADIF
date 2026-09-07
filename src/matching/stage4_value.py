"""Stage 4 — value-based matching (M6, FR-6.1 to FR-6.5).

The only stage that can rescue a column whose *header* carries no information
but whose *values* are diagnostic: a column named ``col_7`` full of ISO 3166
codes is invisible to Stages 1 to 3 and obvious here. Schema C is deliberately
the most idiosyncratic evaluation schema, so this is where the stage should
earn its place — or fail to, which the ablation will show either way.

A signature scores the *fraction of sampled values that conform*, not a
similarity. Ten of ten values matching a country-code pattern is a strong
signal; six of ten is a weak one and should score weakly rather than be
rounded up to a match.

The controlled vocabularies here are shared with CDM validation (FR-10.2), so
the two never drift apart. That reuse is why this stage costs much less than
its specification suggests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.analyser.profile import ColumnProfile
from src.matching.models import Candidate, Stage

__all__ = ["Signature", "SignatureLibrary", "gtin_check_digit_valid"]


def gtin_check_digit_valid(value: str) -> bool:
    """Validate a GTIN-8/12/13/14 modulo-10 check digit.

    Structural validation only — it confirms the number is well-formed, not
    that it was ever issued to anyone. A well-formed GTIN in a manufacturer
    export is still evidence about what the *column* holds, which is all this
    stage claims.
    """
    digits = value.strip()
    if not digits.isdigit() or len(digits) not in (8, 12, 13, 14):
        return False
    body, check = digits[:-1], int(digits[-1])
    total = 0
    for index, char in enumerate(reversed(body)):
        weight = 3 if index % 2 == 0 else 1
        total += int(char) * weight
    return (10 - total % 10) % 10 == check


_CALLABLES = {"gtin_check_digit": gtin_check_digit_valid}


@dataclass(frozen=True)
class Signature:
    """One value-shape test bound to a CDM field."""

    cdm_field: str
    kind: str
    pattern: str | None = None
    vocabulary: tuple[str, ...] = ()
    callable_name: str | None = None
    case_sensitive: bool = False

    def conforms(self, value: str) -> bool:
        """True if a single value matches this signature."""
        text = value.strip()
        if not text:
            return False
        if self.kind == "regex" and self.pattern:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            return re.fullmatch(self.pattern, text, flags) is not None
        if self.kind == "vocabulary":
            probe = text if self.case_sensitive else text.lower()
            return probe in self.vocabulary
        if self.kind == "callable" and self.callable_name:
            return _CALLABLES[self.callable_name](text)
        return False

    def score(self, values: list[str]) -> float:
        """Return the percentage of sampled values that conform (FR-6.2)."""
        if not values:
            return 0.0
        conforming = sum(1 for v in values if self.conforms(v))
        return round(100.0 * conforming / len(values), 4)


class SignatureLibrary:
    """The loaded value-signature library (FR-6.4)."""

    def __init__(self, signatures: list[Signature]) -> None:
        self.signatures = signatures

    @classmethod
    def load(cls, path: str | Path) -> SignatureLibrary:
        """Load signatures from YAML.

        Args:
            path: Path to ``cdm/vocabularies/signatures.yaml``.

        Returns:
            A populated :class:`SignatureLibrary`.
        """
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        signatures: list[Signature] = []
        for cdm_field, specs in raw.items():
            for spec in specs:
                vocab = spec.get("vocabulary", []) or []
                case_sensitive = bool(spec.get("case_sensitive", False))
                signatures.append(
                    Signature(
                        cdm_field=cdm_field,
                        kind=spec["kind"],
                        pattern=spec.get("pattern"),
                        vocabulary=tuple(
                            v if case_sensitive else str(v).lower() for v in vocab
                        ),
                        callable_name=spec.get("callable"),
                        case_sensitive=case_sensitive,
                    )
                )
        return cls(signatures)

    def match(self, column: ColumnProfile, top_k: int = 5) -> list[Candidate]:
        """Rank CDM fields by how well the column's values fit their signatures.

        Args:
            column: The analysed column, carrying deterministic sample values.
            top_k: How many candidates to return.

        Returns:
            Candidates sorted by descending conformance, ties broken by field
            name so the ordering is reproducible (NFR-5).
        """
        best: dict[str, tuple[float, str]] = {}
        for signature in self.signatures:
            score = signature.score(column.sample_values)
            current = best.get(signature.cdm_field, (0.0, ""))
            if score > current[0]:
                best[signature.cdm_field] = (score, signature.kind)

        candidates = [
            Candidate(
                cdm_field=field,
                raw_score=score,
                stage=Stage.VALUE,
                matched_on=f"{kind} signature",
            )
            for field, (score, kind) in best.items()
            if score > 0
        ]
        candidates.sort(key=lambda c: (-c.raw_score, c.cdm_field))
        return candidates[:top_k]
