"""Integration tests for the REST API (M13)."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.main import app
from src.config import load_config
from tests.helpers import underived

client = TestClient(app)

CSV = b"Style_No,baseColour,SIZE,Fabric_Compostion,origin\n0012345678905,Navy,M,80% Cotton,LK\n"


def test_health_reports_build_state() -> None:
    """The real CDM now exists, so the fixture fallback must NOT be in use."""
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["using_fixture_cdm"] is False
    assert body["cdm_field_count"] > 30
    assert not any("FIXTURE CDM" in w for w in body["warnings"])


def test_fixture_fallback_warns_when_the_real_cdm_is_absent(monkeypatch) -> None:
    """The fallback still has to announce itself if the CDM ever goes missing."""
    import src.api.main as api

    api.get_registry.cache_clear()
    cfg = api.get_config()
    monkeypatch.setattr(type(cfg.paths), "model_config", type(cfg.paths).model_config)
    original = cfg.paths.cdm_schema
    object.__setattr__(cfg.paths, "cdm_schema", Path("cdm/does_not_exist.json"))
    try:
        registry, fixture = api.get_registry()
        assert fixture is True
    finally:
        object.__setattr__(cfg.paths, "cdm_schema", original)
        api.get_registry.cache_clear()


def test_openapi_docs_are_generated() -> None:
    assert client.get("/openapi.json").status_code == 200


def _serve_underived(monkeypatch):
    """Point the API at a pre-derivation config (thresholds null)."""
    import src.api.main as api

    api.get_config.cache_clear()
    monkeypatch.setattr(api, "get_config", lambda: underived(load_config("config/default.yaml")))


def test_upload_without_thresholds_returns_409_not_a_guess(monkeypatch) -> None:
    """D11 enforced at the HTTP boundary."""
    _serve_underived(monkeypatch)
    r = client.post("/upload", files={"file": ("a.csv", io.BytesIO(CSV), "text/csv")})
    assert r.status_code == 409
    assert "D11" in r.json()["detail"]


def test_nested_json_upload_is_rejected_with_a_scope_message() -> None:
    payload = b'[{"style":"A","composition":{"cotton":80}}]'
    r = client.post("/upload", files={"file": ("a.json", io.BytesIO(payload), "application/json")})
    assert r.status_code in (409, 422)


def test_unknown_upload_id_is_404() -> None:
    assert client.get("/mapping/doesnotexist").status_code == 404


def test_adid_resolution_by_depth() -> None:
    assert client.get("/adid/top-a").json()["level"] == "family"
    variant = client.get("/adid/top-a/navy_m").json()
    assert variant["level"] == "variant"
    assert variant["variant"] == "navy_m"
    instance = client.get("/adid/top-a/navy_m/sn-1").json()
    assert instance["level"] == "instance"
    assert instance["parent"].endswith("/adid/top-a/navy_m")


def test_malformed_variant_segment_is_rejected() -> None:
    r = client.get("/adid/top-a/navy")
    assert r.status_code == 400
    assert "colour" in r.json()["detail"]


def test_conformance_route_is_not_swallowed_by_the_resolver() -> None:
    """FR-11.7. Registration order matters: /adid/{family} would match
    'conformance' as a family name if declared first."""
    body = client.get("/adid/conformance").json()
    assert body["gs1_digital_link"]["compliant"] is False
    # No identifier scheme may be claimed until EN 18219:2026 has been read.
    assert body["en_18219"]["claim"] is None
    assert body["en_18219"]["standard"].startswith("EN 18219:2026")


def test_resolution_honours_ld_json_content_negotiation() -> None:
    """FR-13.12."""
    r = client.get("/adid/top-a/navy_m", headers={"accept": "application/ld+json"})
    assert r.headers["content-type"].startswith("application/ld+json")
    assert r.json()["@id"].endswith("/adid/top-a/navy_m")


def test_template_listing() -> None:
    """FR-13.9."""
    body = client.get("/templates/does-not-exist").json()
    assert body["versions"] == []
    assert body["latest_version"] is None


def test_upload_refusal_explains_how_to_run_an_exploratory_session(monkeypatch) -> None:
    """The 409 must be actionable. Before the grid search the UI is otherwise
    undemonstrable, which is when you most need to see it work."""
    _serve_underived(monkeypatch)
    r = client.post("/upload", files={"file": ("a.csv", io.BytesIO(CSV), "text/csv")})
    assert r.status_code == 409
    assert "ADIF_EXPLORATORY_THRESHOLDS" in r.json()["detail"]


def test_exploratory_session_runs_and_labels_itself(monkeypatch) -> None:
    """Supplying thresholds by environment never writes them to config and
    always marks the session exploratory (decisions.md D11)."""
    import src.api.main as api

    on_disk = load_config("config/default.yaml").matching.stages.fuzzy.threshold
    monkeypatch.setenv(api.EXPLORATORY_ENV, "fuzzy=85,semantic=70")
    api.get_config.cache_clear()
    api.get_registry.cache_clear()
    api.get_index.cache_clear()
    try:
        fresh = TestClient(api.app)
        body = fresh.get("/health").json()
        assert body["exploratory_session"] is True
        assert any("EXPLORATORY SESSION" in w for w in body["warnings"])

        up = fresh.post(
            "/upload?manufacturer_id=t",
            files={"file": ("a.csv", io.BytesIO(CSV), "text/csv")},
        )
        assert up.status_code == 200
        # config on disk is untouched
        assert load_config("config/default.yaml").matching.stages.fuzzy.threshold == on_disk
    finally:
        monkeypatch.delenv(api.EXPLORATORY_ENV, raising=False)
        api.get_config.cache_clear()
        api.get_registry.cache_clear()
        api.get_index.cache_clear()
