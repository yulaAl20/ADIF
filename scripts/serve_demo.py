"""Serve the review web app for a demonstration, with the real embedding model.

    python -m scripts.serve_demo            # real all-MiniLM-L6-v2, value stage on
    python -m scripts.serve_demo --stub     # stub embedder (no model needed)

Run from the project root, then open http://127.0.0.1:8000/review and upload a
CSV from the page.

Why this exists. ``uvicorn src.api.main:app`` always builds the semantic index
with the STUB embedder (hash-derived noise) and leaves the value stage off, because
the shipped config disables it. A demo through that server can map unrelated
columns at high "confidence". This launcher changes neither the frozen code nor
the frozen config: it only swaps which components the running app uses, so the web
app behaves like the evaluated full cascade.

This is a demonstration server. Nothing run through it is an evaluation.
"""

from __future__ import annotations

import argparse
from functools import lru_cache

import uvicorn

import src.api.main as api
from eval.runner import load_overlay
from src.matching.stage3_semantic import MiniLMEmbedder, SemanticIndex, StubEmbedder
from src.matching.stage4_value import SignatureLibrary

#: The complete cascade, value stage included, as evaluated.
OVERLAY = "config/ablation/full_cascade_value.yaml"


def configure(real_model: bool) -> None:
    """Point the app at the full cascade and (optionally) the real embedder."""
    cfg = load_overlay(overlay_path=OVERLAY)
    stage = cfg.matching.stages.semantic

    @lru_cache(maxsize=1)
    def get_config():
        """The frozen config with the value stage switched on."""
        return cfg

    @lru_cache(maxsize=1)
    def get_index():
        """Semantic index over the CDM, real or stub embedder."""
        registry, _ = api.get_registry()
        if real_model:
            embedder = MiniLMEmbedder(stage.model, str(cfg.paths.embedding_cache), stage.model_revision)
        else:
            embedder = StubEmbedder()
        return SemanticIndex(registry, embedder)

    @lru_cache(maxsize=1)
    def get_signatures():
        """Stage 4 value signatures."""
        return SignatureLibrary.load(cfg.matching.stages.value.signatures)

    original_warnings = api._warnings

    def warnings(fixture_cdm: bool, calibrated: bool) -> list[str]:
        """The app's warnings, minus the stub notice when the real model is in use."""
        notes = original_warnings(fixture_cdm, calibrated)
        if real_model:
            notes = [n for n in notes if not n.startswith("STUB EMBEDDER")]
        notes.append(
            "DEMO SERVER: full cascade with the value stage on. A demonstration, "
            "not an evaluation; nothing here may be cited as a result."
        )
        return notes

    api.get_config = get_config
    api.get_index = get_index
    api.get_signatures = get_signatures
    api._warnings = warnings


def main() -> int:
    """Parse arguments, configure the app and start the server."""
    parser = argparse.ArgumentParser(description="Serve the ADIF demo web app")
    parser.add_argument("--stub", action="store_true", help="use the stub embedder (no model needed)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    configure(real_model=not args.stub)
    print(f"Open http://127.0.0.1:{args.port}/review")
    uvicorn.run(api.app, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())