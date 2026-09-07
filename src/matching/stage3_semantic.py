"""Stage 3 — semantic similarity via sentence embeddings (M5, FR-5.1 to FR-5.7).

The embedder sits behind a protocol for two reasons that are both requirements
rather than preferences. NFR-1 forbids any network access at runtime, and the
80 MB model must be cached locally and loaded with downloads disabled; a
process that silently reaches for Hugging Face would fail the offline
acceptance test. And NFR-5 requires reproducibility, which a deterministic stub
gives the test suite without the model present at all — tests that need a
2 GB torch install to run are tests that stop being run.

:class:`StubEmbedder` is for tests only. It produces stable hash-derived
vectors: useful for asserting that the *plumbing* is correct, meaningless as
similarity. It must never appear in an evaluation run, and the arbitration
layer records which embedder produced a result so that cannot happen silently.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, runtime_checkable

from src.analyser.profile import ColumnProfile
from src.cdm.registry import CdmRegistry
from src.config import SemanticStage
from src.matching.models import Candidate, Stage

__all__ = ["Embedder", "MiniLMEmbedder", "SemanticIndex", "StubEmbedder"]

_DIMS = 32


@runtime_checkable
class Embedder(Protocol):
    """Anything that turns strings into unit-length vectors."""

    name: str

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input string."""
        ...


def _normalise(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / magnitude for v in vector]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two unit-length vectors, clamped to [-1, 1]."""
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))


class StubEmbedder:
    """Deterministic hash-based embedder. **Tests only — never evaluation.**

    Produces stable vectors so pipeline wiring can be asserted without the real
    model. The similarities it produces carry no semantic meaning whatsoever.
    """

    name = "stub-deterministic"

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.lower().encode("utf-8")).digest()
            raw = [digest[i % len(digest)] / 255.0 for i in range(_DIMS)]
            vectors.append(_normalise(raw))
        return vectors


class MiniLMEmbedder:
    """``all-MiniLM-L6-v2`` loaded from a local cache with networking disabled.

    The import is deliberately lazy so that neither the test suite nor the
    ingestion path pays a multi-second torch import they do not need.
    """

    def __init__(self, model_name: str, cache_dir: str, revision: str | None = None):
        import inspect
        import os

        # These two are the load-bearing offline guarantee, and they are what
        # the NFR-1 acceptance test actually exercises: huggingface_hub reads
        # them at call time and raises rather than reaching the network.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer  # lazy: heavy

        kwargs: dict[str, object] = {"cache_folder": cache_dir}

        # The revision MUST be passed through, not merely recorded. Keeping it
        # only in ``self.name`` and in the run record made the pin decorative:
        # the loader would happily take whatever revision happened to be in the
        # cache while every run record claimed the pinned one. That is a
        # reproducibility claim the artefact could not support (NFR-5).
        if revision:
            kwargs["revision"] = revision

        # ``local_files_only`` was added to SentenceTransformer.__init__ in
        # 3.x. Passing it unconditionally raises TypeError on 2.x, which is
        # inside the range requirements-optional.txt originally allowed. The
        # signature check keeps the stronger assertion where it exists and
        # falls back to the environment variables above where it does not,
        # rather than forcing a multi-gigabyte reinstall to satisfy a keyword.
        if "local_files_only" in inspect.signature(SentenceTransformer.__init__).parameters:
            kwargs["local_files_only"] = True

        self._model = SentenceTransformer(model_name, **kwargs)
        self.name = f"{model_name}@{revision or 'unpinned'}"

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]


class SemanticIndex:
    """Pre-computed CDM-side embeddings (FR-5.2, FR-5.7).

    Built once per registry. The index records the CDM schema hash it was built
    from so a stale cache can be detected and rebuilt rather than silently
    scoring against the wrong field set.
    """

    def __init__(self, registry: CdmRegistry, embedder: Embedder) -> None:
        self.embedder = embedder
        self.field_names = registry.names()
        self.built_from_schema_sha256 = registry.schema_sha256
        texts = [f.embedding_text() for f in registry.fields]
        self.vectors = embedder.encode(texts)

    def is_stale(self, registry: CdmRegistry) -> bool:
        """True when the CDM has changed since this index was built (FR-5.7)."""
        return self.built_from_schema_sha256 != registry.schema_sha256

    def match(
        self,
        column: ColumnProfile,
        cfg: SemanticStage,
    ) -> list[Candidate]:
        """Rank CDM fields by cosine similarity to a column header (FR-5.3).

        Cosine similarity runs in [-1, 1]; it is mapped onto [0, 100] so every
        stage reports on one comparable scale before calibration. That mapping
        is presentational — it is not itself a confidence, per D6.
        """
        query = self.embedder.encode([column.normalised_header])[0]
        candidates = [
            Candidate(
                cdm_field=name,
                raw_score=round((cosine(query, vector) + 1.0) * 50.0, 4),
                stage=Stage.SEMANTIC,
                matched_on=name,
            )
            for name, vector in zip(self.field_names, self.vectors)
        ]
        candidates.sort(key=lambda c: (-c.raw_score, c.cdm_field))
        return candidates[: cfg.top_k]
