"""ADID — Apparel DPP Identity Model (M11, FR-11.1 to FR-11.7).

Three levels, per ESPR Art. 9(2)(d) which requires a delegated act to state
whether a passport sits at model, batch or item level:

``family``
    The design. "Top A", regardless of colour or size. **A family has no native
    GS1 identifier** — a GTIN identifies one colour-and-size combination, never
    a whole design — and supplying one is ADID's actual contribution rather
    than a restatement of GS1.
``variant``
    One colour-and-size combination. One GTIN each.
``instance``
    One physical unit. GTIN plus serial number, i.e. an SGTIN.

**URI shape.** ``methodology.md`` and ``project.md`` disagreed: the former gave
``/adid/{family}/{colour}/{size}``, the latter ``/adid/{family}/{variant}/
{instance}``. Those are different depths, and at three segments they collide —
``/adid/TOP-A/navy/M`` could be read either way. Resolved by making the variant
a **single composite segment**, ``{colour}_{size}``, so colour and size remain
the variant's dimensions while path depth stays unambiguous:

    depth 1 → family    depth 2 → variant    depth 3 → instance

**Identity, not data.** Only attributes that distinguish *which* item is being
addressed belong in the path. Material, origin and season describe an item
without identifying it, and live in the CDM record. That split is decisions.md
D9 and it is what stops a data correction from changing an identifier — a
mistyped fibre content must never invalidate every printed QR code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

__all__ = [
    "AdidError",
    "AdidIdentifier",
    "SEGMENT_PATTERN",
    "VARIANT_SEPARATOR",
    "conformance_statement",
    "slugify",
]

VARIANT_SEPARATOR = "_"
SEGMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class AdidError(ValueError):
    """An ADID could not be constructed or parsed."""


def slugify(text: str) -> str:
    """Lowercase, hyphenate, and strip a value into one path segment.

    Hyphen is the intra-value separator, which is why the variant's two
    dimensions are joined with an underscore instead: ``navy-blue_xl`` splits
    unambiguously, whereas ``navy-blue-xl`` does not.

    Raises:
        AdidError: If nothing usable survives normalisation.
    """
    slug = _SLUG_STRIP.sub("-", text.strip().lower()).strip("-")
    if not slug or not SEGMENT_PATTERN.match(slug):
        raise AdidError(
            f"'{text}' does not yield a usable ADID path segment. Segments must "
            f"contain at least one letter or digit."
        )
    return slug


@dataclass(frozen=True)
class AdidIdentifier:
    """A resolvable ADID at family, variant or instance level."""

    manufacturer: str
    family: str
    colour: str | None = None
    size: str | None = None
    serial: str | None = None

    def __post_init__(self) -> None:
        if self.serial is not None and (self.colour is None or self.size is None):
            raise AdidError(
                "An instance-level ADID requires colour and size: an instance is "
                "one physical unit of a specific variant, so it cannot be "
                "addressed without naming that variant."
            )
        if (self.colour is None) != (self.size is None):
            raise AdidError(
                "A variant is a colour-and-size pair. Supply both or neither — "
                "a half-specified variant identifies a set, not a variant."
            )

    @property
    def level(self) -> str:
        """Return ``family``, ``variant`` or ``instance``."""
        if self.serial is not None:
            return "instance"
        return "variant" if self.colour is not None else "family"

    @property
    def variant_key(self) -> str | None:
        """The composite ``{colour}_{size}`` segment, if this is variant-level."""
        if self.colour is None or self.size is None:
            return None
        return f"{slugify(self.colour)}{VARIANT_SEPARATOR}{slugify(self.size)}"

    def path(self) -> str:
        """Return the ADID path, without scheme or host."""
        segments = ["adid", slugify(self.family)]
        if (key := self.variant_key) is not None:
            segments.append(key)
        if self.serial is not None:
            segments.append(slugify(self.serial))
        return "/" + "/".join(quote(s, safe="-_") for s in segments)

    def uri(self, base: str | None = None) -> str:
        """Return the absolute ADID URI.

        Args:
            base: Override the default ``https://dpp.{manufacturer}`` host.
        """
        root = (base or f"https://dpp.{slugify(self.manufacturer)}").rstrip("/")
        return f"{root}{self.path()}"

    def parent(self) -> AdidIdentifier | None:
        """Return the identifier one level up, or ``None`` at family level."""
        if self.level == "instance":
            return AdidIdentifier(self.manufacturer, self.family, self.colour, self.size)
        if self.level == "variant":
            return AdidIdentifier(self.manufacturer, self.family)
        return None

    @classmethod
    def parse(cls, path: str, manufacturer: str = "unknown") -> AdidIdentifier:
        """Parse an ADID path back into an identifier.

        Args:
            path: A path such as ``/adid/top-a/navy_m/sn-001``.
            manufacturer: Host-derived manufacturer, which the path omits.

        Raises:
            AdidError: On a malformed path or an unparseable variant segment.
        """
        parts = [unquote(p) for p in path.strip("/").split("/") if p]
        if not parts or parts[0] != "adid":
            raise AdidError(f"'{path}' is not an ADID path: it must start with /adid/.")
        parts = parts[1:]
        if not 1 <= len(parts) <= 3:
            raise AdidError(
                f"'{path}' has {len(parts)} segments after /adid/. Expected 1 "
                f"(family), 2 (variant) or 3 (instance)."
            )

        family, colour, size, serial = parts[0], None, None, None
        if len(parts) >= 2:
            if VARIANT_SEPARATOR not in parts[1]:
                raise AdidError(
                    f"Variant segment '{parts[1]}' must be "
                    f"'{{colour}}{VARIANT_SEPARATOR}{{size}}'."
                )
            colour, size = parts[1].split(VARIANT_SEPARATOR, 1)
        if len(parts) == 3:
            serial = parts[2]
        return cls(manufacturer, family, colour, size, serial)


def conformance_statement() -> dict[str, object]:
    """Machine-readable statement of what ADID claims (FR-11.7).

    Deliberately states **compatibility, not compliance**, and says why. Two
    claims in this project are unverified and must not be implied by silence:
    the GS1 Digital Link URI syntax has not been run against GS1's own
    validator, and the EN 18219 reference in project.md FR-11.7 is recorded as
    UNVERIFIED in sources.md.

    A conformance statement that overstates is worse than none: an examiner who
    checks one claim and finds it unsupported will distrust the others.
    """
    return {
        "profile": "ADID — Apparel DPP Identity Model v1.0",
        "levels": ["family", "variant", "instance"],
        "variant_composition": ["colour", "size"],
        "uri_template": "https://dpp.{manufacturer}/adid/{family}/{colour}_{size}/{serial}",
        "grammar": "adid/grammar.ebnf",
        "espr_basis": {
            "clause": "Art. 9(2)(d); Art. 10(1)(f)",
            "levels_named_by_regulation": ["model", "batch", "item"],
            "note": (
                "ESPR names a BATCH level that ADID v1.0 does not carry. See "
                "decisions.md D22 and cdm/ALIGNMENT.md — this is an open "
                "decision, not an oversight."
            ),
        },
        "gs1_digital_link": {
            "claim": "compatible extension",
            "compliant": False,
            "reason": (
                "Not validated against the GS1 Digital Link URI syntax "
                "specification. project.md §13 requires this be settled by "
                "testing candidate URIs against a validator, not by assertion."
            ),
        },
        "en_18219": {
            "standard": "EN 18219:2026 — Digital product passport: Unique identifiers",
            "published": "2026-05-27",
            "harmonised": "2026-07-15",
            "claim": None,
            "status": "SCHEME NOT YET CLAIMED",
            "candidate_scheme": "IEC 61406 self-issued link",
            "reason": (
                "EN 18219:2026 permits five identifier schemes: GS1 Digital Link "
                "URI, IEC 61406 self-issued links, W3C DIDs, RFID/2D "
                "identifiers, and DOIs. ADID issues a URI under the "
                "manufacturer's own domain, which is structurally a SELF-ISSUED "
                "link rather than a GS1 Digital Link — so IEC 61406 is the "
                "likelier profile, and GS1 Digital Link conformance may not be "
                "the relevant test at all. "
                "NOT CONFIRMED: EN 18219 is a paid standard and has not been "
                "read. Obtain it, confirm the IEC 61406 profile requirements, "
                "and only then set a claim here."
            ),
        },
    }
