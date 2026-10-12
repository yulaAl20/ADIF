# methodology.md — the chapter that writes itself
**Last updated:** 2026-10-11
**Supersedes:** the 2026-10-08 revision. Changes are listed in §0 so you can see what moved and why, rather than diffing two long documents.

---

## 0. What changed since 2026-08-06, and why

| # | Change | Driver |
|---|---|---|
| 1 | Phase 4 status: *Not started* → **complete** (14 modules, automated test suite) | The prototype exists |
| 2 | **ESPR Annex I → Annex III** wherever DPP *data elements* are meant | Annex III is the DPP annex (Art. 9(2)(a) refers data content "pursuant to Annex III"); Annex I is the product-parameters list. Verified against the consolidated text — see sources.md |
| 3 | Schema inventory: 3 evaluation schemas → **3 development + 3 held-out** | decisions.md **D23** — the ERPNext and Odoo schemas were contaminated during value-signature work and were reassigned to development |
| 4 | ADID URI shape corrected to a **composite variant segment** | `/adid/{family}/{colour}/{size}` and project.md's `/adid/{family}/{variant}/{instance}` were ambiguous at depth 3. Resolved in `adid/grammar.ebnf` |
| 5 | ADID conformance target is **open, and now points at IEC 61406 rather than GS1 Digital Link** | EN 18219:2026 permits five identifier schemes; ADID issues a self-issued link under the manufacturer's own domain |
| 6 | Metric 2 denominator **restricted to mandatory fields the gold standard maps**, plus a reported *coverage ceiling* | The prose already said "restricted to fields the source schema actually has data for"; the code did not. Code and prose now agree |
| 7 | Ablation ladder: 3 conditions → **4**, plus one supplementary condition | decisions.md **D19** (value stage) and **D20** (resolved) |
| 8 | Ground-truth rulebook: "exists in draft" → **compiled as `goldstandard/RULEBOOK.md` v1.0**, committed before any ground truth was written | project.md §11 |
| 9 | CDM figures stated concretely: **54 fields, 4 mandatory**, clause-level provenance for every field | The CDM was built |
| 10 | Layer 3 described as **four** stages under a strict cascade | decisions.md **D17**, **D19** |
| 11 | Phase 5b Evaluation: *Blocked* → **complete** (run 2026-10-10, commit `ef89aa7`) | decisions.md **D25–D34** |
| 12 | Held-out set built: H1 Kaggle (10 columns), H2 Dolibarr-style (26), H3 buyer tech-pack (23); drift variants for **H2 and H3 only** | decisions.md **D31, D32** |
| 13 | D20, D21, D22 resolved (D21 by default, logged after the run) | decisions.md |
| 14 | Thresholds and review band derived and frozen: **85 / 85 / 75** and **0.9608** | decisions.md **D25, D27** |
| 15 | Second-rater agreement obtained: **17 of 17** | decisions.md **D33** |
| 16 | A Streamlit interface and a software-artefact evaluation plan were added; the user study is an **open decision** | decisions.md **D38, D39** |

Results (§5) now contain the development runs and the held-out evaluation. Every number there was measured and comes from a named run record.

---

## 1. Research paradigm

Design Science Research. **Hevner et al. (2004)** for rigour (seven guidelines — full compliance table in Ch3). **Peffers et al. (2007)** DSRM for the six-phase process. Evaluation strategy: **FEDS** (Venable, Pries-Heje & Baskerville, 2016) — this study's evaluation is ex-post, summative and **artificial** (controlled schemas, not a live factory deployment). A naturalistic evaluation — practitioner review by Sri Lankan apparel exporters — remains future work and a stated limitation, not something claimed here.

Contribution type: **exaptation** (Gregor & Hevner, 2013) — established schema-matching techniques extended into the DPP compliance domain. The novelty claimed is the apparel DPP alias vocabulary, the calibrated confidence model, the template/drift mechanism and the offline SME-context packaging. **Not** the matching cascade itself.

### A claim this revision can now make, and should
The artefact was specified and built before CEN/CENELEC JTC 24 published six DPP standards on 27 May 2026, and it lands in the same architectural space as EN 18223 (shared data model container) and EN 18216 (REST over HTTPS). Independent convergence on a published standard is a **convergent-validity argument** for the design, and belongs in Ch5/Ch6 rather than being left for an examiner to notice. See sources.md and §6 below for what this does to research gap #6.

---

## 2. Six phases — status

| # | Phase (Peffers, 2007) | Activity in this study | Status | Notes |
|---|---|---|---|---|
| 1 | Problem identification & motivation | Structured concept-matrix literature review | Done | Chapters 1–2 drafted. **Gap #6 must be restated** — see §6 |
| 2 | Objectives of a solution | SMART objectives, RQs, CDM coverage criterion | Done | Current wording supersedes the original proposal; confirm with supervisor whether that needs a note |
| 3 | Design & development — specification | ADID / CDM / gateway architecture fixed ahead of code | **Done** | Ch3 document text still not updated to match D9, D17, D19, D20–D24 and the corrected URI. **Figure 1 must be redrawn** (it shows parallel matchers; the design is a cascade) |
| 4 | Design & development — implementation | Prototype build, M1–M14 | **Complete** | 14 modules; automated tests passing at the freeze (**update with the current `pytest` count**); offline after setup; every run record carries provenance hashes. A Streamlit interface was added afterwards as a presentation layer over the frozen modules (D39) |
| 5a | **Demonstration** | End-to-end walkthrough: one development schema → resolved DPP record | **Done** | `scripts/demo.py`; `demo_run_b.txt`, `demo_run_sample.txt`; web-interface walkthrough on `demo/` data. Separate activity from Evaluation (D14) |
| 5b | **Evaluation** | Ablation-ladder comparison across held-out schemas | **Done 2026-10-10** | Order kept: thresholds (D25) → calibrator (D26) → freeze (D30) → held-out schemas and ground truth (D31, D33) → runs (D34). Results in §5 |
| 6 | Communication | Dissertation, research paper, viva | **In progress** | Chapter 5 results drafted from the run records |

---

## 3. Framework architecture (current)

### Layer 1 — ADID (identity)
Three levels: **family** (the design, e.g. "Top A") / **variant** (one colour+size combination) / **instance** (one physical unit).

- Family has **no native GS1 identifier**. This is ADID's actual contribution — not a restatement of GS1.
- Variant = one GTIN each. A GTIN never represents a whole family. *(Unverified against the GS1 General Specifications — see sources.md §3; verify before the claim is published.)*
- Instance = GTIN + serial number = SGTIN.
- **URI shape (corrected):** `https://dpp.{manufacturer}/adid/{family}/{colour}_{size}/{serial}`

The variant is a **single composite segment**, colour and size joined by an underscore, with hyphen as the intra-value separator. This resolves a real ambiguity: with `/adid/{family}/{colour}/{size}`, the path `/adid/top-a/navy/M` was indistinguishable from `/adid/{family}/{variant}/{instance}`. Path depth is now unambiguous — 1 = family, 2 = variant, 3 = instance. Formal grammar: `adid/grammar.ebnf`.

Descriptive attributes — material, origin, season, care instructions — are deliberately absent from the path. They describe an item; they do not distinguish *which item is being addressed*. Putting them in the path would mean a data correction changes the identifier and invalidates every printed QR code (decisions.md **D9**).

**Conformance — open, and the question has changed.** EN 18219:2026 permits five identifier schemes: GS1 Digital Link URI, **IEC 61406 self-issued links**, W3C DIDs, RFID/2D identifiers, and DOIs. ADID issues a URI under the manufacturer's own domain, which is structurally a self-issued link — so project.md §13's open decision ("compliant GS1 Digital Link profile vs compatible extension") may be asking the wrong question. Until EN 18219 is read, ADID claims **GS1 Digital Link *compatible* (an extension), not compliant**, and records IEC 61406 as a *candidate* scheme with no claim asserted. `GET /adid/conformance` returns this machine-readably, with `"claim": null` for EN 18219 (FR-11.7). Unverified claims are recorded as unverified rather than implied by silence.

**Batch level — resolved (D22): option 3.** ESPR Art. 9(2)(d) names model, batch and item level; UNTP carries `batchNumber`; apparel manufacturing is batch-organised (dye lots, cut tickets, shipment lots). ADID has no batch level; batch is treated as CDM *data* rather than ADID *identity*, **deliberately**, because by D9's own test a batch number describes provenance and does not distinguish which item is addressed. **State in Ch6 what this gives up:** an ADID cannot address "all units from lot X", which matters for recalls and is recoverable only by querying the CDM. Full write-up in `cdm/ALIGNMENT.md`.

### Layer 2 — CDM (data)
W3C JSON-LD. **54 fields, 4 mandatory** (`productFamily`, `productIdentifier`, `manufacturerOperatorId`, `fibreComposition`).

Synthesised from **ESPR Annex III ¶1 (a)–(k)**, expanded through Art. 7(5) (substances of concern) and Art. 5(1) (sixteen product aspects); **GS1 EPCIS 2.0** event attributes; **UNTP** credential semantics; and **Regulation (EU) 1007/2011** for fibre composition. Procedure as specified: competency questions → term extraction per source → alignment table (conflict and granularity resolution) → precedence rules → alias vocabulary. Executed; written up in `cdm/EXTRACTION.md` and `cdm/ALIGNMENT.md`.

Provenance by source: **ESPR 35, UNTP 11, EPCIS 2.0 4, EU 1007/2011 1, ADIF-originated 3.** Every field carries `x-adif: {source, clause, granularity}`, so any field can be traced to a clause rather than to an assertion. Alias vocabulary: 222 entries across all 54 fields, normalised with the same function as incoming headers (otherwise Stage 1 could never fire) and rejected at load time if two fields claim the same normalised key (otherwise Stage 1's result depends on dictionary ordering — an NFR-5 reproducibility failure).

Precedence rules, applied in order where two sources describe the same concept: (1) ESPR wins on anything legally mandated; (2) EPCIS wins on event and lifecycle structure; (3) UNTP wins on verification and credential semantics; (4) where a source adds qualifying detail rather than a competing name, **keep both** (a carbon figure and its declared unit are two facts, not one).

**The mandatory set is deliberately small, and that is now defensible by citation rather than by taste.** The ESPR textiles delegated act is **not adopted** (verified — see sources.md). No binding list of mandatory DPP attributes for textiles exists. Marking all eleven Annex III points mandatory would have asserted a legal requirement that does not exist.

Two distinct "80%" claims, separately named (decisions.md **D12**) — and the separation now has a verified justification, because there is no regulatory mandate to measure against:
- **Reference attribute set coverage** (design-time) — the CDM schema covers ≥80% of a *constructed* reference attribute set, built from ESPR Annex III ¶1 and the Commission's preparatory documentation plus CIRPASS outputs. Verified once, when the CDM is built.
- **ESPR-mandatory field match rate** (runtime, Metric 2 below) — the proportion of that reference set actually populated correctly for a *given input schema*. Deliberately differently named so the two 80% figures do not read as one claim restated.

### Layer 3 — Hybrid gateway (method)
CSV / Excel / JSON ingestion → schema analysis (type inference, value sampling, duplicate-header handling) → **four-stage cascade** → calibrated confidence → reusable manufacturer templates → ADID-structured JSON-LD over a REST API.

**Strict fallback cascade with early exit** (decisions.md **D17**), not parallel weighted fusion:

1. **Stage 1 — alias lookup.** Exact match, normalised header against normalised alias. Deterministic.
2. **Stage 2 — fuzzy similarity.** RapidFuzz; `ratio`, `token_sort_ratio`, `partial_ratio`. Acceptance threshold **85** (D25).
3. **Stage 3 — semantic similarity.** `all-MiniLM-L6-v2`, offline, revision pinned and recorded in every run (FR-5.5). Encodes the field *description*, not the field name, because the model is trained on natural language. Acceptance threshold **85** (D25).
4. **Stage 4 — value-based matching.** Invoked **only** when every header-based stage returned nothing (FR-6.3). Scores sampled values against controlled vocabularies and patterns (ISO 3166, fibre names per Reg. 1007/2011, units, certification identifiers, percentage composition, ISO dates, GTIN check digits). Acceptance threshold **75**, tuned on its own (D25).

Confidence is **post-hoc Platt scaling, fitted per stage** (decisions.md **D6**; isotonic needs more data than this study has). A raw similarity score is never reported as a confidence. The calibrator refuses to borrow another stage's curve: if a stage has no fitted curve, it is reported as uncalibrated rather than silently scored against someone else's mapping. The review rule (D27): a mapping goes to a person when its calibrated confidence is below **0.9608**, the lowest confidence at which accuracy on the development data reaches 90%.

Conflict resolution, when two columns claim one CDM field, is by **stage precedence first** (template > alias > fuzzy > semantic > value), then raw score, then source position (decisions.md **D24**). An exact match against a curated vocabulary is stronger evidence than an inference from data shape, and the cascade order already encodes that.

**The limitation this design accepts, and Ch6 must state:** a cascade cannot recover from a confident wrong alias hit. Once Stage 1 accepts, Stages 2–4 never see the field. FR-7.5's conflict detection catches only the subset where two columns claim the same CDM field; it does not catch a single confidently-wrong alias. The development error analysis (D28) shows this happening: `Style_No` was mapped to `productIdentifier` where the gold standard says `gtin`.

---

## 4. Evaluation plan

### 4.1 Schema inventory — development vs held-out (D23)

The original plan had three evaluation schemas and "scratch schemas" for threshold tuning that were never specified. It now has an explicit split, which is a methodological **strength to claim in Ch3**, not an embarrassment to bury.

**Development set** — tuning, value-signature design, calibration fitting. Opened, inspected, iterated on freely.

| Schema | Source | Columns |
|---|---|---|
| `manufacturer_a` | Small-exporter style sheet | 7 |
| `manufacturer_a_drift` | Season-two variant of the above | 6 |
| `manufacturer_b_erpnext` | ERPNext open-source ERP item field list | 22 |
| `manufacturer_b_erpnext_drift` | Season-two variant | 21 |
| `manufacturer_c_odoo` | Odoo `product.template` field list | 22 |
| `manufacturer_c_odoo_drift` | Season-two variant | 21 |

99 columns, **51 mapping decisions** in the development gold standard.

**Held-out set** — evaluation only, constructed and opened **after** the freeze commit (tag `freeze-v1.0`, 2026-10-10).

| Schema | Source | Columns / mappable | Notes |
|---|---|---|---|
| H1 `kaggle_styles` | Fashion Product Images Dataset, `styles.csv` (Kaggle, paramaggarwal), MIT licence | 10 / 2 | Download-and-seal per **D18**. 44,446 rows. Repaired copy (22 malformed rows, D32). **No drift variant** |
| H2 `heldout_h2_dolibarr` | Dolibarr-style product export, **compiled by an AI assistant from recollection of the source's naming (D31)** | 26 / 8 | Plus drift variant (25 columns) |
| H3 `heldout_h3_techpack` | Buyer garment tech-pack lines, **compiled by an AI assistant (D31)** | 23 / 12 | Plus drift variant (22 columns) |

59 base-schema columns, 22 mappable. Season-two drift variants exist for **H2 and H3 only**, so Metric 4 is measured on two schemas.

**Construction rules, unchanged and load-bearing:**
- Source material for constructed schemas is **manufacturer-side documentation only** — open-source ERP field lists, buyer tech-pack templates, certification forms. **Never** ESPR / GS1 / UNTP documents (circularity guard, **D3**).
- Held-out schemas are built **without inspecting per-column matcher output**. This is the rule D23 was written because I broke.
- `data/heldout/` is declared in `config/default.yaml` as `heldout_dir` so the evaluation tooling can refuse it by path. `eval/grid_search.py` and `eval/fit_calibration.py` both exit rather than read from it, and an acceptance test asserts they do.

**Declared contamination and provenance limits, to state in Ch3 rather than leave to be found:**
- sources.md records prior awareness of a `masterCategory` field in `styles.csv`. That is minor, it occurred before the freeze, and it is declared.
- **H2 and H3 were compiled by an AI assistant that knew the CDM and the system.** Their headers follow source vocabulary from the assistant's recollection, not copied from a live Dolibarr instance or a real buyer document, and the matcher was not run on them before their answer keys were committed. Independence is argued, not proven, and the H2 headers are still to be checked against Dolibarr (sources.md).
- The Kaggle column list was read after the freeze, as D18 requires.

### 4.2 Metrics

Targets are tentative pending supervisor sign-off. All four are computed per condition per schema.

**Metric 1 — Mapping accuracy (F1)**, at field-mapping level. TP = correct canonical target proposed; FP = wrong target proposed; FN = mappable field missed. Macro-F1 across schemas. *Target: ≥ 0.85.* A conflict-demoted column is scored as unmapped (D21, resolved by default).

**Metric 2 — ESPR-mandatory field match rate.** Proportion of mandatory CDM fields correctly populated in the output JSON-LD, **with the denominator restricted to mandatory fields the gold standard actually maps for that schema**. A schema whose source data contains no fibre composition cannot be penalised for not producing one — that is a property of the input, not of the matcher. *Target: ≥ 80% per schema.*

Reported alongside it: the **mandatory coverage ceiling** — the highest Metric 2 an unrestricted calculation could reach on that schema. Reporting the ceiling next to the score is what stops the restricted denominator looking like a thumb on the scale. A schema with a ceiling of 0.75 and a score of 0.75 is a complete success *and* a demonstration that the input schema cannot carry a compliant passport, which is itself a finding. A schema with no mandatory field at all (H1, ceiling 0.0) has a vacuous rate and is excluded from Metric 2 (D36).

**Metric 3 — Confidence calibration (ECE).** 5 bins, **pooled across all schemas** (per-schema bins would be too small to interpret). Reliability diagram reported alongside the scalar. *Target: ECE ≤ 0.10.* Pooled pairs repeat a column once per condition that maps it, so the effective sample is smaller than the pair count (D36).

**Metric 4 — Template reuse rate.** Fraction of *unchanged* fields correctly auto-remapped on a **drifted** second upload, never an identical one (D8). *Target: ≥95% on unchanged fields; delta-field F1 ≥ 0.80.* Two figures are reported: reuse with a **reviewer-corrected** template (100% by construction, **not a result**) and reuse with a template built from the **system's own uncorrected output** (the informative figure). Delta-field F1 rests on 2 mappable new columns (H2) and 3 (H3) and is reported as counts (D36).

**Review burden** (decisions.md **D16**) — at the chosen acceptance threshold (**0.9608**, D27), the fraction of fields per schema falling below it and routed to the review UI, reported per ablation condition. This falls out of data already collected for Metric 3: no new participants, no new metrics infrastructure, no new ethics submission. The API also records what reviewers *did* with those fields — accepted, retargeted, supplied manually, rejected — yielding a manual-effort rate (FR-8.8). A full usability study is the subject of the open decision D38 (§4.7).

**Mean reciprocal rank** (FR-14.7) is instrumented and reported as supplementary diagnostic, not as a headline metric. It answers "when the top candidate was wrong, was the right answer nearby?", which is the difference between a tuning problem and a representation problem.

### 4.3 Baseline — ablation ladder (D10, amended by D19; count resolved under D20)

Each condition measured with all four metrics on every held-out schema:

| # | Condition | Config |
|---|---|---|
| a | **Fuzzy-only** — RapidFuzz alone, no alias table, no embeddings | `config/ablation/fuzzy_only.yaml` |
| b | **Alias + fuzzy** — Stages 1–2 | `config/ablation/alias_fuzzy.yaml` |
| c | **Full cascade** — Stages 1–3 with calibrated confidence | `config/ablation/full_cascade.yaml` |
| d | **Full cascade + value** — Stages 1–4 | `config/ablation/full_cascade_value.yaml` |
| s | **Semantic-only** (supplementary, **outside the ladder**) — Stage 3 alone, the AI-only comparison | `config/ablation/semantic_only.yaml` |

ΔF1 reported per step (b−a, c−b, d−c, and d−a overall), attributing gain to each **added stage** rather than lumping the whole cascade against a single strawman. The original hypothesis still holds — the gap should widen as schema heterogeneity increases — and now *which stage* does that work is visible too. `eval/metrics.py` also reports **per-stage surviving hit counts**, so a stage that fires often but loses every conflict is distinguishable from one that never fires.

**Resolved — D20.** project.md §7 and §14 specified **five** conditions; D10 specified three; D19 made the cumulative ladder four. Decided: the four-rung ladder, `exact_only` dropped (close to the strawman D10 rejected), and `semantic_only` run as a single supplementary condition **reported separately from the ladder** because it is not a cumulative rung. **Action owed:** amend project.md §7 and §14 so the documents stop disagreeing.

**Reporting caution (D35).** The `ablation_deltas` list stored inside an ablation run record pairs entries across schemas and must not be cited. Per-schema deltas are recomputed from the saved metrics by `eval/summarise_run.py`.

### 4.4 Threshold selection (D11)

Stage 2, 3 and 4 acceptance thresholds are set by **grid search on the development schemas, optimising macro-F1**, run after Phase 4 and before Phase 5b. Never tuned on the held-out set.

Enforcement, because a process rule that is only written down is a rule that gets broken on a tired evening:
- Every threshold in `config/default.yaml` was `null` until derived. Reading an unset tunable raises `UnsetTunable`; it never silently defaults. The guards are exercised against a null-threshold copy of the config now that real values are set.
- `eval/grid_search.py` refuses to run against `heldout_dir`, and refuses to run with the **stub embedder** — deriving a semantic threshold from a hash-based placeholder would produce a number that looks derived and is not.
- The derived values were **hand-copied** into `config/default.yaml` and are logged in §5 with their date and the search range. The config file records its own SHA-256 in every run record.

**Derived 2026-10-10 (D25):** joint search over fuzzy × semantic × value, each 50–100 in steps of 5 (1,331 triples), on the six development schemas with the value stage enabled. Optimum: **fuzzy 85, semantic 85, value 75**, macro-F1 **0.7685** (development set). Ties go to the stricter thresholds.

### 4.5 Ground truth

**Rulebook-governed.** `goldstandard/RULEBOOK.md` v1.0 — six rules covering cardinality, distractor and uncovered-field handling, ambiguity resolution, and when a column maps to nothing. Compiled, and **committed before any ground truth written against it**. That ordering is not cosmetic: it is the evidence that the rulebook governed the decisions rather than being written afterwards to justify them. The commit history is the artefact that proves it.

Frozen and version-controlled before any run. Each gold-standard file records its `frozen_at` date and the rulebook version it was decided under. Primary rater: YulaniA.

**≥25% of entries per schema independently checked by a second rater**, using only the rulebook and the CDM field list — deliberately **not** the perturbation log, so the check is not circular. **Done (D33):** second rater LiviruM, blank seeded sample (seed 2026): H2 8 of 26 columns, H3 6 of 23, H1 3 of 10 — **17 of 59 (29%)**, all agreeing, **17/17 pre-adjudication** against the ≥90% target. Harness: `scripts/second_rater.py`. The first H2 draw (6 of 26, 23%) fell below 25% and was redrawn before any sheet was given to the rater. The development gold standard also had a second-rater review on 2026-10-08. Caveat to state: one second rater and 17 sampled rows.

### 4.6 Freeze discipline (project.md §11)

The ordering below is the anti-circularity argument, and the git history is the only evidence of it. `scripts/freeze.py --check` performs the mechanical preconditions; it checks what can be checked mechanically and says so, rather than certifying intent.

1. CDM schema, alias vocabulary, value signatures, config and rulebook frozen.
2. **Freeze commit, tagged and dated.**
3. Held-out schemas constructed.
4. Held-out ground truth written.
5. Evaluation runs.

Current state: **steps 1 to 5 complete.** Tag `freeze-v1.0` on 2026-10-10 (commit `d857668`; hashes in D30); held-out data and answer keys committed after it; evaluation run at commit `ef89aa7` (D34). The Kaggle second-rater result was obtained after the run; the Kaggle answer key was not changed (D34).

### 4.7 Software-artefact evaluation — open (D38)

Metrics 1 to 4 evaluate the matching model. A separate plan evaluates the software as an artefact (`docs/software_evaluation_plan.md`): functional trace against the FRs, non-functional measurements (NFR-1, 3, 4, 5, 9), an end-to-end scenario on invented demonstration data (`demo/`), negative tests, a task-based user study with the System Usability Scale, and an expert walkthrough. **Decision owed (D38):** whether the user study runs. It would replace this document's earlier statement that a usability study is future work, and it needs ethics approval or an exemption first. Until decided, state the user study as future work.

---

## 5. Results

Logged in the order the runs happened. One block per run.

### 5.1 Development-set results — **not evaluation findings**
- **2026-10-10 · grid search (D25)** · six development schemas · 1,331 triples, 50–100 step 5 · optimum fuzzy 85, semantic 85, value 75 · macro-F1 **0.7685** (development set).
- **2026-10-10 · calibration (D26)** · 182 observations pooled across four conditions (alias 93, fuzzy 71, value 16, semantic 2) · in-sample ECE 0.0037 · semantic and value fits unstable at these sizes.
- **2026-10-10 · review rule (D27)** · lowest calibrated confidence at which accuracy reaches 90% → **0.9608**; 18 of 182 pooled mappings (value 16, semantic 2) clear it.
- **2026-10-10 · error analysis (D28)** · alias 27/31, fuzzy 2/10, semantic 1/1, value 16/16.

### 5.2 Held-out evaluation — 2026-10-10, commit ef89aa7
Config SHA-256 `3faa492b…84695f8` · model revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` · run records listed in D34.

**Metric 1 — F1 by condition and schema**

| Schema | Fuzzy only | + Alias | + Semantic | + Value | Semantic only |
|---|---|---|---|---|---|
| H1 Kaggle | 0.400 | 0.400 | 0.400 | 0.400 | 0.000 |
| H2 Dolibarr | 0.500 | 0.500 | 0.500 | 0.556 | 0.000 |
| H2 drift | 0.375 | 0.375 | 0.375 | 0.444 | 0.000 |
| H3 tech-pack | 0.667 | 0.762 | 0.818 | 0.870 | 0.154 |
| H3 drift | 0.762 | 0.762 | 0.818 | 0.870 | 0.154 |
| **Macro-average** | **0.541** | **0.560** | **0.582** | **0.628** | **0.062** |

Macro precision / recall / MRR: fuzzy only 0.575 / 0.525 / 0.664; + alias 0.597 / 0.542 / 0.672; + semantic 0.602 / 0.575 / 0.666; + value 0.610 / 0.658 / 0.674; semantic only 0.400 / 0.033 / 0.290.

Per-stage delta-F1 (recomputed per schema, D35): the value stage added +0.056 (H2), +0.069 (H2 drift), +0.051 (H3 and H3 drift) and 0.000 on H1; the semantic stage added +0.056 on H3 and H3 drift; the alias stage added +0.095 on H3.

**Metric 2 — mandatory-field match (restricted)**: H2 0.50, H2 drift 0.50, H3 1.00, H3 drift 1.00 in every ladder condition; coverage ceiling 0.50 for H2 and H3. H1 contains no mandatory field and is excluded.

**Metric 3 — calibration**: pooled ECE **0.054**; two populated bins (confidence 0.436 / accuracy 0.500, n = 88; confidence 0.884 / accuracy 0.843, n = 70). The pooled pairs are not independent. The semantic-only record's ECE of 0.029 rests on two pairs and is not evidence of calibration.

**Review burden** (band 0.9608): 1.00 (fuzzy only), 1.00 (+ alias), 0.98 (+ semantic), 0.93 (+ value).

**Metric 4 — template reuse (cascade-built template)**: H2 2/6, 2/6, 2/6, 3/6; H3 6/9, 6/9, 7/9, 8/9 down the ladder. Delta-field F1 0.500 (2 mappable new columns, H2) and 0.667 (3, H3). With a reviewer-corrected template reuse is 6/6 and 9/9 by construction and is not a result.

**Against the targets:** only ECE ≤ 0.10 was met. F1 ≥ 0.85 (0.628), mandatory match ≥ 80% on every schema (H2 0.50), reuse ≥ 95% (0.50 and 0.89 with the full system) and delta-F1 ≥ 0.80 (0.50 and 0.667) were not. Report that as the finding.

---

## 6. Standing corrections to Chapters 1–3

Carried here so they are not lost between document revisions.

1. **Research gap #6 must be restated.** As written it claims the key standards "have never been realised in one unified transformation architecture." EN 18223:2026 now defines exactly that container, and an examiner can disprove the gap with one search. The gap survives in a **sharper** form, because the published standards explicitly do *not* specify identifier **granularity** and do *not* specify product **attributes** ("attributes belong to sectoral acts, not JTC 24 standards"). Restated: *the standards specify the plumbing — identifiers, carriers, APIs, access control — but no apparel-sector attribute model exists, no identifier granularity is defined, and no open SME-accessible implementation targets this context.* All three are what ADIF supplies.
2. **Annex I → Annex III** wherever DPP data elements are meant (Ch1, Ch2, Ch3, research objectives doc). Both annexes are relevant; only Annex I is currently cited.
3. **Figure 1 must be redrawn.** It shows name-, structure- and instance-based matchers in **parallel**; the design is a **cascade** (D17). Its "instance-based matching" box now maps to a stage that exists (Stage 4 ≈ Rahm & Bernstein's instance-based category). Its "structure-based matching" box corresponds to nothing implemented — nested/hierarchical input is an explicit scope exclusion (project.md §2).
4. **Ch1 must not describe the EU DPP registry as forthcoming** if the reports of it going live on 20 July 2026 are correct. Unverified; the scope exclusion stands either way.
5. **FR-11.6** (support all three granularity levels so the artefact survives whichever the delegated act selects) is **not** defensive over-engineering — it is the correct response to a live legal uncertainty, and that can now be said with a citation.
6. **Vendor neutrality is mandated by the regulation, not asserted by this thesis.** ESPR Art. 10(1)(d) requires DPP data to be open-standards-based, interoperable, machine-readable, structured, searchable and transferable "without vendor lock-in". This is the strongest available support for the thesis title and currently goes uncited.
7. **State the limitations, plainly (Ch6):** (a) a small evaluation set (five schemas, 59 base columns, 22 mappable); (b) two of three held-out schemas compiled by an AI assistant that knew the system (D31); (c) one primary and one second rater, 17 sampled rows (D33); (d) drift tested as header changes only; (e) D21 was settled by a default and logged after the run; (f) two defects found after the freeze and recorded rather than patched — stored ablation deltas (D35) and a raw-parser-error ingestion failure (D32); (g) calibration for the semantic and value stages rests on 2 and 16 observations and the review threshold was derived in-sample (D26, D27); (h) the batch-level gap (D22); (i) the hosted web interface runs without the language model and its free-tier storage may reset (D39).
