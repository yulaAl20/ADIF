# Second design iteration: strict cascade vs evidence-aware reranking (D54–D57)

Status: **designed and checked on development data only. Not evaluated on held-out data.**
The v1.0 strict cascade, its configuration and its held-out results are unchanged and remain the evaluated artefact.

## D54 — Why a second iteration

The v1 decision rule (D17) accepts the first stage whose best candidate clears its threshold, and nothing later can overturn it. On the six development schemas this produced two kinds of error:

| Error kind | Development examples | v1 behaviour |
|---|---|---|
| Header match that the values contradict | `has_batch_no` = 1 → batchNumber; `weight_uom` = Kg → netWeight; `description` (marketing copy) → productFamily; `Style_No` holding GTINs → productIdentifier (exact alias) | Accepted. No later stage sees the column |
| Correct mapping lost | `x_studio_lot` lost its value candidate in a conflict and was dropped; `weight_per_unit` scored 80 against a threshold of 85; `co2e_kg` scored 73 | NO_MAPPING |

Lowering thresholds or adding aliases would trade one error kind for the other. The iteration therefore keeps all four matching techniques unchanged and replaces only the **decision** taken from their output.

## D55 — The v2 decision rule

Implemented in `src/matching/rerank.py`. It is selected by `matching.arbitration: rerank` in `config/ablation/rerank_v2.yaml`. The frozen `config/default.yaml` still selects `cascade`.

1. **Collect.** Gather candidates from every enabled stage, not just the first one to fire. Also run an exact alias lookup on the header after removing documented ERP custom-field prefixes (`x_studio_`, `x_`, `custom_`). For numeric columns only, also try it after removing a trailing unit token (`_kg`, `_pct`).
2. **Validate** each candidate against the column's values. These are the annotation rulebook's R3 principles turned into checks, and none of them names a specific header:
   - **R3.1 A flag is not a value.** All values are 0/1/true/false, so the candidate is rejected for every field.
   - **R3.2 A unit is not a quantity.** All values are units ("kg", "pcs"), so the candidate is rejected except for a `unit`-kind field. A quantity field also requires numeric values.
   - **R3.3 A label is not an identifier.** For `code`-kind fields, a median of three or more words per value is rejected as prose.
   - **Data overrides header.** Suppose the header suggests field F, F has a value signature, and F's signature fits 20% or less of the values. If another field's signature also clears the value threshold, F is rejected. This is the only rule that can overturn an exact alias.

   Field kinds live in `config/rerank/field_expectations.yaml`.
3. **Rank.** Candidates are ordered by:
   - Evidence tier, in the same order as v1: alias, derived alias, fuzzy, semantic, value, corroborated sub-threshold.
   - Then whether the values agree with the header.
   - Then score.

   Two adjustments apply. A fuzzy or semantic resemblance that the values do not support ranks below a field the values positively identify. A header score below threshold but at or above 70 survives only if the values corroborate it, either through the field's signature or through numeric values for a quantity field. Such a candidate is always flagged for review.
4. **Assign** one-to-one across the whole file, greedily in rank order, with NO_MAPPING always available. A column that loses its first choice takes its next *valid* candidate, never an invalid one.

Every decision writes its reason into `MappingRecord.notes`, for example: "productIdentifier rejected: the values do not fit productIdentifier (0% conform) but fit gtin (100%) — the data overrides the header."

## D56 — Development result (in-sample)

`python -m eval.compare_decision` scores both rules on the same stages: alias, fuzzy and value. Semantic is off in both, because the real model is not available in the build environment and the stub is never substituted.

| Schema | Cascade F1 | Rerank F1 |
|---|---|---|
| manufacturer_a | 0.833 | 1.000 |
| manufacturer_a_drift | 0.833 | 1.000 |
| manufacturer_b_erpnext | 0.667 | 0.880 |
| manufacturer_b_erpnext_drift | 0.741 | 0.880 |
| manufacturer_c_odoo | 0.762 | 0.818 |
| manufacturer_c_odoo_drift | 0.727 | 0.762 |
| **Macro P / R / F1** | 0.819 / 0.727 / 0.760 | 0.972 / 0.833 / 0.890 |

There were 14 column decisions that differed between the rules. The reranker was right in all 14, and no column that the cascade got right was lost.

**This is not an accuracy claim.** The rules were written after inspecting these same errors, so the figure is in-sample and optimistic. It shows the mechanism works as designed; it does not show how well it generalises.

Still wrong under v2:
- `variant_of` → should be productFamily; no stage proposes it.
- `item_group` / `categ_id` → should be productCategory; header scores are 75 and 77, and no value evidence is possible for free categories.
- `x_studio_po_ref`, `x_studio_wash`, `x_studio_ghg`, `x_stud` → should be mapped; no candidate above the floor.
- `supplier_gln` → manufacturerOperatorId; the gold standard says NO_MAPPING. See the inconsistency below.

Known residual risks, untested because development data has no instances:
- The size signature `\d{2,3}` matches whole-number gram weights, so `weight_g` = 180 would go to `size` under both rules.
- A constant 13-digit party GLN fits the GTIN signature.

**Vocabulary versus gold inconsistency, for the user to resolve:** `cdm/aliases_v1.0.yaml` lists `supplier gln` and `vendor code` as aliases of manufacturerOperatorId. The gold standard (R4.3) marks `supplier_gln` as NO_MAPPING because "a supplier need not be the manufacturer". Both are frozen. Record which one is authoritative; do not change either to move a score.

## D57 — Configuration parity (accuracy review, improvement 6)

- `src/api/main.py` used to load the base config only, which left the value stage off, and paired it with the stub embedder. It now loads the evaluated overlay. When the real model is not cached it switches the semantic stage off and never substitutes the stub. `/health` reports `matching_configuration`.
- The website already ran the evaluated overlay. Its `/admin` page now shows the decision rule, stages, model, overlay and fingerprint in use.
- `effective_fingerprint()` in `src/config.py` hashes the effective settings, including the expectation table. `source_sha256` hashes only the base file, so two runs citing `default.yaml` could differ.
- `ADIF_MATCHING_OVERLAY=config/ablation/rerank_v2.yaml` selects v2 in either interface for demonstration. The interface labels the session as the unevaluated second iteration.

## What must happen before any v2 accuracy figure is reported

1. **Semantic, on your machine.** Run `python -m eval.compare_decision --real-model` with all-MiniLM-L6-v2 cached. Then repeat with `semantic_query: enriched` (improvement 5) and keep whichever does better on development data.
2. **Freeze v2.** Freeze these files at tag `freeze-v2.0` and record their hashes:
   - `src/matching/rerank.py`
   - `config/ablation/rerank_v2.yaml`
   - `config/rerank/field_expectations.yaml`
3. **Recalibrate.** Refit the calibrator on development data with v2 selected, and write it to a separate file such as `config/calibrator_v2.json`. Leave the v1 file untouched. The current calibrator was fitted on v1 decisions.
4. **Evaluate on fresh held-out data.** The current held-out set has already been seen. Use new held-out data that neither rule was designed on (Sri Lankan manufacturer exports are the natural candidate). A rerun on the old held-out set can be reported only as a non-independent check.
5. **Report both iterations side by side.** v1 strict cascade (evaluated, frozen) against v2 evidence-aware reranking, on the same fresh data, with the same stages and model.

## Update (D63, D65): no fresh held-out data

No Sri Lankan manufacturer dataset could be obtained in the time available (D63). Step 4 above therefore cannot be carried out in this study.

The second iteration is reported as a **development-stage design with in-sample results only**, as future work. It makes no accuracy claim, and the evaluated v1.0 results stand as the study's findings.

The corrected alias vocabulary (D65, `cdm/aliases_v1.1.yaml`) is tested as its own condition, `rerank_v2_aliases_v1_1.yaml`, so its effect is not mixed with that of the decision rule. On development data it changes only `supplier_gln`, from manufacturerOperatorId (an alias match) to gtin (a value-signature match). Both are wrong against the answer key: a GLN-13 and a GTIN-13 share the same structure and check digit. Development F1 is unchanged at 0.890, and the rule was not tuned further.
