"""ADID identifier forms (D41).

An ADID *is* a version-4 UUID (RFC 9562). It has three textual forms, each with
a different job:

``urn:uuid:{uuid}``
    The canonical, infrastructure-independent name. Registered URN namespace
    (RFC 9562 §4), so no new namespace has to be governed.
``https://{resolver}/adid/{uuid}``
    The resolvable locator printed in a QR code. ``{resolver}`` is the stable
    **root resolver** host, not an individual registry node, so nodes can be
    added, moved or retired without invalidating a printed label (the DOI /
    handle-system pattern).
``{uuid}``
    The bare form used in API paths and storage.

Why version 4 and not the alternatives:

* **v1 / v6 / v7** embed a timestamp (and v1 a MAC address). A garment's
  identifier would then disclose when — and for v1 on which machine — it was
  registered. That is information leakage with no benefit to resolution.
* **v3 / v5** are name-based: derived deterministically from attributes. That
  re-introduces exactly the dependence on encoded attributes this redesign
  removes — correct the colour and the derived identifier changes.
* **v4** carries 122 random bits and nothing else. Collision probability for
  n identifiers is about n² / 2¹²³; for 10¹² garments that is ~10⁻¹³.
"""

from __future__ import annotations

import uuid

__all__ = ["AdidFormatError", "new_adid", "parse_adid", "to_urn", "to_uri", "is_adid"]

DEFAULT_RESOLVER = "https://id.adir.example"


class AdidFormatError(ValueError):
    """A string is not a well-formed ADID."""


def new_adid() -> str:
    """Mint a new ADID (random UUID v4, lowercase canonical text form)."""
    return str(uuid.uuid4())


def parse_adid(text: str) -> str:
    """Accept any of the three textual forms and return the bare UUID.

    Raises:
        AdidFormatError: If the value is not a version-4 UUID.
    """
    raw = text.strip()
    lowered = raw.lower()
    if lowered.startswith("urn:uuid:"):
        raw = raw[9:]
    elif "/adid/" in lowered:
        raw = raw[lowered.rindex("/adid/") + 6:].split("/")[0].split("?")[0]
    try:
        value = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise AdidFormatError(f"'{text}' is not a UUID-based ADID.") from exc
    if value.version != 4 or value.variant != uuid.RFC_4122:
        raise AdidFormatError(
            f"'{text}' is a UUID but not version 4. ADIDs are random UUIDs so that "
            "they carry no timestamp, hardware or attribute information."
        )
    return str(value)


def is_adid(text: str) -> bool:
    """True if ``text`` is an ADID in any of its three forms."""
    try:
        parse_adid(text)
        return True
    except AdidFormatError:
        return False


def to_urn(adid: str) -> str:
    """Canonical, infrastructure-independent form: ``urn:uuid:{uuid}``."""
    return f"urn:uuid:{adid}"


def to_uri(adid: str, resolver: str = DEFAULT_RESOLVER) -> str:
    """Resolvable locator under the stable root resolver host."""
    return f"{resolver.rstrip('/')}/adid/{adid}"


# ---------------------------------------------------------------------------
# ADID v2 canonical paths (D51) — proposed post-freeze design.
#
#   family    /adid/{familyUUID}
#   variant   /adid/{familyUUID}/{colour}_{size}
#   instance  /adid/{familyUUID}/{colour}_{size}/{instanceUUID}
#
# Path depth still determines the level, exactly as in the frozen v1.0
# grammar (adid/grammar.ebnf). Every v2 path is also a valid v1.0 adid-path:
# a lowercase UUID matches v1's ``segment`` rule. See adid/grammar_v2.ebnf.
#
# The variant segment is *issued once* from the colour and size recorded at
# registration and is then immutable. A later correction to the colour or size
# attribute updates the record, not the segment — so the address printed on a
# label keeps resolving. The variant's own UUID is exposed as metadata.
# ---------------------------------------------------------------------------

import re as _re

_SEG = _re.compile(r"^[a-z0-9][a-z0-9-]*$")
_UUID4 = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def variant_key(colour: str, size: str) -> str:
    """Issue the variant segment ``{colour}_{size}`` (v1.0 slug rules)."""
    from src.identity.adid import slugify  # the frozen v1.0 slug function, reused unchanged

    return f"{slugify(str(colour))}_{slugify(str(size))}"


def adid_path(family: str, variant: str | None = None, instance: str | None = None) -> str:
    """Canonical v2 path for a family, variant or instance."""
    parts = ["adid", parse_adid(family)]
    if variant is not None:
        parts.append(variant)
    if instance is not None:
        if variant is None:
            raise AdidFormatError("An instance path needs its variant segment.")
        parts.append(parse_adid(instance))
    path = "/" + "/".join(parts)
    parse_path(path)  # validate
    return path


def parse_path(path: str) -> dict[str, str | None]:
    """Parse and validate a v2 path. Returns family, variant, instance and level.

    Raises:
        AdidFormatError: If the path breaks the v2 grammar.
    """
    parts = [p for p in path.strip().split("?")[0].strip("/").split("/") if p]
    if not parts or parts[0] != "adid" or not 2 <= len(parts) <= 4:
        raise AdidFormatError(f"'{path}' is not an ADID v2 path (/adid/{{family}}[/{{variant}}[/{{instance}}]]).")
    family, variant, instance = parts[1].lower(), None, None
    if not _UUID4.match(family):
        raise AdidFormatError(f"Family segment '{parts[1]}' must be a version-4 UUID.")
    if len(parts) >= 3:
        variant = parts[2].lower()
        colour, sep, size = variant.partition("_")
        if not sep or not _SEG.match(colour) or not _SEG.match(size):
            raise AdidFormatError(f"Variant segment '{parts[2]}' must be '{{colour}}_{{size}}'.")
    if len(parts) == 4:
        instance = parts[3].lower()
        if not _UUID4.match(instance):
            raise AdidFormatError(f"Instance segment '{parts[3]}' must be a version-4 UUID.")
    level = "instance" if instance else "variant" if variant else "family"
    return {"family": family, "variant": variant, "instance": instance, "level": level}


def path_uri(path: str, resolver: str = DEFAULT_RESOLVER) -> str:
    """Resolvable URI for a canonical path."""
    return f"{resolver.rstrip('/')}{path}"
