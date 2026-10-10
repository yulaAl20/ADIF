"""One-time download of the sentence embedding model (FR-5.4, NFR-1).

    python -m scripts.fetch_model

Run once on a connected machine. Afterwards every run loads from the local
cache with networking disabled, which is what NFR-1 requires.

Prints the resolved revision hash. **Record it** in ``config/default.yaml``
under ``matching.stages.semantic.model_revision``. An unpinned model is an
unreproducible result: a silent upstream update changes your numbers with
nothing in the run record to explain the difference.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.config import load_config


def main() -> int:
    cfg = load_config("config/default.yaml")
    model_name = cfg.matching.stages.semantic.model
    cache = Path(cfg.paths.embedding_cache)

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print(
            "sentence-transformers is not installed. It is optional:\n\n"
            "    pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
            "    pip install -r requirements-optional.txt\n\n"
            "Install the CPU wheel FIRST, or pip may pull a multi-gigabyte CUDA "
            "build this project never uses.",
            file=sys.stderr,
        )
        return 1

    print(f"Downloading {model_name} into {cache}/ (~80 MB, one time)...")
    cache.mkdir(parents=True, exist_ok=True)
    SentenceTransformer(model_name, cache_folder=str(cache))

    revision = None
    for meta in cache.rglob("*/refs/main"):
        try:
            revision = meta.read_text(encoding="utf-8").strip()
            break
        except OSError:
            continue
    snapshots = sorted(cache.rglob("snapshots/*"))
    if revision is None and snapshots:
        revision = snapshots[-1].name

    print(f"\nCached to {cache}/")
    if revision:
        print(f"Resolved revision: {revision}")
        print("\nRecord it in config/default.yaml:")
        print(f'    model_revision: "{revision}"')
    else:
        print(
            "\nCould not read the revision hash automatically. Find it under "
            f"{cache}/ (a 'snapshots/<hash>' directory) and record it manually."
        )
    print("\nThen verify offline loading:  python -m scripts.demo --real-model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
