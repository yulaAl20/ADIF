# Verifying the software works — before any ground truth exists

Nothing here needs a gold standard. Run top to bottom; takes about five minutes.
Each step is something you can screenshot for Chapter 4's demonstration section.

---

## 1. Tests

```powershell
pytest
```

**Expect:** `118 passed`. Some of these are process guards rather than
behaviour tests — the offline test, the held-out seal grep, the refusal to run
on underived thresholds — so a pass here is also evidence for §14's Definition
of Done #1 and #2.

## 2. Build state

```powershell
python -m scripts.check_environment
```

**Expect:** all four frozen artefacts `OK`, 54 CDM fields, and
`gold standards MISSING` with your worksheet count. The last line is the
honest statement of where the project is.

## 3. Profile a real manufacturer file

```powershell
python -m src.cli inspect data\dev\manufacturer_b_erpnext.csv
```

**Expect:** 22 columns with inferred types, null rates, distinct counts and
normalised headers. This exercises M1 and M2 and needs no CDM and no
thresholds — ingestion and analysis are genuinely independent of the matcher.

## 4. Run the full cascade on real data

```powershell
python -m src.cli map data\dev\manufacturer_b_erpnext.csv ^
  --cdm cdm\cdm_v1.0.schema.json --aliases cdm\aliases_v1.0.yaml ^
  --fuzzy-threshold 85 --no-semantic
```

**Expect:** an `EXPLORATORY RUN` banner, then a per-column table —
`item_code → productIdentifier (alias, 100.0)`,
`recycled_pct → recycledContent (fuzzy, 85.7)`, and nine columns left
`NO_MAPPING`. Stage hit counts and a run record written to `runs/`.

This is the artefact doing its actual job. **The banner is not decoration** —
thresholds supplied on the command line are not derived thresholds, and nothing
from this run may be cited.

Add `--embedder minilm` to exercise the real semantic stage now that the model
is cached.

## 5. The review interface

The API refuses to run on underived thresholds, so start it in an
explicitly-labelled exploratory session:

```powershell
set ADIF_EXPLORATORY_THRESHOLDS=fuzzy=85,semantic=70
uvicorn src.api.main:app --reload
```

(Linux/macOS: `export ADIF_EXPLORATORY_THRESHOLDS=fuzzy=85,semantic=70`)

Then open:

| URL | What to check |
|---|---|
| <http://127.0.0.1:8000/health> | `exploratory_session: true`, 54 CDM fields, every artefact hash |
| <http://127.0.0.1:8000/review> | Upload `data\dev\manufacturer_b_erpnext.csv` |
| <http://127.0.0.1:8000/docs> | Every endpoint, auto-generated from the code |

In the review UI: upload the file, read the mapping table, change a dropdown,
click **Confirm mappings and save template**, then **Generate DPP for row 0**.
You should get an ADID URI, a validation report, a mandatory-field match rate,
and a JSON-LD document.

The yellow banner stating this is a demonstration appears on every response.
**Supplying thresholds this way never writes them to config** — there is a test
asserting that.

## 6. ADID resolution and conformance

```powershell
curl http://127.0.0.1:8000/adid/top-a/navy_m
curl http://127.0.0.1:8000/adid/conformance
```

**Expect:** the first resolves to `level: variant` with a parent link; the
second returns the machine-readable statement, including
`gs1_digital_link.compliant: false` and the EN 18219 candidate scheme with
`claim: null`.

## 7. Template reuse

Upload `manufacturer_b_erpnext.csv`, confirm the mappings, then upload
`manufacturer_b_erpnext_drift.csv` — the same schema with four renamed columns
and one dropped. The stored template should reapply to the unchanged columns
while the renamed ones route through the cascade and get flagged.

That is Metric 4's mechanism. **Measuring** it needs a gold standard; watching
it work does not.

---

## What you cannot check yet, and why

| Not checkable | Needs |
|---|---|
| F1 / precision / recall | A gold standard — there is nothing to compare output against |
| Mandatory-field match rate | A gold standard |
| ECE and the reliability diagram | A fitted calibrator, which needs a gold standard |
| Template reuse *rate* | A gold standard for the drift variants |
| The ablation ΔF1 ladder | All of the above |

Every one of these is a **comparison against ground truth**. The software
produces the output; the gold standard supplies the answer key. Without it
there is no number to compute — which is why the harness refuses rather than
inventing one.
