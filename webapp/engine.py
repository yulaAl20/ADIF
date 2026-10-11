from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from eval.runner import RunContext, build_context, load_overlay
from src.analyser.profile import SchemaAnalysis, analyse_frame
from src.identity.adid import AdidError, AdidIdentifier, slugify
from src.ingestion.errors import IngestionError
from src.ingestion.loader import load_tabular
from src.matching.arbitration import MappingResult, run_cascade
from src.matching.confidence import Calibrator
from src.matching.models import NO_MAPPING, Stage
from src.templates.store import ReuseOutcome, Template, TemplateStore
from src.validation.validator import serialise_jsonld, validate_record

#: The evaluated configuration by default; ``ADIF_MATCHING_OVERLAY`` may select
#: ``config/ablation/rerank_v2.yaml`` (second design iteration, D54) for
#: demonstration. The admin page shows which one is running.
OVERLAY = os.environ.get("ADIF_MATCHING_OVERLAY", "").strip() or "config/ablation/full_cascade_value.yaml"
CALIBRATOR_PATH = Path("config/calibrator.json")
VOCABULARIES = Path("cdm/vocabularies/signatures.yaml")
ALLOWED_SUFFIXES = {".csv", ".xlsx", ".json"}


class EngineError(Exception):
    pass


@dataclass
class Engine:
    context: RunContext
    calibrator: Calibrator | None
    semantic_on: bool
    semantic_note: str
    store: TemplateStore

    @property
    def cfg(self):
        return self.context.cfg

    @property
    def fingerprint(self) -> dict:
        """What this engine actually runs (accuracy review, improvement 6)."""
        from src.config import effective_fingerprint

        name = self.context.embedder_name
        out = effective_fingerprint(self.cfg, None if name == "none" else name)
        out["overlay"] = OVERLAY
        return out

    @property
    def registry(self):
        return self.context.registry

    @property
    def field_names(self) -> list[str]:
        return list(self.registry.names())


@dataclass
class MappingSession:
    token: str
    filename: str
    company: str
    frame: pd.DataFrame
    analysis: SchemaAnalysis
    result: MappingResult
    reuse: ReuseOutcome | None = None
    template_name: str | None = None
    corrections: list[dict[str, Any]] = field(default_factory=list)
    confirmed: bool = False
    template_version: int | None = None


def _semantic_ready(cfg) -> tuple[bool, str]:
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False, "The meaning-based matching step is not installed in this version."
    cache = Path(cfg.paths.embedding_cache)
    if not cache.is_dir() or not any(cache.iterdir()):
        return False, "The language model files are not available in this version."
    return True, ""


def build_engine(allow_semantic: bool = True) -> Engine:
    cfg = load_overlay(overlay_path=OVERLAY)
    ready, note = (False, "Meaning-based matching was switched off.")
    if allow_semantic:
        ready, note = _semantic_ready(cfg)
    if not ready:
        cfg.matching.stages.semantic.enabled = False
    if cfg.unset_matching_thresholds():
        raise EngineError("The matching settings have not been set up yet.")
    try:
        context = build_context(cfg, real_model=ready)
    except Exception as exc:
        if not ready:
            raise EngineError(f"The matching engine could not start: {exc}") from exc
        cfg = load_overlay(overlay_path=OVERLAY)
        cfg.matching.stages.semantic.enabled = False
        context = build_context(cfg, real_model=False)
        ready, note = False, f"The language model could not be loaded ({exc})."
    calibrator = Calibrator.load(CALIBRATOR_PATH) if CALIBRATOR_PATH.is_file() else None
    return Engine(
        context=context,
        calibrator=calibrator,
        semantic_on=ready,
        semantic_note=note,
        store=TemplateStore(cfg.paths.template_db),
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return build_engine(True)


def _read_error(exc: Exception) -> str:
    text = str(exc)
    if isinstance(exc, pd.errors.EmptyDataError):
        return "This file has no data in it. Please check that you picked the right file and that it was saved."
    if isinstance(exc, pd.errors.ParserError):
        return (
            "This file could not be read because some rows have a different number of columns "
            f"from the header row. Details: {text}"
        )
    return f"This file could not be read. Details: {text}"


def run_mapping(
    engine: Engine,
    filename: str,
    data: bytes,
    company: str,
    template: Template | None = None,
    template_name: str | None = None,
) -> MappingSession:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise EngineError("Please upload a .csv, .xlsx or .json file.")
    if not data or not data.strip():
        raise EngineError("This file is empty. Please choose a file that contains your product data.")
    try:
        company_id = slugify(company)
    except AdidError:
        raise EngineError("Please enter a company name that contains at least one letter or number.") from None

    cfg = engine.cfg
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(data)
        try:
            loaded = load_tabular(path, cfg)
        except IngestionError as exc:
            raise EngineError(str(exc)) from exc
        except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, ValueError) as exc:
            raise EngineError(_read_error(exc)) from exc

    analysis = analyse_frame(loaded.frame, cfg)
    try:
        result = run_cascade(
            analysis,
            engine.registry,
            cfg,
            engine.context.semantic_index,
            engine.context.signature_library,
        )
    except Exception as exc:
        raise EngineError(f"The matching step stopped with an error: {exc}") from exc

    if engine.calibrator is not None:
        engine.calibrator.apply(result.records, strict=False)
        review_below = cfg.confidence.bands.review
        if review_below is not None:
            for record in result.records:
                if record.confidence is not None and record.confidence < review_below:
                    record.review_required = True

    reuse = TemplateStore.apply(template, result.records) if template is not None else None
    return MappingSession(
        token=uuid.uuid4().hex[:10],
        filename=filename,
        company=company_id,
        frame=loaded.frame,
        analysis=analysis,
        result=result,
        reuse=reuse,
        template_name=template_name,
    )


def confirm_mappings(engine: Engine, session: MappingSession, decisions: dict[str, str]) -> dict[str, Any]:
    valid = set(engine.field_names) | {NO_MAPPING}
    bad = sorted({v for v in decisions.values() if v not in valid})
    if bad:
        raise EngineError(f"These choices are not standard fields: {', '.join(bad)}")
    session.corrections = []
    for record in session.result.records:
        chosen = decisions.get(record.raw_header)
        if chosen is None:
            continue
        proposed = record.target_field
        if proposed == chosen:
            kind = "accepted"
        elif chosen == NO_MAPPING:
            kind = "rejected"
        elif proposed == NO_MAPPING:
            kind = "supplied"
        else:
            kind = "retargeted"
        session.corrections.append(
            {
                "raw_header": record.raw_header,
                "kind": kind,
                "proposed": proposed,
                "confirmed": chosen,
                "proposed_by_stage": record.deciding_stage.value,
            }
        )
        record.target_field = chosen
        record.deciding_stage = Stage.TEMPLATE
        record.raw_score = 100.0
        record.review_required = False
        record.conflict_flagged = False
        record.notes = "Confirmed by reviewer."
    template = engine.store.save(session.company, session.result.records, engine.registry.schema_sha256)
    session.confirmed = True
    session.template_version = template.version
    changed = [c for c in session.corrections if c["kind"] != "accepted"]
    total = len(session.result.records)
    return {
        "total": total,
        "kept": total - len(changed),
        "changed": len(changed),
        "by_kind": {
            k: sum(1 for c in session.corrections if c["kind"] == k)
            for k in ("accepted", "retargeted", "supplied", "rejected")
        },
        "version": template.version,
    }


def decisions_from_session(session: MappingSession) -> dict[str, str]:
    return {r.raw_header: r.target_field for r in session.result.records}


def generate_passport(engine: Engine, session: MappingSession, row: int) -> dict[str, Any]:
    if row < 0 or row >= session.analysis.row_count:
        raise EngineError("That row number is outside your file.")
    mapped = {
        r.target_field: session.frame.iloc[row, r.source_position]
        for r in session.result.records
        if r.is_mapped()
    }
    report = validate_record(mapped, engine.registry, VOCABULARIES)
    family = mapped.get("productFamily")
    if not family:
        raise EngineError(
            "No column is matched to the product family (the design or style name). "
            "Match one column to 'productFamily' in step 2, confirm, and try again."
        )
    try:
        identifier = AdidIdentifier(
            manufacturer=session.company,
            family=str(family),
            colour=str(mapped["colour"]) if mapped.get("colour") else None,
            size=str(mapped["size"]) if mapped.get("size") else None,
        )
        document = serialise_jsonld(mapped, identifier, engine.registry)
    except AdidError as exc:
        raise EngineError(str(exc)) from exc
    return {
        "id": identifier.uri(),
        "level": identifier.level,
        "valid": report.is_valid,
        "problems": report.schema_errors + report.vocabulary_errors,
        "missing": report.missing_mandatory,
        "filled": len(report.populated_fields),
        "match_rate": report.mandatory_match_rate(engine.registry),
        "document": json.loads(json.dumps(document, default=str)),
    }