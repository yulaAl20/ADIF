# ADIF — Apparel DPP Interoperability Framework

Software artefact for *A Vendor-Neutral Interoperability Framework for Digital Product Passports (DPP) in the Apparel Sector: A Sri Lanka-Focused Implementation*.

Takes a messy manufacturer spreadsheet, works out which columns mean what, and emits a JSON-LD Digital Product Passport addressed by a hierarchical identifier — with a confidence score and a full audit trail for every decision.

This is an **instantiation of a research artefact, not a product**. Every module exists because it serves a research objective or produces evaluation data.

---

## Setup

Extract the zip, open a terminal **in the folder containing `README.md`**, and run one command.

**Windows** — use the batch file; it cannot be blocked by execution policy
```
setup.cmd
```

**Linux / macOS**
```bash
bash setup.sh
```

That finds Python 3.12 or 3.11, creates a virtual environment, installs dependencies, and runs the test suite (215 tests) to prove the install works. If it reports "Setup complete", you are done.

### Then — the website

```powershell
.\.venv\Scripts\Activate.ps1        # Windows
source .venv/bin/activate           # Linux / macOS

python -m scripts.seed_demo          # demo accounts + products (prints the demo password)
uvicorn src.web.app:build --factory --port 8000
```

### Hosting with an online database

Locally every store is a SQLite file under `var/`. On a host with no persistent
disk (Render's free plan wipes it on every restart), point the site at a free
PostgreSQL database instead, for example [Neon](https://neon.tech):

| Environment variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (use Neon's *direct*, not pooled, URL). Each former SQLite file becomes one schema. |
| `ADIF_DEMO_PASSWORD` | Password for the demo accounts created on first start. If unset, a random one is generated and printed in the logs. |
| `ADIF_AUTOSEED` | `0` stops the demonstration catalogue being registered into an empty database. |
| `ADIR_SECRET_KEY` | Session-cookie key, so sign-ins survive a redeploy. |
| `ADIF_PUBLIC_URL` | Optional: the site's public address, used in the QR codes. |

Start command: `uvicorn src.web.app:build --factory --host 0.0.0.0 --port $PORT`.

Open **<http://127.0.0.1:8000>**. One process serves:

| Who | Where | What |
|---|---|---|
| Anyone | `/`, `/registry`, `/how-it-works` | What an ADID is, lookup by ID / barcode / style code, search by details |
| Anyone, or a QR scan | `/adid/{family}[/{colour}_{size}[/{instance}]]` | The product page. The **same address** returns JSON or JSON-LD to machines |
| Manufacturers (signed in) | `/portal` | Upload → check matches → register; edit details (each save is a new version); versioned templates |
| Registry operator | `/admin` | Approve manufacturer accounts, create authority accounts, check frozen-artefact hashes |
| Authorities | any product page, `/portal/lot` | Also see supply-chain and production sections, and everything recorded under one lot |
| Developers | `/docs` | OpenAPI for the registry API (`X-ADIR-Key` for writes) |

Demo sign-ins after seeding: `demo@demoknit.example` (manufacturer), `officer@customs.example` (authority), `operator@adir.example` (operator). Design and justification: `docs/ADID_V2_DESIGN.md` and decisions D48–D53. The site is a demonstration of the three research contributions (ADID, CDM, gateway). It is not a legally designated DPP service, and account approval is prototype governance.

Other entry points:

```powershell
python -m scripts.check_environment  # what is installed, what is missing
python -m scripts.demo               # end-to-end matching pipeline, one command
uvicorn src.api.main:app --reload    # the original gateway JSON API + /review page
```

> **Streamlit app (legacy).** `Home.py` and `pages/` are the earlier Streamlit interface (D39). They still run (`streamlit run Home.py`) but are superseded by the website above and will be removed once the new site is deployed.

> If you prefer PowerShell, `.\setup.ps1` does the same thing. Windows blocks
> unsigned scripts extracted from a zip, so you may first need
> `Unblock-File .\setup.ps1` followed by
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.
> `setup.cmd` avoids all of that.

### If the setup script fails

Do it by hand — `docs/setup.md` has the full walkthrough and troubleshooting. The short version:

```powershell
py -3.12 -m venv .venv               # or py -3.11
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
```

No Python 3.11 or 3.12 installed? `winget install Python.Python.3.12`, then close and reopen your terminal so PATH refreshes. Avoid the Microsoft Store build — it sandboxes file paths in ways that break virtual environments confusingly.

### Optional, later — the real embedder (~2 GB)

Not needed to run anything above. Install order matters:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-optional.txt
pip freeze > requirements.lock.txt      # the lock your appendix cites
```

---

## The three layers

**Layer 1 — ADID (identity and hierarchical resolution).** Three levels, with path depth giving the level: *family* `/adid/{family}`, *variant* `/adid/{family}/{colour}_{size}`, *instance* `/adid/{family}/{colour}_{size}/{serial}`. This is the **evaluated v1.0 specification** (`adid/grammar.ebnf`, frozen). A **proposed post-freeze ADID v2** (`adid/grammar_v2.ebnf`, decisions D51–D53) keeps the same three levels and depth rule, but issues the family and instance segments as random UUIDs and freezes the variant segment at registration, for example `/adid/3f2b…8b42/white_xs/9c41…1f90`. A registry resolves every ADID to its passport. Every v2 path is also a valid v1.0 path. See **`docs/ADID_V2_DESIGN.md`**.

**Layer 2 — CDM (data).** One technology-neutral schema synthesising ESPR Annex III data elements, Annex I product parameters, GS1 EPCIS 2.0 event attributes and UNTP credential semantics. Serialised as W3C JSON-LD.

**Layer 3 — Hybrid gateway (method).** A four-stage cascade turning heterogeneous manufacturer columns into CDM fields, with a calibrated confidence per mapping.

Identity and data stay strictly separate. Material, origin and season describe an item; they do not identify *which* item, so they live in the CDM record and never in the URI. That is why a data correction can never invalidate a printed QR code.

---

## Features

### Ingestion (M1)

CSV, Excel `.xlsx`, and flat JSON. Encoding detection (UTF-8, UTF-8-BOM, Latin-1), delimiter sniffing (comma, semicolon, tab, pipe), configurable size and row caps.

**Everything is read as text.** pandas' default inference turns GTIN `0012345678905` into `12345678905` and style number `00742` into `742`, unrecoverably. Type inference happens later, over sampled strings, where a wrong guess costs a label rather than the data.

Nested JSON is rejected with a message naming the scope limitation, not a parser traceback.

### Schema analysis (M2)

Header extraction preserving raw names, deterministic first-N value sampling, datatype inference, null rate, distinct count, length and numeric ranges. Duplicate headers are suffixed and reported; empty headers are named `col_N`.

True headers are recovered before pandas mangles duplicates to `origin.1`, so duplicate handling is consistent across all three input formats.

**Header normalisation** produces three forms, because downstream stages want different things: `normalised` (space-separated, for the embedder), `compact` (for exact alias lookup), and `tokens` (for token-sort fuzzy matching). Handles camelCase, acronym boundaries (`GTINCode` → `GTIN Code`), separators, abbreviations and stopwords.

### The matching cascade (M3–M7)

A **strict fallback cascade with early exit**. A stage that accepts ends the search for that column.

| Stage | Mechanism | Catches |
|---|---|---|
| 1 — Alias | Exact match on normalised headers | `Fabric_Composition`, `fabric-composition`, `fabricComposition` |
| 2 — Fuzzy | RapidFuzz: ratio, token-sort, partial | `fabric_compostion` (typo), reordered tokens |
| 3 — Semantic | `all-MiniLM-L6-v2` sentence embeddings | `material_breakdown` — no string overlap at all |
| 4 — Value | Regex, controlled vocabulary, GTIN check digit | `col_7` full of ISO 3166 codes — header carries nothing |

Each CDM field is scored against *every* alias, not just its canonical name, so the vocabulary earns its keep.

**Conflict resolution:** when two columns claim one CDM field, the higher score keeps it and the loser is demoted to `NO_MAPPING` and flagged for review — never silently dropped.

**Calibrated confidence:** per-stage Platt scaling maps raw score onto empirical P(correct). A raw cascade score is *not* a confidence: alias hits are a constant 100, fuzzy scores are edit-distance ratios, semantic scores are rescaled cosines. Those scales are incommensurable. Confidence is learned from data so that "0.8" carries a falsifiable claim, which ECE then measures.

### Review UI (M8)

Single HTML file, vanilla JS, no build step — a research artefact needing npm and a bundler to open is one an examiner cannot run. Upload, see every mapping with its deciding stage and score, correct any of them from a dropdown, save as a template, generate a DPP.

### Templates (M9)

Confirmed mappings persist to SQLite, versioned append-only, and reapply automatically on the next upload from that manufacturer. A factory pays the review cost once, not every season.

Reuse is measured on a **drifted** upload, never an identical one: deterministic lookup cannot fail on an identical file, so a 100% score there proves nothing. Reused, drifted-missing and new columns are counted separately, because "degraded gracefully" and "silently mismatched" look identical otherwise.

### Validation (M10)

JSON Schema validation, controlled-vocabulary checks, mandatory-field coverage. **Reports rather than raises** — an SME's first upload will not be clean, and a validator that aborts on the first error tells them one thing per attempt. Every problem is collected in one pass.

Vocabularies are shared with Stage 4, so the matcher can never accept a value the validator then rejects.

### ADID registry (ADID v2, proposed post-freeze)

```bash
python -m src.registry.admin add-registrar demoknit "Demo Knit Works"   # prints an API key
uvicorn src.registry.api:build --factory --port 8100                    # resolver + registrant API
python -m eval.registry_eval --sizes 1000 10000 50000                   # E1-E8 evaluation
```

In the web app, Step 4 of the Main Tool registers every product in the file. The **Registry** page is the public lookup: search by ADID, barcode or readable name, follow relations, and download passports.

### ADID identifiers (M11) — v1.0, deprecated

```
https://dpp.{manufacturer}/adid/{family}                        → family
https://dpp.{manufacturer}/adid/{family}/{colour}_{size}        → variant
https://dpp.{manufacturer}/adid/{family}/{colour}_{size}/{sn}   → instance
```

Grammar in `adid/grammar.ebnf`. The variant is a **composite segment** so path depth alone determines level — `/adid/top-a/navy_m` cannot be confused with a family-plus-instance address. Hyphens separate within a value, underscore joins the two dimensions, so `navy-blue_xl` splits unambiguously.

The family identifier can never be derived from a GTIN. A GTIN identifies one colour-and-size combination, so using it as a family would make every variant its own family and collapse the hierarchy. The API returns 422 rather than doing this.

### JSON-LD output (M12)

The `@context` is **generated from the CDM schema**, so it cannot drift from the field set it describes. Documents carry `@id` (the ADID URI), level, family, variant, instance and parent link, alongside CDM data — the identity/data split made visible in the output.

### REST API (M13)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness **and build state** — artefact hashes, unset tunables, active warnings |
| POST | `/upload` | Ingest a file and run the cascade |
| GET | `/mapping/{id}` | Full mapping report with per-field provenance |
| POST | `/mapping/{id}/confirm` | Apply corrections, save a template |
| POST | `/dpp/{id}?row=N` | Generate a validated JSON-LD DPP |
| GET | `/adid/{family}[/{variant}[/{instance}]]` | Resolve an identifier |
| GET | `/review` | The review UI |
| GET | `/docs` | Interactive OpenAPI docs |

### Evaluation harness (M14)

Four metrics — **F1** at field-mapping level, **ESPR-mandatory field match rate**, **ECE** with reliability diagram, **template reuse rate** on drift — plus mean reciprocal rank, review burden, and per-stage runtime and memory.

The full Phase 5 workflow, in order:

```bash
# 1. Build dev schemas and their drifted variants (seeded, reproducible)
python -m scripts.perturb_schema data/dev/source.csv --level moderate --seed 42
python -m scripts.perturb_schema data/dev/source.csv --level drift --seed 42

# 2. Write a gold standard per schema, by hand, into goldstandard/<name>.json

# 3. Derive the thresholds (D11)
python -m eval.grid_search --schemas data/dev --gold goldstandard --real-model
#    → copy the derived values into config/default.yaml

# 4. Fit the confidence calibrator (D6)
python -m eval.fit_calibration --schemas data/dev --gold goldstandard --real-model

# 5. Run the ablation ladder (D10)
python -m eval.run_ablation --schemas data/heldout --gold goldstandard \
       --status EVALUATION --confidence-threshold 0.8
```

**Four refusals are built into this chain**, because each of them is a mistake that would silently invalidate results rather than announce itself:

- Steps 3 and 4 **refuse the sealed directory.** Tuning on the evaluation set is the single most damaging thing that could happen to this study.
- Steps 3 and 4 **refuse the stub embedder.** Its similarities are hash noise; a threshold derived from them looks entirely reasonable sitting in a config file. Pass `--allow-stub` only to smoke-test, and discard the output.
- Step 5 **refuses `--status EVALUATION`** unless the frozen CDM exists, thresholds are derived, and a calibrator is fitted. Everything else is stamped `EXPLORATORY`.
- The calibrator **refuses to borrow another stage's curve.** An ablation condition may use a stage the calibrator never observed; those mappings report no confidence, and the run record names the gap.

Every run writes a dated record with git commit, config hash, CDM hash, alias hash, model revision, enabled stages, per-stage cost, and the gold standard's freeze date.

### Command line

```bash
python -m src.cli inspect data/dev/manufacturer_a.csv        # profile a file
python -m src.cli map FILE --cdm ... --aliases ... --fuzzy-threshold 85
python -m scripts.demo [--file FILE] [--real-model]
python -m scripts.check_environment
python -m scripts.fetch_model                    # one-time model download
python -m scripts.build_cdm_context              # generate the JSON-LD context
python -m scripts.perturb_schema FILE --level moderate|heavy|drift --seed N
python -m scripts.make_gold_worksheet data/dev/FILE.csv    # blank ground-truth sheet
python -m scripts.build_gold_standard goldstandard/X.worksheet.csv --rater XX
```

---

## Two guarantees the code enforces

**Unset tunables fail loudly.** Every threshold and confidence band must be derived before use. An unset one raises `UnsetTunable`; the cascade refuses to run; the API returns 409. The values in the frozen `config/default.yaml` (fuzzy 85, semantic 85, value 75, review 0.9608) came from the grid search and calibration on development schemas (D25-D27).

**Held-out data stays sealed.** No code path may read `data/heldout/`. A test greps the source tree to enforce it, and the demo script refuses any path inside it. Evaluation credibility depends on that directory being genuinely untouched during development.
---
# Demonstration data

Two invented exports from a fictional knitwear manufacturer ("Demo Knit Works").
They exist to **demonstrate the app**. They are **not evaluation data** and must
never be copied into the tuning folder or the sealed held-out folder. The
evaluation harness only reads the folders it is pointed at, so keeping them here
keeps them out of every run record.

All values are invented. Barcodes pass the GTIN-13 check digit.

| File | Rows x columns | Role |
|---|---|---|
| `demo_knitwear_export_spring.csv` | 10 x 19 | First upload: review, correct, confirm, save the template |
| `demo_knitwear_export_autumn.csv` | 10 x 19 | "Season two": 4 renamed headers, 1 dropped, 1 new. Upload after confirming spring, to show template reuse |

The files were **chosen to exercise every stage**, which is what a demonstration
is for. Do not report anything measured on them as a result.

## What you should see (deterministic stages, checked)

Spring, alias / fuzzy / value stages:

- **Alias hits:** `Design_Code`, `SKU`, `EAN13`, `Colour Name`, `Size Code`, `Origin`, `Batch No`, `Buyer PO`, `Factory`.
- **Fuzzy hits:** `Fabric Compostion` (typo), `Care Instr.`, `Net Weight (kg)`.
- **Value-stage rescue:** `Col_K` (an uninformative header) is recognised as an HS commodity code from its values.
- **A conflict:** `Made In` (country names) loses to `Origin` (country codes), and is flagged for review.
- **Distractors with no CDM target:** `Unit Price (USD)`, `Warehouse Bin`, `Last Updated`, `Internal Ref` should stay unmapped.

Autumn: the renamed columns (`Barcode No`, `Shade / Tone`, `Sz`, `Fibre Mix`) no
longer match by alias, so they route through the cascade and are flagged, the
dropped `Warehouse Bin` disappears, and the new `Recycled %` column appears.

**The semantic stage depends on the real embedding model.** These notes were
checked with the semantic stage off. Run the demo with `--real-model` and read the
semantic rows for yourself; if the real model maps a distractor, that is a
finding to show, not a defect to hide.

## Run it

Command line:

    python -m scripts.demo --real-model --file demo\demo_knitwear_export_spring.csv
    python -m scripts.demo --real-model --file demo\demo_knitwear_export_autumn.csv

The web app:

    uvicorn src.api.main:app

Open http://127.0.0.1:8000/review and:

1. Upload `demo_knitwear_export_spring.csv`, with a manufacturer id such as `demoknit`.
2. Read the table: confidence, stage and "needs review" flags.
3. Change one dropdown (for example correct a distractor to no mapping), then click **Confirm mappings and save template**.
4. Click **Generate DPP for row 0**. Expect an ADID URI of the form `https://dpp.demoknit/adid/ts-1000/navy_m`, a passing validation report, mandatory match rate 1.0 and a JSON-LD document.
5. Upload `demo_knitwear_export_autumn.csv` under the same manufacturer id and show the stored template re-applying.
---

## Current research status — 2026-10-15

The prototype and its evaluation artefacts are included. The v1.0 reference
model has 54 CDM fields, a four-stage matching cascade, ADID identity, a REST
API, and a human-review workflow. The held-out run on 2026-10-10 reported
macro-F1 **0.628** for the four-stage cascade and pooled ECE **0.054**; the
accuracy and template-reuse targets were not achieved. See `runs/`,
`docs/COMPLIANCE_REGISTER.md`, and `md files/methodology.md` for denominators,
limitations, and provenance. Later ADID v2 and reranking work is post-freeze
and has not been evaluated against a new held-out set.

## Scope of the claims (read before quoting anything)

- **Contribution.** The research framework (ADID, the CDM and the hybrid gateway) is the contribution. The website is an implementation that demonstrates it.
- **Standards context.** Harmonised DPP standards EN 18216 and EN 18219 to EN 18223 were cited in the Official Journal by Implementing Decision (EU) 2026/1736 (14 July 2026). They define horizontal DPP infrastructure. The gap this study addresses is narrower: an apparel-specific schema-transformation workflow, a hierarchical product-grouping implementation, and a low-resource mapping approach designed for Sri Lankan apparel SMEs.
- **Evaluation scope (D63).** The framework is designed to address interoperability challenges relevant to Sri Lankan apparel SMEs. Its technical feasibility is evaluated using publicly available fashion product metadata and constructed manufacturer-style schemas representing heterogeneous apparel data structures. The evaluation is controlled and synthetic rather than an empirical assessment of operational Sri Lankan factories. The findings therefore demonstrate prototype feasibility and comparative matching performance, but do not establish industrial generalisability.
- **Baseline (D64).** The fuzzy-only rung is the primary computational baseline, subject to the supervisor's written approval. A deterministic alias-only baseline is prepared (`config/ablation/alias_only_baseline.yaml`) and will be run only if required.
- **CDM coverage (D59, D66).** 27/30 (90.0%) of a research-defined regulatory reference set (ESPR Annex III (a)–(l), Art 7(5), Reg. 1007/2011), and 11/12 Annex III points. This is not coverage of a legal list of mandatory apparel attributes.
- **Registry.** The SQLite registry here is a research registry and resolver. It is not the EU DPP registry under Implementing Regulation (EU) 2026/1778 and is not evidence of EU registration.
- **Mandatory fields.** The four mandatory CDM fields are a research-defined minimum. The textiles delegated act is not adopted.
- **Accuracy.** Several pre-set evaluation targets were not met (macro-F1 0.628 against 0.85; see `docs/COMPLIANCE_REGISTER.md`). A high confidence score does not guarantee a correct mapping. The workflow is human-assisted interoperability, not automatic conversion.
- **ADID v2 and the reranker** are post-freeze designs (D51, D54). Neither has been evaluated on fresh held-out data.
- **Security.** Prototype safeguards only (D61). No security assessment has been done.

**Deliberately not implemented** (project.md §2): EU DPP registry submission,
post-issuance lifecycle management, consumer scanning interfaces, non-apparel
categories, nested/hierarchical input.

**Claims that remain unverified, and are recorded as such in the code:**

- **GS1 Digital Link conformance.** Not claimed. Variant and instance records
  carry a GS1 Digital Link that passes a syntax check (`eval/registry_eval.py`),
  which is not conformance; it has never been validated against GS1's own tools.
- **EN 18219:2026 identifier scheme.** The standard permits five schemes, and
  ADID's manufacturer-domain URI is structurally an *IEC 61406 self-issued
  link* rather than a GS1 Digital Link. EN 18219 is a paid standard and has not
  been read, so `GET /adid/conformance` reports `"claim": null`.
- **Kaggle dataset licence** for Schema A.
- **ISO 3166 codes** — all 249 present, compiled from knowledge rather than from
  the ISO register. Spot-check before the freeze.

## Layout

```
config/       tunables (one file) + ablation overlays
cdm/          CDM schema, JSON-LD context, aliases, provenance, vocabularies   [FROZEN]
adid/         EBNF grammar                                                     [FROZEN]
src/          M1–M14 implementation
ui/           single-file review interface
scripts/      demo, environment check
eval/         metrics and ablation harness
data/dev/     development schemas — build and tune against these
data/heldout/ SEALED until the freeze commit
runs/         instrumented run records
tests/        116 tests, including process-discipline guards
docs/         setup guide
```

Full setup detail and troubleshooting: **`docs/setup.md`**.
