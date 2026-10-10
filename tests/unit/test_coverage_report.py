"""O2 coverage figures are computed, not asserted (D12, D59)."""

from scripts.coverage_report import compute


def test_coverage_uses_twelve_annex_iii_points_and_real_field_names():
    out = compute()
    assert out["annex_iii_points"][1] == 12          # (a)-(l), corrected from 11
    assert out["uncovered_points"] == ["l"]          # acknowledged omission
    covered, total = out["core"]
    assert covered / total >= 0.80                   # O2 target, on the core set
