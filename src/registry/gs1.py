"""GS1 interoperability helpers (closes issue 7).

The ADID registry does not replace GS1 identifiers; it records them as alternate identifiers
of the entity they identify — a GTIN against a *variant*, a GTIN + serial
(SGTIN) against an *instance* — and emits the corresponding GS1 Digital Link
URI so that a GS1-aware scanner and the ADID resolver reach the same record.

The family/model level has no GS1 identifier, which is the gap ADID fills.
"""

from __future__ import annotations

import re

from src.matching.stage4_value import gtin_check_digit_valid

__all__ = ["normalise_gtin", "digital_link", "sgtin_key", "GS1_DL_ROOT"]

GS1_DL_ROOT = "https://id.gs1.org"
#: GS1 AI (21) serial: up to 20 characters from GS1 AI encodable set 82. The
#: subset used here (alphanumerics and - . _ /) is conservative.
_SERIAL = re.compile(r"^[A-Za-z0-9\-._/]{1,20}$")


def normalise_gtin(value: str | None) -> str | None:
    """Return the 14-digit form of a valid GTIN-8/12/13/14, else ``None``.

    GS1 Digital Link uses the 14-digit form in the path (zero-padded).
    """
    if value is None:
        return None
    digits = str(value).strip()
    if digits.endswith(".0"):  # spreadsheet float artefact
        digits = digits[:-2]
    if not gtin_check_digit_valid(digits):
        return None
    return digits.zfill(14)


def valid_serial(serial: str | None) -> bool:
    """True if ``serial`` fits the conservative GS1 AI (21) character subset."""
    return bool(serial) and bool(_SERIAL.match(str(serial)))


def sgtin_key(gtin14: str, serial: str) -> str:
    """Registry key for an SGTIN: ``{gtin14}.{serial}``."""
    return f"{gtin14}.{serial}"


def digital_link(gtin14: str, serial: str | None = None, root: str = GS1_DL_ROOT) -> str:
    """GS1 Digital Link URI: ``/01/{gtin14}`` or ``/01/{gtin14}/21/{serial}``."""
    uri = f"{root.rstrip('/')}/01/{gtin14}"
    if serial is not None:
        uri += f"/21/{serial}"
    return uri
