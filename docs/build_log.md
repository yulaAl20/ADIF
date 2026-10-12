# Build log — development narrative

Source material for Chapter 4. This is the honest account of how the artefact
was built, including what went wrong, because the failures are the parts that
carry evidential weight.

## Increment sequence

Built in the order project.md §9 specifies, with one deviation. §9 placed B10
(evaluation harness) before B11 (value stage); that ordering was kept, and it
mattered: it meant the harness existed to detect the Stage 4 problems below.

| Increment | Delivered |
|---|---|
| B0–B1 | Repository, config loader, provenance capture, `/health`, seal test |
| B2 | M1 ingestion, M2 schema analysis |
| — | **CDM v1.0 derived** (Objective 2) — see `cdm/EXTRACTION.md`, `cdm/ALIGNMENT.md` |
| B3 | M3 alias lookup, M7 cascade arbitration |
| B4 | M4 fuzzy, M5 semantic |
| B5 | M7 calibrated confidence |
| B6 | M10 validation, M11 ADID, M12 JSON-LD |
| B7–B8 | M13 REST API, M8 review interface |
| B9 | M9 template store with drift reporting |
| B10 | M14 instrumentation, evaluation harness |
| B11 | M6 value-based matching |

## Defects found during development

Each of these would have corrupted results silently rather than failing loudly.
They are worth reporting in Chapter 4 or 6: they are evidence the artefact was
tested rather than merely written, and three of them are findings in their own
right.

**1. Type inference destroying identifiers.** pandas' default inference turned
GTIN `0012345678905` into `12345678905` and style number `00742` into `742`,
irreversibly. Fixed by reading every column as text and deferring type inference
to the analyser, where a wrong guess costs a label rather than the data.

**2. Duplicate headers silently renamed.** pandas rewrote duplicate columns to
`origin.1` before FR-2.5's handling could see them, so the duplicate was reported
as a distinct column and `.1` leaked into the normalised form. Fixed by reading
the true header row first, consistently across all three input formats.

**3. Short alias captured a longer header via partial matching.** `partial_ratio`
scores any short string found inside a longer one at 100. The alias `po`
(purchase order) sits inside `fabric compostion`, so `purchaseOrderReference`
scored 100 against a fabric-composition column, won the conflict, and demoted
`Buyer_PO` — the column that was actually right. **Two wrong mappings from one
short alias, both at maximum confidence.** Fixed with a configurable minimum
length and length ratio for partial matching.

**4. Conflict resolution ignored evidence strength.** When two columns claimed
one CDM field, the tie broke on raw score alone. Alias hits and value hits both
score 100, so a column named `customs_tariff_number` — whose HS code `610910`
happens to be six valid hex characters — took the `colour` field from a column
named `colour_name`, on nothing more than appearing earlier in the file. Fixed by
ordering on stage precedence first (decisions.md D24).

**5. Value signatures that did not discriminate.** Three patterns matched far
more than intended: a carbon-footprint pattern with an optional unit matched any
number, a numeric-size pattern matched weights and prices, a hex-colour pattern
with an optional `#` matched any six hex characters. **A loose signature does not
merely fail to help — it actively destroys correct matches**, because its false
positive wins a conflict against a true positive. This is a direct argument for
the ablation ladder: a stage can make results worse, and a single aggregate score
would never show it.

**6. A calibrator fitted on one ablation condition cannot score another.**
Fitting on the full cascade yields almost no fuzzy observations, because the
alias stage absorbs most columns — so the `fuzzy_only` condition had no model and
the run crashed. Fixed by fitting across every condition, and by having the
calibrator refuse to borrow another stage's curve: uncovered stages report no
confidence and the run record names the gap.

**7. Thresholds derived from a meaningless embedder.** An early grid search ran
with the deterministic stub embedder, whose similarities are hash-derived noise,
and produced `semantic=70.0` — a number that looked entirely reasonable sitting
in a config file. Both tuning scripts now refuse to run without a real embedder
unless `--allow-stub` is passed explicitly.

**8. The family identifier derived from a GTIN.** The DPP endpoint fell back to
`productIdentifier` when no family field was mapped, producing
`adid:family = 0012345678905`. A GTIN identifies one colour-and-size combination,
so this made every variant its own family and collapsed the hierarchy ADID exists
to provide. Now a 422 with the reason, rather than a broken identifier
(decisions.md D9).

## Process corrections

**Schemas B and C reassigned from held-out to development (D23).** Three of the
signature defects above were found by inspecting those schemas' per-column
output. Every fix was correct, but each was found by looking at data destined to
be sealed — which is tuning on the evaluation set regardless of intent. The
schemas became development data and the held-out set was rebuilt from sources not
yet inspected. The result is a cleaner tuning/evaluation split than the original
three-schema plan had, and five schemas instead of three.

**Process rules encoded as tests.** Several tests assert discipline rather than
behaviour, so a lapse fails the build: `UnsetTunable` on underived thresholds,
the held-out seal grep, the refusal to label a run `EVALUATION` without a frozen
CDM and a fitted calibrator. Three of them caught real lapses during development,
including one of mine where a convenience script hardcoded the sealed path.

## Verification

116 tests. NFR evidence in `docs/nfr_verification.md`. Platform verification on
Windows/Python 3.12 and Linux/Python 3.13.
