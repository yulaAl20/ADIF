"""Header normalisation (M2) — FR-2.6, FR-2.7.

This is the highest-leverage twenty lines in the matching pipeline. Stage 1
alias lookup is an exact match against the ``compact`` form produced here, so
every field that normalisation fails to canonicalise falls through to fuzzy and
semantic matching unnecessarily — inflating cost and depressing precision. A
normalisation bug looks, in the results, exactly like a matching failure.

Three forms are emitted because downstream stages want different things:

``normalised``
    Space-separated tokens. What the semantic encoder sees, because
    ``all-MiniLM-L6-v2`` is trained on natural language, not on ``prdctnm``.
``compact``
    Whitespace removed. The exact-match key for Stage 1 alias lookup, so that
    ``Product_Name``, ``productName`` and ``PRODUCT NAME`` collapse to one key.
``tokens``
    The token list, which ``token_sort_ratio`` needs in Stage 2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.config import Normalisation

__all__ = ["NormalisedHeader", "normalise_header", "split_camel_case"]

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalisedHeader:
    """All forms of one column header (FR-2.7 requires raw to be retained)."""

    raw: str
    normalised: str
    compact: str
    tokens: list[str] = field(default_factory=list)


def split_camel_case(text: str) -> str:
    """Insert spaces at camelCase and PascalCase boundaries.

    ``baseColour`` becomes ``base Colour``; ``GTINCode`` becomes ``GTIN Code``.
    The second pattern in the boundary regex handles acronym-to-word
    transitions, which a naive lowercase-to-uppercase rule splits wrongly.

    Args:
        text: A raw header.

    Returns:
        The header with word boundaries made explicit.
    """
    return _CAMEL_BOUNDARY.sub(" ", text)


def normalise_header(raw: str, cfg: Normalisation) -> NormalisedHeader:
    """Canonicalise one header into the three forms used downstream.

    Order matters. Camel case is split before separators are stripped, so
    ``base_Colour`` yields two tokens rather than one. Abbreviations are
    expanded per token, so a table entry for ``qty`` does not also rewrite
    ``quantity``. Stopwords are removed last.

    Args:
        raw: The header exactly as it appeared in the source file.
        cfg: The normalisation section of the loaded configuration.

    Returns:
        A :class:`NormalisedHeader`. If stopword removal would empty the
        header, the pre-removal tokens are kept: a column named ``of`` is a bad
        header, but an empty match key is a worse one.
    """
    text = raw
    if cfg.split_camel_case:
        text = split_camel_case(text)
    for separator in cfg.strip_separators:
        if separator != " ":
            text = text.replace(separator, " ")
    if cfg.case_fold:
        text = text.lower()
    if cfg.collapse_whitespace:
        text = _WHITESPACE.sub(" ", text)
    text = text.strip()

    tokens = [t for t in text.split(" ") if t]
    tokens = [cfg.abbreviations.get(t, t) for t in tokens]

    stopwords = set(cfg.stopwords)
    kept = [t for t in tokens if t not in stopwords]
    if kept:
        tokens = kept

    normalised = " ".join(tokens)
    return NormalisedHeader(
        raw=raw,
        normalised=normalised,
        compact=normalised.replace(" ", ""),
        tokens=tokens,
    )
