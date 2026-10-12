# Quickstart — install, run, and produce results

Fresh machine to Chapter 5 numbers. Windows commands; Linux/macOS equivalents in
`docs/setup.md`.

---

## PART 1 — Install (5 minutes)

### 1.1 Extract

Extract the zip so you get a folder containing `README.md`, `requirements.txt`
and `src\`. Open PowerShell **in that folder** and confirm with `dir`.

> ### ⚠ If you are replacing an existing copy
>
> `config\default.yaml` in this zip has `model_revision: null`. **Yours is
> pinned.** Copy your hash out before overwriting `config\`, and paste it back
> after. Check it with:
> ```powershell
> python -c "from src.config import load_config; print(load_config('config/default.yaml').matching.stages.semantic.model_revision)"
> ```
> `None` means it was lost. An unpinned model is an unreproducible result.

### 1.2 Set up

```powershell
setup.cmd
```

Finds Python 3.12 or 3.11, creates `.venv`, installs dependencies, runs the
tests. **Expect `118 passed`.**

Use `setup.cmd`, not `setup.ps1` — PowerShell refuses unsigned scripts from a
downloaded zip, and batch files are not subject to that rule.

If it cannot find Python: `winget install Python.Python.3.12`, then close and
reopen PowerShell so PATH refreshes.

### 1.3 Activate

```powershell
.\.venv\Scripts\activate.bat
```

Your prompt should show `(.venv)`. Every command below assumes it is active.

### 1.4 Optional — the real embedder (~2 GB)

Needed for the grid search in Part 3. Install order matters:

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-optional.txt
python -m scripts.fetch_model
```

Paste the printed revision hash into `config\default.yaml` under
`matching.stages.semantic.model_revision`.

---

## PART 2 — Run it (5 minutes, no ground truth needed)

Full detail in `docs/verify_it_works.md`.

```powershell
python -m scripts.check_environment
```
All four frozen artefacts `OK`, 54 CDM fields, 6 gold standards.

```powershell
python -m src.cli inspect data\dev\manufacturer_b_erpnext.csv
```
22 columns profiled — types, null rates, normalised headers. Exercises M1, M2.

```powershell
python -m src.cli map data\dev\manufacturer_b_erpnext.csv ^
  --cdm cdm\cdm_v1.0.schema.json --aliases cdm\aliases_v1.0.yaml ^
  --fuzzy-threshold 85 --no-semantic
```
The cascade on real data. `item_code → productIdentifier` (alias, 100.0),
`recycled_pct → recycledContent` (fuzzy, 85.7). An `EXPLORATORY RUN` banner,
because CLI-supplied thresholds are not derived thresholds.

### The web interface

```powershell
set ADIF_EXPLORATORY_THRESHOLDS=fuzzy=85,semantic=70
uvicorn src.api.main:app --reload
```

| URL | What you see |
|---|---|
| <http://127.0.0.1:8000/review> | Upload a file, correct mappings, generate a DPP |
| <http://127.0.0.1:8000/docs> | Every endpoint, generated from the code |
| <http://127.0.0.1:8000/health> | Artefact hashes, 54 CDM fields, session state |

In the UI: upload `data\dev\manufacturer_b_erpnext.csv`, change a dropdown,
**Confirm mappings**, then **Generate DPP for row 0** → an ADID URI, validation
report and JSON-LD.

**Use Schema A or B for demonstration screenshots.** Schema C returns 422 — it
has no family-level identifier, so no ADID can be constructed. That is a
finding, not a bug (see `goldstandard/REVIEW_2026-10-08.md`).

Everything in Part 2 is Phase 5a Demonstration material. **Screenshot it now** —
it is independent of the evaluation and you can write that chapter today.

---

## PART 3 — Produce results

### 3.1 Git, with a real history

```powershell
python -m scripts.init_repo --dry-run
python -m scripts.init_repo --name "G.D.Y.D. Alwis" --email "your@email"
```

18 commits in project.md §9's increment order, so `git log` reads as a
development narrative — Chapter 4 material. The rulebook is committed *before*
the ground truth written against it, deliberately: §11 makes that ordering the
evidence that the rulebook governed the decisions.

All timestamps are real. The script has no date option, because
`src/provenance.py` stamps commit hashes into every run record and your gold
standards carry `frozen_at: 2026-10-08`. Invented dates would contradict data
already inside the artefact.

### 3.2 Derive the thresholds

```powershell
python -m eval.grid_search --schemas data\dev --gold goldstandard --real-model
```

Prints the best macro-F1, writes `config\thresholds.yaml`. **Copy the two values
by hand into `config\default.yaml`**, replacing `null`, with a dated comment.
Then record them in methodology.md's Results section — D11 requires it.

Refusals and what they mean:

| Message | Fix |
|---|---|
| `REFUSED: ... sealed evaluation directory` | You pointed it at `data\heldout`. Use `data\dev`. |
| `REFUSED: ... stub embedder` | Add `--real-model`, or the model cache is missing. |
| `No gold standard for X` | A worksheet is unconverted. |

### 3.3 Fit the calibrator

```powershell
python -m eval.fit_calibration --schemas data\dev --gold goldstandard --real-model
```

Writes `config\calibrator.json`, fitted across all four ablation conditions so
every stage has observations. If it warns about fewer than 30 observations for a
stage, **report that stage's confidence curve with the caveat.**

The in-sample ECE it prints is **not** Metric 3.

### 3.4 Freeze

```powershell
python -m scripts.freeze --check
python -m scripts.freeze --tag freeze-v1.0
```

`--check` refuses unless every artefact exists, thresholds are derived, a
calibrator is fitted, gold standards exist, the tree is clean, **and
`data\heldout\` is still empty**. That last condition cannot be recovered once
lost.

Paste `decisions_freeze_record.json` into decisions.md with the tag and date.

### 3.5 Held-out schemas, then their ground truth

Only now unzip `heldout_package.zip` into `data\heldout\`. Read its README.
Then write those two gold standards — 46 rows, same process as
`goldstandard/HOWTO.md`.

### 3.6 Run the evaluation

```powershell
python -m eval.run_ablation --schemas data\heldout --gold goldstandard ^
  --status EVALUATION --confidence-threshold 0.8
```

Minutes. Writes a dated run record with all four metrics, the ΔF1 ladder and
full provenance. **`--status EVALUATION` is refused** unless the frozen CDM
exists, thresholds are derived and a calibrator is fitted.

That run record is Chapter 5.

### 3.7 Second rater

```powershell
python -m scripts.second_rater sample data\dev\manufacturer_b_erpnext.csv --fraction 0.25
```

Give them the blank worksheet, `RULEBOOK.md` and the CDM field list — nothing
else. Then:

```powershell
python -m scripts.second_rater agree goldstandard\manufacturer_b_erpnext.json ^
  goldstandard\manufacturer_b_erpnext.rater2.worksheet.csv
```

**Book them now** — it is the only task on someone else's calendar.

---

## Where you are

| Done | Outstanding |
|---|---|
| 14 modules, 119 tests | Thresholds (3.2) |
| CDM v1.0, 54 fields, clause provenance | Calibrator (3.3) |
| 253-key alias vocabulary | Git history (3.1) |
| Six dev gold standards, 99 columns | Freeze tag (3.4) |
| Model cached and pinned | Held-out ground truth (3.5) |
| Review UI, REST API, CLI | The ablation run (3.6) |
| Evaluation harness | Second-rater agreement (3.7) |

Steps 3.1 to 3.4 are about twenty minutes of commands plus one hand-edit.
