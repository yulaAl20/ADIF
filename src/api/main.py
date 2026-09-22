"""ADIF REST API (M13, FR-13.1 to FR-13.12).

Run::

    uvicorn src.api.main:app --reload

Endpoints follow the pipeline: upload a file, read its mapping report, confirm
or correct mappings, generate DPP records, then resolve them by ADID.

**Two safety properties are enforced here rather than left to the operator.**

Every response that depends on a fixture CDM or an unfitted calibrator carries
an explicit warning field. A prototype that looks production-ready while
running on six invented fields is the fastest route to a number reaching a
thesis chapter without provenance.

State is held in memory. Uploads do not survive a restart. That is correct for
an artefact whose purpose is demonstration and controlled evaluation — durable
storage would imply a deployment claim this study does not make.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from src.analyser.profile import SchemaAnalysis, analyse_frame
from src.cdm.registry import CdmRegistry
from src.config import DEFAULT_CONFIG_PATH, AdifConfig, effective_fingerprint, load_config
from src.identity.adid import AdidError, AdidIdentifier, conformance_statement
from src.ingestion.errors import IngestionError
from src.ingestion.loader import load_tabular
from src.matching.arbitration import MappingResult, run_cascade
from src.matching.models import NO_MAPPING, Stage
from src.matching.confidence import Calibrator
from src.matching.stage3_semantic import MiniLMEmbedder, SemanticIndex
from src.matching.stage4_value import SignatureLibrary
from src.provenance import capture
from src.templates.store import TemplateStore
from src.validation.validator import serialise_jsonld, validate_record

FIXTURE_SCHEMA = Path("tests/fixtures/cdm_test.schema.json")
FIXTURE_ALIASES = Path("tests/fixtures/aliases_test.yaml")
VOCABULARIES = Path("cdm/vocabularies/signatures.yaml")

app = FastAPI(
    title="ADIF — Apparel DPP Interoperability Framework",
    description=(
        "Research prototype instantiating a three-layer framework: the ADID "
        "identity model, a Canonical Data Model, and a hybrid schema "
        "interoperability gateway. Not a production service."
    ),
    version="0.1.0-dev",
)


#: Environment variable enabling an explicitly-labelled exploratory session.
#: Format: ADIF_EXPLORATORY_THRESHOLDS="fuzzy=85,semantic=70"
EXPLORATORY_ENV = "ADIF_EXPLORATORY_THRESHOLDS"


def _exploratory_thresholds() -> dict[str, float]:
    """Parse operator-supplied thresholds from the environment.

    Mirrors what the CLI already allows. Without this the review UI cannot run
    at all before the grid search, which makes the interface undemonstrable
    during exactly the phase when you most need to see it work.

    Supplying thresholds here NEVER writes them to config and ALWAYS marks the
    session exploratory, so a screenshot taken from it cannot be mistaken for an
    evaluation result (decisions.md D11).
    """
    raw = os.environ.get(EXPLORATORY_ENV, "").strip()
    if not raw:
        return {}
    parsed: dict[str, float] = {}
    for piece in raw.split(","):
        if "=" not in piece:
            continue
        stage, _, value = piece.partition("=")
        try:
            parsed[stage.strip().lower()] = float(value)
        except ValueError:
            continue
    return parsed


#: The matching configuration the API runs. Defaults to the overlay that was
#: evaluated (all four stages, strict cascade) so the API, the website and the
#: evaluation run the same thing. ``config/ablation/rerank_v2.yaml`` selects
#: the second design iteration (D54) for demonstration.
OVERLAY_ENV = "ADIF_MATCHING_OVERLAY"
DEFAULT_OVERLAY = "config/ablation/full_cascade_value.yaml"


def _semantic_available(cfg: AdifConfig) -> tuple[bool, str]:
    """Whether the real all-MiniLM-L6-v2 model can be used here."""
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False, "sentence-transformers is not installed"
    cache = Path(cfg.paths.embedding_cache)
    if not cache.is_dir() or not any(cache.iterdir()):
        return False, f"no cached model under {cache}"
    return True, ""


#: Why the semantic stage is off in this process, or "" when it is on.
SEMANTIC_OFF_REASON: dict[str, str] = {"reason": ""}


@lru_cache(maxsize=1)
def get_config() -> AdifConfig:
    """Load the evaluated configuration, applying any exploratory thresholds.

    Improvement 6 of the accuracy review: this used to load the base file
    only, which leaves the value stage OFF, and paired it with the stub
    embedder. The API therefore ran a configuration nobody evaluated. It now
    loads the same overlay as the website and the evaluation, and switches the
    semantic stage off when the real model is unavailable — never the stub.
    """
    from eval.runner import load_overlay

    overlay = os.environ.get(OVERLAY_ENV, "").strip() or DEFAULT_OVERLAY
    cfg = load_overlay(DEFAULT_CONFIG_PATH, overlay)
    SEMANTIC_OFF_REASON["reason"] = ""
    ok, why = _semantic_available(cfg)
    if cfg.matching.stages.semantic.enabled and not ok:
        cfg.matching.stages.semantic.enabled = False
        SEMANTIC_OFF_REASON["reason"] = why
    for stage, value in _exploratory_thresholds().items():
        if stage in {"fuzzy", "semantic", "value"}:
            setattr(getattr(cfg.matching.stages, stage), "threshold", value)
    return cfg


@lru_cache(maxsize=1)
def get_registry() -> tuple[CdmRegistry, bool]:
    """Load the real CDM, falling back to the fixture.

    Returns:
        The registry and whether the fixture was used. Callers must surface
        that flag: a fixture-backed response is a demonstration, not a result.
    """
    cfg = get_config()
    if Path(cfg.paths.cdm_schema).is_file() and Path(cfg.paths.alias_vocabulary).is_file():
        return (
            CdmRegistry.load(
                cfg.paths.cdm_schema, cfg.paths.alias_vocabulary, cfg.normalisation
            ),
            False,
        )
    return CdmRegistry.load(FIXTURE_SCHEMA, FIXTURE_ALIASES, cfg.normalisation), True


@lru_cache(maxsize=1)
def get_index() -> SemanticIndex | None:
    """Build the semantic index once with the real model, or return None.

    None means the semantic stage is off (see :func:`get_config`). The stub
    embedder is never used here: hash-derived similarity is noise, and a
    demonstration that contains it is not the system that was evaluated.
    """
    cfg = get_config()
    if not cfg.matching.stages.semantic.enabled:
        return None
    registry, _ = get_registry()
    sem = cfg.matching.stages.semantic
    return SemanticIndex(
        registry, MiniLMEmbedder(sem.model, str(cfg.paths.embedding_cache), sem.model_revision)
    )


def matching_configuration() -> dict[str, Any]:
    """What this process actually runs: decision rule, stages, model, hash."""
    cfg = get_config()
    index = get_index()
    out = effective_fingerprint(cfg, index.embedder.name if index else None)
    out["overlay"] = os.environ.get(OVERLAY_ENV, "").strip() or DEFAULT_OVERLAY
    if SEMANTIC_OFF_REASON["reason"]:
        out["semantic_off_reason"] = SEMANTIC_OFF_REASON["reason"]
    return out


@lru_cache(maxsize=4)
def _signature_library(path: str) -> SignatureLibrary:
    return SignatureLibrary.load(path)


def get_signatures() -> SignatureLibrary | None:
    """The value-signature library when Stage 4 is enabled in the *current* config.

    Not cached on its own: whether Stage 4 runs is a property of the config,
    and a cached ``None`` from one config must not leak into another.
    """
    cfg = get_config()
    if not cfg.matching.stages.value.enabled:
        return None
    return _signature_library(str(cfg.matching.stages.value.signatures))


@lru_cache(maxsize=1)
def get_calibrator() -> Calibrator | None:
    """Load a fitted calibrator if one exists. None means no confidence is
    reported at all — raw scores are never substituted (D6)."""
    path = Path("config/calibrator.json")
    return Calibrator.load(path) if path.is_file() else None


@lru_cache(maxsize=1)
def get_store() -> TemplateStore:
    """Open the SQLite template store once per process."""
    return TemplateStore(get_config().paths.template_db)


@dataclass
class Session:
    """One uploaded file and everything derived from it."""

    upload_id: str
    filename: str
    manufacturer_id: str
    frame: pd.DataFrame
    analysis: SchemaAnalysis
    result: MappingResult
    warnings: list[str] = field(default_factory=list)
    #: FR-8.8 — every reviewer edit, for the "manual effort" evaluation metric
    #: (project.md §12). Counted per kind because they are not equivalent work:
    #: accepting a proposal costs a glance, retargeting it costs a decision.
    corrections: list[dict[str, Any]] = field(default_factory=list)


SESSIONS: dict[str, Session] = {}


def _warnings(fixture_cdm: bool, calibrated: bool) -> list[str]:
    notes = []
    if _exploratory_thresholds():
        notes.append(
            "EXPLORATORY SESSION: thresholds were supplied via "
            f"{EXPLORATORY_ENV}, not derived by grid search (decisions.md D11). "
            "Nothing from this session may be cited as a result."
        )
    if fixture_cdm:
        notes.append(
            "FIXTURE CDM: running against six invented test fields, not the "
            "canonical data model. Output is a demonstration, not a result."
        )
    if SEMANTIC_OFF_REASON["reason"]:
        notes.append(
            "SEMANTIC STAGE OFF: all-MiniLM-L6-v2 is not available here "
            f"({SEMANTIC_OFF_REASON['reason']}). Mappings come from alias, fuzzy "
            "and value matching only; the four-stage evaluation figures do not "
            "describe this session."
        )
    if get_config().matching.arbitration == "rerank":
        notes.append(
            "SECOND DESIGN ITERATION: decisions use evidence-aware reranking "
            "(D54), developed on development data and not yet evaluated on "
            "held-out data. The confidence calibrator was fitted on v1 cascade "
            "decisions."
        )
    if not calibrated:
        notes.append(
            "UNCALIBRATED: no confidence values are reported. Raw cascade "
            "scores are not confidence (decisions.md D6)."
        )
    return notes


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    exploratory_session: bool
    offline_mode: bool
    using_fixture_cdm: bool
    cdm_field_count: int
    calibrator_fitted: bool
    active_sessions: int
    warnings: list[str]
    provenance: dict[str, Any]
    matching_configuration: dict[str, Any]


@app.get("/health", tags=["service"])
def health() -> HealthResponse:
    """Service liveness plus build state (FR-13.10, FR-13.11)."""
    cfg = get_config()
    registry, fixture = get_registry()
    return HealthResponse(
        status="ok",
        exploratory_session=bool(_exploratory_thresholds()),
        offline_mode=cfg.runtime.offline,
        using_fixture_cdm=fixture,
        cdm_field_count=len(registry.fields),
        calibrator_fitted=get_calibrator() is not None,
        active_sessions=len(SESSIONS),
        warnings=_warnings(fixture, calibrated=get_calibrator() is not None),
        provenance=capture(cfg).model_dump(),
        matching_configuration=matching_configuration(),
    )


@app.post("/upload", tags=["gateway"])
async def upload(file: UploadFile, manufacturer_id: str = "unknown") -> dict[str, Any]:
    """Ingest a manufacturer file and run the cascade (FR-13.1).

    Thresholds must be set in config before this succeeds; an unset threshold
    returns 409 rather than a guess (D11).
    """
    cfg = get_config()
    registry, fixture = get_registry()
    suffix = Path(file.filename or "upload.csv").suffix or ".csv"
    store_dir = Path(cfg.paths.upload_store)
    store_dir.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4().hex[:12]
    path = store_dir / f"{upload_id}{suffix}"
    path.write_bytes(await file.read())

    try:
        loaded = load_tabular(path, cfg)
    except IngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    analysis = analyse_frame(loaded.frame, cfg)
    try:
        result = run_cascade(
            analysis, registry, cfg, get_index(), get_signatures()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{exc}\n\nTo click through the interface before the grid "
                f"search has run, start the server with explicitly-supplied "
                f"thresholds — the session is then labelled exploratory and "
                f"nothing from it can be cited:\n"
                f'  Windows:  set {EXPLORATORY_ENV}=fuzzy=85,semantic=70\n'
                f'  Linux:    export {EXPLORATORY_ENV}=fuzzy=85,semantic=70\n'
                f"then  uvicorn src.api.main:app --reload"
            ),
        ) from exc

    if (calibrator := get_calibrator()) is not None:
        calibrator.apply(result.records)
        # Review rule: below the derived confidence, a human decides.
        review_below = cfg.confidence.bands.review
        if review_below is not None:
            for record in result.records:
                if record.confidence is not None and record.confidence < review_below:
                    record.review_required = True

    SESSIONS[upload_id] = Session(
        upload_id=upload_id,
        filename=file.filename or path.name,
        manufacturer_id=manufacturer_id,
        frame=loaded.frame,
        analysis=analysis,
        result=result,
        warnings=_warnings(fixture, calibrated=get_calibrator() is not None),
    )
    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "manufacturer_id": manufacturer_id,
        "format": loaded.source_format,
        "encoding": loaded.encoding,
        "delimiter": loaded.delimiter,
        "rows": analysis.row_count,
        "columns": analysis.column_count,
        "warnings": SESSIONS[upload_id].warnings,
    }


def _session(upload_id: str) -> Session:
    session = SESSIONS.get(upload_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No upload '{upload_id}'.")
    return session


@app.get("/mapping/{upload_id}", tags=["gateway"])
def mapping_report(upload_id: str) -> dict[str, Any]:
    """Full mapping report with per-field provenance (FR-13.2, FR-8.1-8.5)."""
    session = _session(upload_id)
    registry, _ = get_registry()
    return {
        "upload_id": upload_id,
        "manufacturer_id": session.manufacturer_id,
        "records": [r.model_dump(mode="json") for r in session.result.records],
        "stage_hits": session.result.stage_hits,
        "stage_fallthroughs": session.result.stage_fallthroughs,
        "unmapped_columns": session.result.unmapped_columns(),
        "unpopulated_mandatory": session.result.unpopulated_mandatory(registry),
        "review_required_count": sum(
            1 for r in session.result.records if r.review_required
        ),
        "cdm_fields": registry.names(),
        "warnings": session.warnings,
    }


class Correction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_header: str
    cdm_field: str


@app.post("/mapping/{upload_id}/confirm", tags=["gateway"])
def confirm(upload_id: str, corrections: list[Correction]) -> dict[str, Any]:
    """Apply reviewer corrections and store a template (FR-8.2, FR-9.1).

    A correction is recorded as :class:`Stage.TEMPLATE` at full score, because
    a human decided it. Their judgement is not a match score.
    """
    session = _session(upload_id)
    registry, _ = get_registry()
    valid = set(registry.names()) | {NO_MAPPING}
    applied: list[str] = []

    for correction in corrections:
        if correction.cdm_field not in valid:
            raise HTTPException(
                status_code=422,
                detail=f"'{correction.cdm_field}' is not a CDM field.",
            )
        for record in session.result.records:
            if record.raw_header != correction.raw_header:
                continue
            proposed = record.target_field
            if proposed == correction.cdm_field:
                kind = "accepted"       # reviewer agreed with the proposal
            elif correction.cdm_field == NO_MAPPING:
                kind = "rejected"       # reviewer removed a wrong proposal
            elif proposed == NO_MAPPING:
                kind = "supplied"       # reviewer mapped what the cascade missed
            else:
                kind = "retargeted"     # reviewer moved it to a different field
            session.corrections.append({
                "raw_header": correction.raw_header,
                "kind": kind,
                "proposed": proposed,
                "confirmed": correction.cdm_field,
                "proposed_by_stage": record.deciding_stage.value,
            })
            record.target_field = correction.cdm_field
            record.deciding_stage = Stage.TEMPLATE
            record.raw_score = 100.0
            record.review_required = False
            record.conflict_flagged = False
            record.notes = "Confirmed by reviewer."
            applied.append(correction.raw_header)

    template = get_store().save(
        session.manufacturer_id, session.result.records, registry.schema_sha256
    )
    edits = [c for c in session.corrections if c["kind"] != "accepted"]
    return {
        "applied": applied,
        "template_version": template.version,
        "template_entries": len(template.mappings),
        # FR-8.8 / §12 "manual corrections required" metric. 'accepted' rows are
        # excluded from the effort count: agreeing with a correct proposal is not
        # a correction, and counting it would understate the system's accuracy.
        "corrections_total": len(edits),
        "corrections_by_kind": {
            k: sum(1 for c in session.corrections if c["kind"] == k)
            for k in ("accepted", "retargeted", "supplied", "rejected")
        },
        "manual_effort_rate": round(len(edits) / len(session.result.records), 4)
        if session.result.records else 0.0,
        "corrections": session.corrections,
    }


@app.post("/dpp/{upload_id}", tags=["dpp"])
def generate(upload_id: str, row: int = 0) -> dict[str, Any]:
    """Build a validated JSON-LD DPP record for one row (FR-13.3, FR-12.1)."""
    session = _session(upload_id)
    registry, fixture = get_registry()
    if row >= session.analysis.row_count:
        raise HTTPException(status_code=404, detail=f"Row {row} out of range.")

    mapped = {
        r.target_field: session.frame.iloc[row, r.source_position]
        for r in session.result.records
        if r.is_mapped()
    }
    report = validate_record(mapped, registry, VOCABULARIES)

    # The family identifier must come from a family-level field. It must NEVER
    # fall back to productIdentifier: a GTIN identifies one colour-and-size
    # combination, so using it as a family would make every variant its own
    # family and collapse the hierarchy ADID exists to provide (decisions.md D9).
    family = mapped.get("productFamily")
    if not family:
        raise HTTPException(
            status_code=422,
            detail=(
                "No family-level identifier was mapped. ADID requires a product "
                "family distinct from the variant GTIN — a GTIN identifies one "
                "colour-and-size combination and cannot represent a design "
                "(decisions.md D9). Map a style or design column to a "
                "family-level CDM field, then retry."
            ),
        )
    try:
        identifier = AdidIdentifier(
            manufacturer=session.manufacturer_id,
            family=str(family),
            colour=str(mapped["colour"]) if mapped.get("colour") else None,
            size=str(mapped["size"]) if mapped.get("size") else None,
        )
    except AdidError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "adid": identifier.uri(),
        "level": identifier.level,
        "validation": report.as_dict(),
        "mandatory_match_rate": report.mandatory_match_rate(registry),
        "document": serialise_jsonld(mapped, identifier, registry),
        "warnings": _warnings(fixture, calibrated=get_calibrator() is not None),
    }


# Declared before /adid/{family}: FastAPI matches in registration order, so a
# literal segment must come first or the path parameter swallows it.
@app.get("/adid/conformance", tags=["adid"])
def adid_conformance() -> dict[str, Any]:
    """Machine-readable statement of what ADID claims and does not (FR-11.7)."""
    return conformance_statement()


@app.get("/adid/{family}", tags=["adid"], deprecated=True)
@app.get("/adid/{family}/{variant}", tags=["adid"], deprecated=True)
@app.get("/adid/{family}/{variant}/{instance}", tags=["adid"], deprecated=True)
def resolve(
    request: Request,
    family: str,
    variant: str | None = None,
    instance: str | None = None,
) -> JSONResponse:
    """Resolve an ADID at family, variant or instance level (FR-13.6-13.8).

    Path depth alone determines the level, which is exactly what the composite
    variant segment buys: ``/adid/top-a/navy_m`` cannot be confused with a
    family-plus-instance address.
    """
    path = "/adid/" + "/".join(p for p in (family, variant, instance) if p)
    try:
        identifier = AdidIdentifier.parse(path)
    except AdidError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    parent = identifier.parent()
    # FR-13.12: serve application/ld+json when the client asks for it. A DPP
    # resolver that only ever returns application/json is not participating in
    # the linked-data ecosystem the regulation's interoperability requirement
    # (Art. 10(1)(d)) describes.
    wants_ld = "application/ld+json" in (request.headers.get("accept") or "")
    body = {
        "adid": identifier.uri(),
        "level": identifier.level,
        "family": identifier.family,
        "variant": identifier.variant_key,
        "instance": identifier.serial,
        "parent": parent.uri() if parent else None,
        "note": (
            "DEPRECATED v1.0 path ADID: returns identifier structure only. "
            "ADID v2 (proposed post-freeze, decisions.md D51) issues paths such as "
            "/adid/{familyUUID}/{colour}_{size}; the v1.0 readable path survives "
            "there as a readable alias at /alias/{registrar}/{family}/{variant}."
        ),
    }
    if wants_ld:
        body["@context"] = {"adid": "https://adif.example/ns/adid#"}
        body["@id"] = identifier.uri()
    return JSONResponse(
        content=body,
        media_type="application/ld+json" if wants_ld else "application/json",
    )


@lru_cache(maxsize=1)
def get_registry_node():
    """The ADID registry node configured in config/registry.yaml (ADID v2, D51)."""
    from src.registry.api import node_from_config
    return node_from_config()


@app.get("/rows/{upload_id}", tags=["registry"])
def cdm_rows(upload_id: str) -> dict[str, Any]:
    """The upload as CDM-shaped rows — the payload the registry API's POST /registrations accepts."""
    from src.registry.registration import rows_from_mapping
    session = _session(upload_id)
    return {"upload_id": upload_id,
            "rows": rows_from_mapping(session.frame, session.result.records)}


@app.post("/register/{upload_id}", tags=["registry"])
def register_upload(upload_id: str, x_adir_key: str | None = Header(default=None)) -> dict[str, Any]:
    """Register every row of a reviewed upload in the local ADID registry node.

    Replaces v1.0's path-encoded ADID with registry-issued UUIDs (D41): models,
    variants, batches and instances, linked by relations, each resolvable at
    the registry API at their ADID v2 paths.
    """
    from src.registry.policy import Role
    from src.registry.registration import register_rows, rows_from_mapping
    session = _session(upload_id)
    node = get_registry_node()
    principal = node.store.authenticate(x_adir_key)
    if principal.role not in (Role.REGISTRANT, Role.OPERATOR):
        raise HTTPException(401, "An ADIR registrant key (X-ADIR-Key) is required.")
    registry, _ = get_registry()
    report = register_rows(
        node, rows_from_mapping(session.frame, session.result.records),
        principal.registrar_id or session.manufacturer_id, registry.schema,
    )
    return {**report.as_dict(), "resolver": node.resolver,
            "warnings": session.warnings}


@app.get("/templates/{manufacturer_id}", tags=["gateway"])
def list_templates(manufacturer_id: str) -> dict[str, Any]:
    """List stored template versions for a manufacturer (FR-13.9)."""
    store = get_store()
    versions = store.versions(manufacturer_id)
    latest = store.latest(manufacturer_id)
    return {
        "manufacturer_id": manufacturer_id,
        "versions": versions,
        "latest_version": latest.version if latest else None,
        "latest_created_at": latest.created_at if latest else None,
        "latest_entry_count": len(latest.mappings) if latest else 0,
        "latest_cdm_sha256": latest.cdm_sha256 if latest else None,
    }


@app.get("/review", response_class=HTMLResponse, include_in_schema=False)
def review_ui() -> str:
    """Serve the single-file review interface (M8)."""
    page = Path("ui/review.html")
    if not page.is_file():
        raise HTTPException(status_code=404, detail="ui/review.html not found.")
    return page.read_text(encoding="utf-8")
