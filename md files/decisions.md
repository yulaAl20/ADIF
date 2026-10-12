# decisions.md — the decision log
**Last updated:** 2026-10-11

Each entry records: what was decided, what else was considered, why, **what was given up**, and what else has to change as a consequence. The "gave up" line is the one that matters at viva — a decision log that only lists benefits is a sales document, not a record.

---

## ⚠ Read this before pasting

**Entries D1–D16 are not reproduced in this file.** I do not have their text, and reconstructing them from the way they are cited elsewhere would put words into your decision log that you never wrote. A decision log with invented bodies is worse than an incomplete one.

Use this file in two parts:

1. **§A — Amendments to D1–D16.** Apply these edits to your existing entries. Each says which entry, what changes, and why. Do not rewrite the entries; append the amendment lines, so the original decision and its later revision are both visible. An examiner reading a log that was silently edited learns nothing; one reading "decided X, amended by D23 on 2026-10-05 because Y" learns how you work.
2. **§B — Entries D17–D40.** Paste these in full. Anything marked **[FILL IN]** or **[confirm]** is a fact only you can supply or check.

---

## §A — Amendments to existing entries

| Entry | Amendment | Driver |
|---|---|---|
| **D2** (schema inventory) | **Superseded in part by D23.** The ERPNext- and Odoo-derived schemas are now *development* schemas, not held-out. The evaluation set is rebuilt from uninspected sources. Append: *"Amended 2026-10-05 by D23."* | D23 |
| **D3** (circularity guard on source material) | Unchanged and still load-bearing. The guard also covers **held-out construction without inspecting per-column matcher output**, which is the failure D23 records. **Added 2026-10-11:** held-out schemas H2 and H3 were compiled by an AI assistant from its recollection of manufacturer-side vocabulary, not copied from live Dolibarr documentation or a real buyer document (D31). Compliance with the guard is argued, not proven. | D23, D31 |
| **D6** (calibration method = Platt) | Unchanged. Implementation note: fitted **per stage**, and the calibrator **refuses to borrow another stage's curve** — an uncalibrated stage is reported as uncalibrated rather than scored against someone else's mapping. Fitted 2026-10-10 (D26). | Implementation |
| **D8** (drifted "season-two" variants) | Unchanged. Three dev drift variants exist with machine-readable perturbation logs. Held-out drift variants were built after the freeze for **H2 and H3 only** (H1 has none), so Metric 4 is measured on two schemas (D31). | Implementation |
| **D9** (ADID hierarchy) | **Amended.** The URI shape is `/adid/{family}/{colour}_{size}/{serial}` — the variant is a **single composite segment**, not two. `/adid/{family}/{colour}/{size}` was ambiguous against project.md's `/adid/{family}/{variant}/{instance}` at depth 3. The conformance target is open and points at **IEC 61406**, not GS1 Digital Link — see D22 and methodology.md §3. | Implementation; EN 18219 finding |
| **D10** (ablation ladder, three conditions) | **Amended by D19** — the ladder is four rungs. **Count resolved under D20** (four-rung ladder plus one supplementary condition). Append: *"Amended 2026-08-18 by D19; count resolved by D20."* | D19, D20 |
| **D11** (thresholds by grid search) | Executed 2026-10-10 (D25). Enforcement strengthened: thresholds were `null` in config and raised rather than defaulted until derived; the grid search **refuses** to read `heldout_dir` and **refuses** to run with the stub embedder; both refusals are asserted by automated tests. | Implementation |
| **D12** (two separate 80% claims) | Unchanged, and now **better justified**: the textiles delegated act is verified **not adopted**, so there is no regulatory mandate to measure against. Measuring coverage against a *constructed* reference set was the only honest option, not a convenience. | sources.md verification |
| **D14** (Demonstration separate from Evaluation) | Unchanged. Demonstration run captured 2026-10-10 (D29). | |
| **D15** (Schema A = Fashion Product Images Dataset) | **Superseded in part by D23.** The dataset remains in the study but moves to the **held-out** set, under D18's download-and-seal rule. The development `manufacturer_a` schema is a different, smaller schema. Append: *"Amended 2026-10-05 by D23."* | D23 |
| **D16** (review burden statistic) | Unchanged. The API also records reviewer *actions* (accepted / retargeted / supplied / rejected), giving a manual-effort rate (FR-8.8) at no extra data-collection cost. The review band (0.9608, D27) is now the threshold used. | Implementation |
| **D18** (download-and-seal) | Rule unchanged. Checksum recorded 2026-10-10; the file was later extracted and a repaired copy made outside the frozen system (D32). | D32 |

---

## §B — Entries

## D17 — Cascade vs parallel weighted combination
**Date:** 2026-08-18. Resolves the first open decision in project.md §13 (blocks B3).
**Decided:** Strict fallback **cascade with early exit** — alias → fuzzy → semantic — not parallel scoring with weighted combination.
**Options considered:** (a) cascade with early exit; (b) parallel scoring of all stages with a tuned weighted combination.
**Why:** (b) would likely calibrate better, since it sees every signal for every field rather than stopping at the first acceptance. But it requires weight tuning — a second tuning surface on top of the thresholds already grid-searched under D11, on the same limited development data. It also breaks D10's ablation ladder, which attributes ΔF1 to each *added stage* and so presupposes stages that can be added in sequence. And RQ4 and Objective 4 already say "cascaded" following D13; choosing (b) would mean rewriting both.
**Gave up:** Real accuracy. A cascade cannot recover from a confident wrong alias hit — once Stage 1 accepts, the later stages never see the field. This is a genuine limitation of the design and belongs in Chapter 6 as a stated one, not omitted. FR-7.5's conflict detection catches only the subset where two columns claim the same CDM field; it does not catch a single confidently-wrong alias.
**Consequence:** Figure 1 must be redrawn. It shows name/structure/instance-based matchers running in parallel, which contradicts the design as decided and as described in Chapter 3.

---

## D18 — Download-and-seal rule for Schema A (Kaggle)
**Decided:** The Fashion Product Images Dataset is downloaded, its SHA-256 recorded, and the file placed in `data/heldout/` **unopened**. Its column list is confirmed only at evaluation time and reported in Ch6. Checking it earlier would tune the alias vocabulary to the evaluation set.
**[FILL IN — restore from your earlier copy: options considered, why, what was given up.]**

**Outcome (2026-10-10):**
- **File:** `data/heldout/styles.csv.zip`, downloaded unopened and unextracted
- **SHA-256:** `2D5C74F249C44DA1690BBDD2221E526E57D170EEA8260D03605F7446813E92C1`
- **Size:** 935,785 bytes
- **Downloaded:** 2026-10-10, using the Kaggle CLI, after the freeze tag `freeze-v1.0`
- **Source:** https://www.kaggle.com/datasets/paramaggarwal/fashion-product-images-dataset
- **Path within dataset:** `fashion-dataset/styles.csv` (only the metadata table; the images and other files were not downloaded)
- **Licence:** MIT, as reported by the Kaggle CLI
- **Extracted 2026-10-10** after the zip was hashed (repair logged in D32).
- **Column list now known** (read post-freeze, as this rule requires): `id, gender, masterCategory, subCategory, articleType, baseColour, season, year, usage, productDisplayName`.

---

## D19 — Value-based matching stage (M6) retained in Phase 4 scope
**Date:** 2026-08-18.
**Decided:** M6 / B11 stays in scope. The in/out decision remains at the **B10 checkpoint**, as project.md §13 specified — it is not pre-empted on timeline grounds. `stage_order` declares four stages; the toggle stays false until B11 is built.
**Options considered:** (a) cut M6 now to protect the Phase 4 window; (b) keep it and hold the decision to B10 as specified.
**Why:** M6 is the only stage that can recover a field whose *header* is uninformative but whose *values* are diagnostic — a column named `col_7` full of ISO 3166 codes. The deliberately idiosyncratic schema is exactly where header-only matching should degrade and where the value stage would show its worth; cutting it removes the ablation's most interesting rung. It is also cheaper than project.md §5 implies: FR-10.2 already requires ISO 3166 codes, fibre names (Reg. 1007/2011), units and certification identifiers as controlled vocabularies for CDM validation, and FR-6.4 reuses those same vocabularies as signatures. The genuinely new work is percentage-composition, ISO date, GTIN check-digit and currency patterns, plus the conformance scoring function.
**Gave up:** Schedule slack, and — more sharply — *evaluation* surface rather than build time. A fourth condition multiplies across schemas, metrics and drift variants, and D11's grid search must now tune a fourth threshold on the same limited development data, diluting it. The cost of this decision lands in Phase 5, not Phase 4.
**Protection retained:** project.md §9's sequencing rule is unchanged and now load-bearing — **B10 before B11**. If the window closes, what is lost is the fourth matching stage, never the evaluation harness that produces Chapter 6.
**Contingency instead of a scope cut:** pressure is absorbed through the existing M/S/C requirement grading, which exists for this purpose ("C = cut first under time pressure"). No module is dropped; individual **S** and then **C** requirements are, and each drop is logged here when made.
**Outcome:** B10 and B11 both completed. The stage is built and wired into the cascade; the config toggle is the only thing holding it off, and it is flipped per ablation condition. In evaluation the value stage added +0.05 to +0.07 F1 on H2 and H3 and nothing on H1 (D34).
**Consequence:** Figure 1's "instance-based matching" box now maps to a stage that actually exists (≈ Rahm & Bernstein's instance-based category). What remains wrong in that figure: the parallel arrangement, which contradicts D17, and the "structure-based matching" box, which corresponds to nothing implemented — nested/hierarchical input is an explicit scope exclusion.

---

## D20 — Ablation condition count — **RESOLVED**
**Decided (ratified 2026-10-09 per the code comments in `eval/run_ablation.py` and `config/ablation/semantic_only.yaml` — [confirm the date against your notes]):** a four-rung ladder `fuzzy_only` → `alias_fuzzy` → `full_cascade` → `full_cascade_value`. `exact_only` dropped. `semantic_only` run as **one supplementary condition, reported outside the ladder**, and kept out of the delta-F1 sequence.
**Options considered:** the original three (D10); the five in project.md §7 and §14; four, plus a supplementary condition.
**Why:** `exact_only` is close to the single-strawman framing D10 rejected. `semantic_only` answers a real question (would embeddings alone have sufficed?) but is not a rung on a cumulative ladder; putting it in the ladder would make ΔF1 unattributable.
**Gave up:** the five-condition requirement in project.md §7 and §14, and attribution for a non-cumulative condition.
**Outcome:** executed 2026-10-10 (D34). Semantic-only macro-F1 was 0.062.
**Action still owed:** amend D10 (done in §A), and amend project.md §7 and §14 so the documents agree.

---

## D21 — How demoted conflict losers are counted — **RESOLVED BY DEFAULT, LOGGED 2026-10-11**
**What was used:** every run, including the evaluation, used `count_demoted_as_fp=False` (the default in `eval/metrics.py`). A conflict-demoted column is scored as **unmapped**: a false negative if the gold standard maps it, a correct rejection if the gold standard says `NO_MAPPING`. It is never counted as an additional false positive, and it is not re-offered its next-best candidate.
**Honesty note, state it in Ch3:** this was the default in force, not a choice made before the numbers existed, and it is being logged after the run. Do not describe it as pre-registered.
**What it affects:** conflicts concentrate on fields such as `colour` and `size`. The treatment changes reported F1 without changing any matching code.
**Optional:** report a sensitivity figure with `count_demoted_as_fp=True` to show how much it matters.

---

## D22 — ADID and the batch level — **RESOLVED: option 3**
**Decided [confirm the date; it was before the freeze]:** batch is **CDM data, not ADID identity** (option 3), adopted deliberately.
**Options considered:** (1) state it as a limitation; (2) add a fourth optional ADID level; (3) treat batch as CDM *data* rather than ADID *identity*. Full write-up in `cdm/ALIGNMENT.md`.
**Why:** D9's principle is that only what *distinguishes which item is being addressed* belongs in the path. A batch number describes provenance: two garments from different dye lots are the same variant, orderable and sellable interchangeably. By D9's own test, batch fails to earn a path segment. EN 18219:2026 reinforces this — the published standards do not define granularity, so there is no external schema ADID is failing to conform to.
**Gave up, and Chapter 6 must say:** an ADID cannot address "all units from lot DL-7781." For a **recall** — a realistic apparel scenario — that is a genuine functional gap, recoverable only by querying the CDM rather than by resolving an identifier.
**Not chosen:** option 2 would need a grammar change, a URI depth change, API route changes and a re-freeze, to serve a level the standards do not require and the regulation names only as one option among three.

---

## D23 — Schemas B and C reassigned from held-out to development
**Date:** 2026-10-05.
**Decided:** The ERPNext-derived and Odoo-derived schemas become **development** schemas. The held-out evaluation set is rebuilt from sources not yet inspected.
**Why — and this is a self-report:** while constructing them, the value-signature library was adjusted three times in response to their per-column output — a hex-colour pattern matching an HS code, a numeric-size pattern matching a weight, a carbon-footprint pattern matching any number. Every fix was a genuine bug, but each was *found by looking at data destined to be sealed*. That is tuning on the evaluation set (project.md §11), and it does not stop being so because the fixes were correct.
**Options considered:** (a) revert the fixes and seal B and C — which ships a value stage with patterns known to be broken and leaves nothing to tune signatures against; (b) reassign B and C to development and rebuild the held-out set.
**Gave up:** two ready-made held-out schemas, and roughly a day rebuilding the evaluation set from untouched sources.
**Gained, and this is the larger part:**
- A genuine tuning set. The calibration fit previously warned at ten observations per stage; three development schemas materially improve that.
- A clean tuning/evaluation split, which the original three-schema plan did **not** have — thresholds were to be grid-searched on "scratch schemas" that were never actually specified anywhere.
- Six schema files rather than three, 99 columns and 51 mapping decisions instead of roughly 50 total. Still far too few for a significance test, but a better basis for reporting a trend.
**Revised inventory (supersedes D2 and D15 in part):**
- **Development** (tuning, signature design, calibration fitting): `manufacturer_a`, `manufacturer_b_erpnext`, `manufacturer_c_odoo`, plus drift variants.
- **Held-out** (evaluation only, opened after the freeze commit): Fashion Product Images Dataset (D15, under D18's seal rule), plus a Dolibarr-style export and a buyer tech-pack, **constructed without inspecting per-column matcher output** (built as D31 records).
**Enforcement added, so the rule is not merely written down:** `heldout_dir` is declared in `config/default.yaml`; `eval/grid_search.py` and `eval/fit_calibration.py` refuse to read from it; an acceptance test asserts those refusals. Two scripts named the path literally and had to be changed to resolve it from config — the test caught both. (It caught a third lapse on 2026-10-10: a data-repair script's docstring named the sealed path.)
**Consequence:** methodology.md's schema list is rewritten. **Chapter 3 should state the dev/held-out split explicitly — it is a methodological strength worth claiming, not an embarrassment to bury.** The contamination itself is declared, dated and traceable; that is what a decision log is for.

---

## D24 — Conflict resolution respects stage precedence
**Date:** 2026-10-05.
**Decided:** When two columns claim one CDM field, the winner is chosen by **stage precedence first** (template > alias > fuzzy > semantic > value), then raw score, then source position.
**Why:** previously the tie broke on raw score alone. Alias hits and value hits both score 100, so a column named `customs_tariff_number` — whose HS code `610910` happens to be six valid hex characters — took the `colour` field away from a column literally named `colour_name`, on nothing more than appearing earlier in the file. An exact match against a curated vocabulary is stronger evidence than an inference from data shape, and the cascade order already encodes that ranking.
**Gave up:** nothing. The previous behaviour had no justification beyond being the first thing written.
**Follow-on:** raised **D21** — how the demoted loser is counted in the metrics (resolved by default, above).

---

## Freeze-time decisions (2026-10-10)

### D25 — Matching thresholds derived (executes D11)
- **Date / script:** 2026-10-10, `python -m eval.grid_search --real-model`
- **Data:** 6 scratch schemas in `data/dev` (A, B, C and their drifted copies) against the frozen gold standards dated 2026-10-08. The sealed directory was not read.
- **Method:** exhaustive joint search over fuzzy × semantic × value, each 50–100 in steps of 5 (11³ = 1,331 triples), optimising macro-F1. The search ran on the complete cascade including the value stage (`config/ablation/full_cascade_value.yaml`).
- **Result:** macro-F1 0.7685 at **fuzzy = 85.0, semantic = 85.0, value = 75.0**.
- **Changes from the earlier plan:**
  - The value threshold is tuned on its own. It previously borrowed the fuzzy value.
  - The fuzzy and semantic thresholds are therefore tuned with the value stage enabled.
  - Ties go to the stricter (higher) thresholds.
- **Evidence:** `config/thresholds.yaml`, `config/grid_trace.json`.

### D26 — Calibration fitted
- **Method:** Platt scaling, one model per stage (D6), fitted on the scratch schemas pooled across the four ablation conditions: 182 observations.
- **Observations per stage:** alias 93, fuzzy 71, value 16, semantic 2.
- **Caveat:** the semantic and value fits are unstable at these sample sizes, and the script warned about both. Confidence values for those two stages are reported with that caveat.
- **In-sample ECE:** 0.0037. This is not Metric 3, which is computed on the held-out data.
- **Artefact:** `config/calibrator.json`. It is gitignored by default, so it was committed with `git add -f` as part of the frozen set.

### D27 — Review threshold rule
- **Rule (stated before results):** a mapping goes to a human when its calibrated confidence is below the lowest confidence at which accuracy on the scratch data reaches 90%.
- **Result:** `confidence.bands.review = 0.9608`.
- **Effect:** 18 of 182 pooled scratch mappings are auto-accepted, at 100% accuracy. Only the 18 mappings from the value stage (16) and the semantic stage (2) clear the bar. Alias mappings (confidence 0.870) and fuzzy mappings (about 0.43) all go to review.
- **Caveats:** the figure is in-sample and rests on small counts for the stages above the threshold. The 90% target was not lowered to let the alias stage through. Review burden can be reported at 85% and 95% as a sensitivity analysis without changing this rule.
- **Used by:** the API and review screen (flagging), the web interface (D39), and the review-burden statistic in the ablation run (default).

### D28 — Development-set error analysis (full cascade, scratch schemas)
- **Per-stage accuracy:** alias 27/31 (87.1%), fuzzy 2/10 (20.0%), semantic 1/1, value 16/16.
- **Alias errors (4):**
  - `Style_No` → `productIdentifier`, gold `gtin` (R3.4, R4.1: decide on contents). The alias stage reads headers only and exits early.
  - `supplier_gln` → `manufacturerOperatorId`, gold `NO_MAPPING` (R4.3: a supplier need not be the manufacturer).
- **Fuzzy errors (8):** distractor columns that should map to nothing: `description`, `weight_uom`, `has_batch_no`, `has_serial_no`, `descript`. Several score 100, so no threshold removes them.
- **Decision:** the gold standard follows the rulebook, so it was not changed. Aliases and matchers were not changed to remove these errors. They are findings for the evaluation chapter, not defects to tune away.

### D29 — Demonstration run
- **Command:** `python -m scripts.demo --real-model --file data\dev\manufacturer_b_erpnext.csv`, plus the built-in sample.
- **Outputs:** `demo_run_b.txt`, `demo_run_sample.txt`.
- **Setup:** real 54-field CDM, thresholds from the frozen config, calibrated confidence, review band 0.9608. These runs are demonstration only and are not an evaluation.

### D30 — Freeze record
- **Tag:** `freeze-v1.0`, 2026-10-10
- **Commit:** `d8576689eca7aa0ab9759a548ceb6c32c4a33e89`
- **Check output:** READY TO FREEZE. Sealed directory empty at freeze, working tree clean, 9 gold standards present.
- **Frozen artefacts and SHA-256** (from the `freeze --check` output; verify against `decisions_freeze_record.json`):
  - `cdm/cdm_v1.0.schema.json` — `357698a9f230c127e09563107b708c7f539fbf87486f15c42ed71f3aefcb2e54`
  - `cdm/cdm_v1.0.context.jsonld` — `5ddaa0828ba69867546824225a8fb10eb8d3e8394dad64ec2b8c4fa7d923f6e3`
  - `cdm/aliases_v1.0.yaml` — `76d33e551f752dc8f8b7d75a57425b6b94a422050026bbbab108b903faf8931e`
  - `adid/grammar.ebnf` — `92090c1c58e96efbbcc26d5f34c809114f88b6bb8e1c041dfba1f050a4f271a7`
  - `config/default.yaml` — `3faa492bfc75c9928be50e9335fb464332f1ca2b9f65c421a05e4542d84695f8`
  - `cdm/vocabularies/signatures.yaml` — `3f43e180c363b9e47f8498d2f75f820d989f5253f741398418ef61e27efee579`
  - `config/calibrator.json` — `d8677181573884d7317a96c6359fcdc8402d003b04762d23087375c837b3e7eb`
- **After this point:** no change to frozen artefacts. Held-out data may now be added to `data/heldout` (D18).

---

## Post-freeze decisions (2026-10-10 onward)

### D31 — Held-out schema construction and disclosure
- **Date:** 2026-10-10, after tag `freeze-v1.0` (commit `d857668`).
- **H1 (Kaggle):** `styles.csv` from the Fashion Product Images Dataset, downloaded unopened; SHA-256 of the zip recorded in D18.
- **H2 (`heldout_h2_dolibarr.csv`, 5 rows × 26 columns) and H3 (`heldout_h3_techpack.csv`, 5 rows × 23 columns):** compiled by an AI assistant (Claude).
  - Headers follow Dolibarr product-table and extrafield naming (H2) and typical buyer tech-pack vocabulary (H3), **from the assistant's recollection of those sources, not copied from a live Dolibarr instance or a specific buyer's document.**
  - All values are invented. Barcodes pass the GTIN-13 check digit.
  - The assistant knew the CDM and the system. Headers were taken from source vocabulary rather than chosen to match or avoid CDM fields, and the matcher was not run on these files before the answer keys were committed.
- **Drifted variants:** `scripts.perturb_schema --level drift --seed 7`. One column dropped and five renamed in each (H2: `weight_units` dropped; H3: `Main Label` dropped). H1 has no drift variant.
- **To do before citing:** check the H2 header list against a Dolibarr instance or its documentation and record any difference. **[FILL IN]**
- **Provenance note:** `data/heldout/PROVENANCE.md`.

### D32 — Kaggle file repaired outside the frozen system
- `styles.csv` contains rows with an unquoted comma in the last column (`productDisplayName`), giving 11 fields against a 10-column header. A strict reader fails first at source line 6044 (`pandas.errors.ParserError`).
- The loader is frozen, and the file was not edited by hand. `scripts/repair_kaggle_styles.py` re-joins surplus fields into the last column and writes a **new** file; rows with too few fields would stop the script (none occurred).
- **Result:** 44,446 data rows, 10 columns, **22 rows repaired** (first at line 6044).
- **SHA-256 of extracted `styles.csv`:** `CD86BD2D71B4065ED91786A52AA6CCC0EED343949791C663BE9AF35F105A128C`
- **SHA-256 of repaired `kaggle_styles.csv`:** `E0ABD709EC0000596452695626DAF904AC87F3C86FA6F8E6ACC8EBBB01DBB338`
- The original extracted file was moved out of `data/heldout` so the harness does not load it. The zip hash in D18 is unchanged.
- **Findings for the limitations section:** the loader surfaces this as a raw parser error, not a user-facing ingestion message; an empty upload to the API returns a 500 with a raw traceback; and a missing optional dependency is reported under a misleading threshold hint. All deferred to a post-evaluation version.

### D33 — Ground truth and second rating for the held-out schemas
- **Primary rater:** YulaniA. Answer keys written from `goldstandard/RULEBOOK.md` and `CDM_FIELDS.txt` only, before any run on these schemas. Drift keys derived mechanically with `scripts.derive_drift_gold` (every column resolved; no hand decisions).
- **Answer-key sizes (columns / mapped):** H2 26/8, H2 drift 25/8, H3 23/12, H3 drift 22/12, Kaggle 10/2.
- **Second rater:** LiviruM, independent, given only the blank sheet, the rulebook, `CDM_FIELDS.txt` and the CDM schema. Never shown the answer keys, perturbation logs or matcher output.
- **Sampling:** seeded (2026), reproducible via `scripts.second_rater sample`.
  - The first H2 draw (`--fraction 0.25`) gave 6 of 26 columns (23%), below the 25% target, and was **redrawn at 0.3 (8 of 26, 31%) before any sheet was given to the rater**.
- **Pre-adjudication agreement:** H2 8/8, H3 6/6, Kaggle 3/3 = **17/17 (100%)**, against the 90% target. Agreement files: `goldstandard/*.agreement.json`.
- **Caveat to state:** 17 sampled rows (about 29% of the 59 base-schema columns), one second rater.

### D34 — Evaluation run
- **Commit:** `ef89aa757a446426ad85da4cc4cdbc08cbe4385f` (after the answer keys were committed; tag `freeze-v1.0` precedes it).
- **Config hash:** `3faa492b…84695f8` (see the run records' provenance block). Model revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.
- **Commands (RUNBOOK step 12):** `eval.run_ablation` (ladder), `eval.run_ablation --conditions semantic_only`, `eval.run_template_reuse` (gold template), `eval.run_template_reuse --template-from cascade`.
- **Run records (all `[EVALUATION]`):** `runs/eval_20261010T071102Z.json`, `runs/eval_20261010T071120Z.json`, `runs/template_reuse_20261010T071134Z.json`, `runs/template_reuse_20261010T071150Z.json`.
- **Ordering note:** the Kaggle second-rater result (3/3) was obtained **after** this run. The Kaggle answer key was not changed after the run, and agreement was 100%, so the run stands as recorded.
- **Headline:** macro-F1 0.541 / 0.560 / 0.582 / 0.628 up the ladder; 0.062 semantic only; pooled ECE 0.054. Only the ECE target was met (methodology.md §5).

### D35 — Defect found after freeze: stored ablation deltas
- The `ablation_deltas` list inside an ablation run record pairs consecutive entries of the whole metrics list, so it compares different schemas (for example `fuzzy_only -> fuzzy_only`). The console output printed the correct per-schema deltas, but the stored list must not be cited.
- **Decision:** the frozen code is not changed. Deltas are recomputed from the saved `metrics` by `eval/summarise_run.py` (read-only analysis, outside the frozen system). The per-condition metrics themselves are unaffected.
- Fix deferred to a post-evaluation version; list as a limitation.

### D36 — Reporting rules for the evaluation
1. **Template reuse:** with a reviewer-corrected template, reuse on unchanged columns is 100% by construction; it is **not** reported as a result. Report reuse with the cascade-derived template, and delta-field F1, always with counts (denominators are 2 mappable new columns for H2 and 3 for H3).
2. **Metric 2 (mandatory-field match):** the Kaggle schema contains no mandatory field (coverage ceiling 0.0), so its restricted rate is vacuous. Report Metric 2 over H2, H3 and their drifted copies only, with the coverage ceiling (0.5 for H2 and H3).
3. **ECE:** pooled over conditions and schemas, so the same column is counted once per condition that maps it. State that the effective sample is smaller than the 158 pooled pairs; two bins are populated.
4. **Macro-averages:** each schema counts once. Per-schema results are always reported alongside, because the Kaggle schema has 10 columns (one column moves its F1 by 10 or more points).
5. **Review burden** is reported with the review band 0.9608 from D27.

### D37 — Environment checks
- **NFR-3 (hardware), 2026-10-10:** Intel Core i5-1135G7 @ 2.40 GHz, 4 cores / 8 threads; 11.8 GB RAM as reported by Windows; Intel Iris Xe integrated graphics only; `torch.cuda.is_available()` = `False` (CPU-only run).
- **NFR-1 (offline):** demo run with Wi-Fi off completed on the real model from the local cache. **[FILL IN date and screenshot reference]**
- **NFR-9 (second machine):** **[FILL IN after the install: machine, OS, Python version, date, deviations from `docs/setup.md`, time taken, outcome]**
- Per-schema cascade time on this machine was 0.01 to 0.4 s for the five schemas; the 44,446-row Kaggle file took 0.08 s for the full cascade (stage time only, excluding file loading).

### D38 — Software-artefact evaluation — **OPEN**
A plan exists (`docs/software_evaluation_plan.md`: functional trace, NFRs, end-to-end scenario, negative tests, user study, expert walkthrough). **Decide whether the user study (E5) will run.** It conflicts with methodology.md's statement that a usability study is future work, and it needs ethics approval or an exemption first. Log the decision either way.

### D39 — Web interface (Streamlit) and hosting
A Streamlit interface was added over the frozen modules, with no change to `src/`. Saved templates persist in a separate SQLite file. Hosting on Streamlit Community Cloud runs **without the language model** (meaning-based matching off, stated on screen), and free-tier storage may be reset; template backup and restore were added for that reason. This is a presentation layer outside the frozen set. It also applies the saved template on upload, which the earlier REST API did not do.

### D40 — Public wording about ADID
The app tells users a barcode identifies one colour and size and that ADID adds the missing design level. That rests on the **unverified GTIN claim** in sources.md §3. Verify against the GS1 General Specifications before publishing, or soften the wording. The app also states that ADID is not an official standard and that example addresses are illustrative.

---

## Status summary

| Entry | Subject | Status |
|---|---|---|
| D1–D8 | (in your copy) | Settled; D2, D3, D6, D8 carry amendments in §A |
| D9 | ADID hierarchy | Settled; amended (composite variant segment; conformance target reopened) |
| D10 | Ablation ladder | Settled; amended by D19; count resolved by D20 |
| D11 | Threshold selection | Settled; executed (D25) |
| D12 | Two 80% claims | Settled; justification now verified |
| D13 | "Cascaded" wording in RQ4 / Obj. 4 | Settled |
| D14 | Demonstration ≠ Evaluation | Settled |
| D15 | Kaggle dataset as a study schema | Settled; amended by D23 (moved to held-out) |
| D16 | Review-burden statistic | Settled; extended with reviewer-action counts |
| D17 | Cascade vs parallel | Settled |
| D18 | Download-and-seal | Settled; checksum recorded; **restore original body** |
| D19 | Value stage retained | Settled; built |
| D20 | Ablation condition count | **Settled** (four rungs + supplementary); project.md §7/§14 still to amend |
| D21 | Demoted-conflict metric treatment | **Settled by default; logged 2026-10-11** |
| D22 | ADID batch level | **Settled: option 3** |
| D23 | Dev / held-out reassignment | Settled |
| D24 | Stage precedence in conflicts | Settled |
| D25–D30 | Thresholds, calibration, review rule, error analysis, demonstration, freeze | Settled |
| D31–D37 | Held-out build, repair, second rating, evaluation run, defect, reporting rules, environment | Settled; D37 has [FILL IN] items |
| D38 | Software-artefact evaluation / user study | **OPEN** |
| D39 | Web interface and hosting | Settled |
| D40 | Public ADID wording | **Open until the GTIN claim is verified** |

**Open items:** D38 (user study), D40 (verify the GTIN claim before the app is public), and the [FILL IN] items in D18 and D37.
