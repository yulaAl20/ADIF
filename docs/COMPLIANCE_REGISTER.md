# Research compliance and objective-alignment register (updated with decisions D63–D66)

**Date:** 2026-10-12 · **Basis:** proposal §1.1–1.5, the 2026-10-12 external review, the frozen run records in `runs/`, and primary sources re-checked on 2026-10-12.

**Verdict.** The research is aligned with its objectives **as a design-science study that reports its own shortfalls**. It is not aligned if the thesis presents the gateway as meeting its accuracy targets, the registry as an EU registry, the CDM as covering legally mandatory apparel attributes, or the conversion as automatic. Every item below is either fixed in the software (with a decision number) or listed under "Still open" with the action it needs.

---

## 1. Objectives

| Objective (proposal §1.3) | Evidence | Status | What the thesis must say |
|---|---|---|---|
| **O1.** Identify frameworks and standards, and assess the gap | Ch2; `sources.md` | **Met, but the gap statement must be reframed** | Harmonised standards EN 18216 and EN 18219–EN 18223 now exist (Implementing Decision (EU) 2026/1736, 14 July 2026). "No unified DPP interoperability architecture exists" no longer holds. The gap is narrower: an apparel-specific schema-transformation workflow, a hierarchical product-grouping implementation, and a low-resource mapping approach designed for Sri Lankan apparel SMEs. |
| **O2.** Vendor-neutral CDM covering ≥80% of mandatory EU apparel attributes | 54-field schema, JSON-LD context, aliases, provenance. **New:** `cdm/corrections/`, `scripts/coverage_report.py` | **Met against a research-defined regulatory reference set (90.0%), with the correction and the scope refinement disclosed (D59, D66)** | No legally mandatory apparel attribute list exists, because the textiles delegated act is not adopted. Describe the CDM as synthesised from ESPR requirements, with supporting GS1, UNTP and textile-fibre semantics. The coverage set is primary regulatory text only, which narrows D12; no CIRPASS or preparatory-study set was evaluated. The v1.0 claim of 11/11 Annex III points is superseded by 11/12 (point (l) was omitted). Core reference coverage is 27/30 = 90.0%. Including the Art 5(1) aspects gives 34/46 = 73.9%, a sensitivity figure. Use "Annex III", not "Annex I". |
| **O3.** Three-level ADID, URI-based, GS1 Digital Link compatible, variant grouping, complete DPP from one call | ADID v1.0 (frozen); ADID v2 resolver (D51–D53); E1–E8 registry evaluation; **new** end-to-end passport demo (D60) | **Met by the post-freeze v2 design; GS1 conformance not claimed** | v2 is a proposed post-freeze design. Its identifiers are valid under its own grammar and parse under v1.0. That is not conformance with EN 18219, IEC 61406 or GS1 Digital Link. Variant and instance records carry syntactically valid GS1 Digital Links. Complete passports are shown by the end-to-end demo, not by the synthetic registry evaluation. |
| **O4.** Gateway: CSV/Excel/JSON, three-stage matching with confidence, ADID DPP records over REST | Gateway, API, website; D19 (four stages), D6 (calibrated confidence) | **Met with documented deviations** | Four stages, not three. Confidence is calibrated, not raw. The API now runs the evaluated configuration (D57). The workflow is **human-assisted**: a high confidence score does not guarantee a correct mapping, and alias (0.870) and fuzzy (≈0.43) mappings all go to review under D27. |
| **O5.** Evaluate on ≥3 realistic Sri Lankan schemas, measure five things, and compare against a one-to-one baseline | `runs/eval_20261010T071102Z.json` and template-reuse runs | **Partly met; scope revised (D63, D64)** | Evaluation was run and is transparent, but most targets were missed (§2). No Sri Lankan manufacturer dataset could be obtained within the time available. The evaluation is therefore controlled and synthetic: H1 is public fashion metadata (Kaggle), and H2 and H3 are constructed manufacturer-style schemas (D31). Use the revised scope statement in §5. Fuzzy-only is the primary computational baseline, subject to written supervisor approval (D64). |

## 2. Evaluation targets (verified against the run records)

| Target | Achieved | Outcome |
|---|---|---|
| Macro-F1 ≥ 0.85 | 0.628 (full cascade + value); 0.541 fuzzy-only; 0.062 semantic-only | Not met |
| Mandatory-field match ≥ 80% per applicable schema | H2 50%, H3 100% (Kaggle has no applicable mandatory fields, D36) | Not met consistently |
| ECE ≤ 0.10 | 0.054 | Met, with the small-sample caveats in D26 and D36 |
| Unchanged-field template reuse ≥ 95% (template from system output) | H2 3/6, H3 8/9 | Not met |
| New/changed-field F1 ≥ 0.80 | H2 0.500, H3 0.667 | Not met |

**How to present it.** The hybrid gateway is a working implementation. It improved measurably over the string-only rung (0.541 → 0.628). The evaluation exposed specific weaknesses in automated matching: distractor columns, header-only early exit and conflict demotion. It also showed where human oversight remains necessary. A missed target, reported transparently, is a legitimate finding. The second design iteration (D54–D57) responds to these weaknesses. It has not been evaluated on fresh held-out data and is not part of these figures.

## 3. Review items: verification and action

| # | Review finding | Verified? | Action (decision) |
|---|---|---|---|
| 1 | Annex III inventory incomplete; point (l) missing; wrong field reference for (c) | (c) is **confirmed** wrong (`dataCarrierStandard`, not a CDM field). Fields for (g), (h) and (i) are also misnamed. Point (l) is **consistent with** the back-up-copy duty (ESPR Art 10, recital 38) and with 2026/1778 storing a service-provider reference. Its verbatim text could not be retrieved here, so copy it from the OJ yourself. | Corrected transcription and reference set in `cdm/corrections/`. Frozen files untouched. Coverage script and test added. **D59** |
| 2 | Calibrator hash differs from D30 | **Resolved.** The repository file, converted to CRLF line endings, reproduces the D30 hash exactly. D30 hashed the Windows working copy (written by Python with CRLF); the repository holds LF. The coefficients are identical and no rerun is needed. | `src/integrity.py`, `python -m scripts.verify_freeze`, and an admin page that shows "Same content (line endings)". **D58** |
| 3 | Registry evaluation shows no complete CDM-valid passports | **Confirmed**, for two reasons. The synthetic records are incomplete. Also, a *family* passport cannot carry the two variant-level mandatory fields (productIdentifier, fibreComposition) by design. | `eval/e2e_passport_demo.py`: one invented, complete product goes through map → review → register → resolve, with seven explicit checks per passport. All six passports (1 family, 2 variants, 3 instances) pass. The demo also **found and fixed a real defect**: numeric fields (carbonFootprint) were stored as text and failed the CDM type. **D60** |
| 4 | Confidence not a guarantee; human-assisted rather than automatic | Agreed | Wording added to the website and README. The thesis must drop "guaranteed correctness" (proposal §1.1). **D62** |
| 5 | Website security | Agreed | Added: same-site redirect validation (the old check allowed `//evil.example`, an open redirect), sign-in throttling, upload size limit, uploads expiring after 2 h, an append-only access log on /admin, and HTTPS-only cookies via config. Not claimed: a security assessment. **D61** |
| 6 | Harmonised standards change the gap statement | **Verified:** Implementing Decision (EU) 2026/1736 (14 July 2026) lists EN 18216, 18219, 18220, 18221, 18222 and 18223. | Reframed on the website and in the README. Ch1 and Ch2 to be updated. **D62** |
| 7 | Textile requirements are forthcoming; the four mandatory fields are research-defined | **Verified** (secondary): the textiles delegated act is not adopted, with adoption indicated for 2027. | Stated in `cdm/corrections/README.md`, the README and the website. **D62** |
| 8 | EU registry under 2026/1778; the project's registry is a research registry | **Verified:** Implementing Regulation (EU) 2026/1778 of 16 July 2026, in force 6 August 2026. The registry stores identifiers, commodity code and a service-provider reference, registered by verified economic operators. | Website and README now say the project's registry is not the EU registry and not evidence of EU registration. **D62** |
| 9 | GS1: each size and colour needs its own GTIN | **Verified** on GS1's support portal: "Each product variation needs its own GS1 GTIN™", where a variation is each size, each colour, or each combination. | Upgrade the sources.md entry to primary. This supports the family level above variants. GS1 identification rules and ADID conformance remain separate claims. |
| 10 | ADID v2 conformance claim must stay open | Agreed; already the case (docs/ADID_V2_DESIGN.md §8, website) | No change |

## 4. Proposal wording that must change in the thesis

| Proposal text | Problem | Replace with |
|---|---|---|
| "measurably and automatically with **guaranteed correctness**" (§1.1) | Contradicted by the results and the design | "with a measurable, calibrated confidence per mapping and human confirmation" |
| "automatically converted" / "doesn't require manual setup" (§1.2) | Review is needed by design (D27) | "converted with automated proposals and human-assisted review" |
| "ESPR **Annex I**" (§1.3, §1.4, §1.5) | Wrong annex for DPP data | "ESPR Annex III (with Annex I parameters where point (a) refers out)" |
| "at least 80% of **mandatory** EU apparel attributes" (O2) | No legal list exists yet | "≥80% of a constructed reference attribute set (D12)", stating its basis |
| "three key standards … have not been combined into one … architecture" (§1.2) | Harmonised standards now exist | The reframed gap in §1, O1 |
| "established the legal basis to **require** DPPs for all textile and garment products" (§2.1.1) | ESPR enables the requirement; a delegated act imposes it | "established the legal basis on which a textiles delegated act will set DPP requirements" |
| "three stage matching engine" (O4, RQ4) | Four stages were built (D19) | Keep the RQ wording, and add the deviation to the Ch3 deviations table |
| "complete DPP registry" (O3, RQ3) | Could be read as the EU registry | "a research registry and resolver" |

## 5. Decisions taken and items still open

**Decided (2026-10-12):**

1. **Scope (D63).** No Sri Lankan manufacturer dataset could be found, and time is limited. Use this scope statement in Ch1 (§1.5), Ch3 and Ch6:

   > The framework is designed to address interoperability challenges relevant to Sri Lankan apparel SMEs. Its technical feasibility is evaluated using publicly available fashion product metadata and constructed manufacturer-style schemas representing heterogeneous apparel data structures. The evaluation is controlled and synthetic rather than an empirical assessment of operational Sri Lankan factories. Accordingly, the findings demonstrate prototype feasibility and comparative matching performance but do not establish industrial generalisability.

   The second iteration (D54) therefore has no fresh held-out set. It stays a development-stage design and is reported as future work, with no accuracy claim.
2. **Baseline (D64).** Fuzzy-only stays the primary computational baseline. It is a stronger and more informative comparator than exact matching, and the ablation ladder isolates what alias, semantic and value matching each add. **Get the supervisor's written approval.** A deterministic alias-only baseline is prepared but not run (`config/ablation/alias_only_baseline.yaml`, registered as a supplementary condition). Run it only if the supervisor requires it, and report it as added after the main evaluation. The existing results (0.541 and 0.628) are unchanged.
3. **supplier_gln (D65).** The answer key stays authoritative (R4.3: a supplier need not be the manufacturer). The frozen `aliases_v1.0.yaml` is not edited. `cdm/aliases_v1.1.yaml` removes `supplier gln`, and, under the same rule, `supplier code`, `vendor code`, `supplier` and `vendor` from the manufacturer fields. It is used only by the second-iteration overlay `rerank_v2_aliases_v1_1.yaml`.
   - **Development finding:** without the alias, the value stage maps `supplier_gln` to `gtin`, because a GLN-13 and a GTIN-13 share the same structure and check digit. The column is still wrong, now for a different, documented reason. Development F1 is unchanged. It was not tuned further; this is a limitation of value signatures for party identifiers.
   - **Viva example:** the evaluation exposed a semantic weakness in the vocabulary, and the correction was principled. The answer key was not altered to raise the score.
4. **Reference set (D66).** The coverage claim is narrowed to the research-defined regulatory reference set actually built. This is a scope refinement of D12; no CIRPASS-inclusive set was evaluated. Annex III is corrected to 12 points, with (l) recorded as an identified coverage gap. Annex III point coverage (11/12) and attribute coverage (27/30) are reported as separate measures.

**Still open:**

1. **Supervisor's written approval** of the baseline (D64) and of the scope statement (D63).
2. **Annex III (l) verbatim.** Copy the exact wording from the OJ PDF into `cdm/corrections/annex_iii_transcription_v1.1.csv` and change its status from `PARAPHRASE_PENDING_VERBATIM_CHECK`.
3. **D31 [FILL IN].** Check the H2 headers against Dolibarr documentation and record any differences.
4. **Unverified README items.** The Kaggle dataset licence, and a spot-check of the ISO 3166 list against the ISO OBP.
5. **sources.md updates.**
   - Mark 2026/1736 and 2026/1778 as primary and verified.
   - Add the GS1 GTIN source as primary.
   - Mark the registry as live rather than forthcoming.
   - Record the Annex III (l) correction.
6. **Ethics statement.** Say "privacy-aware design and prototype access controls", not "secure" or "certified". State that all demonstration data is invented, that H2 and H3 were AI-compiled (D31), and that no personal data was processed.
7. **Low-observation calibration.** The semantic curve rests on 2 observations (D26). Report it as a limitation.
8. **Second iteration (D54).** Report it as a development-stage design with in-sample development results only. Optionally run `--real-model` on your laptop for completeness. Without fresh held-out data it supports no accuracy claim.

## 6. Decisions added by this check

| ID | Decision |
|---|---|
| D58 | The calibrator hash mismatch is a line-ending difference (CRLF at freeze vs LF in the repository); the content is identical. The integrity check reports this as its own status. The D30 values are not edited. |
| D59 | Annex III correction: 12 points; (l) recorded as an acknowledged v1.0 omission. Field references corrected. The reference attribute set is materialised. Coverage is computed: 11/12 points, 27/30 core attributes (90.0%), 34/46 with Art 5(1) aspects. Frozen files are untouched. |
| D60 | End-to-end complete-passport demonstration, kept separate from the registry evaluation. Mandatory fields are checked by level. Numeric CDM fields are converted from text at registration. |
| D61 | Website prototype safeguards: redirect validation, sign-in throttling, upload limit, upload expiry, access log, optional HTTPS-only cookies. No security assessment is claimed. |
| D62 | Claims reframed: the gap in light of EN 18216 and 18219–18223; a research registry, not the EU registry (2026/1778); a research-defined mandatory minimum; confidence is not a guarantee; human-assisted interoperability. |
| D63 | Evaluation scope revised: no Sri Lankan manufacturer data. The evaluation is controlled and synthetic and shows prototype feasibility and comparative matching performance, not industrial generalisability. |
| D64 | Fuzzy-only stays the primary computational baseline, pending written supervisor approval. A deterministic alias-only baseline is prepared as a contingency and not run. |
| D65 | The answer key stays authoritative for supplier_gln. The alias vocabulary is corrected in a new version, `aliases_v1.1.yaml` (supplier/vendor role aliases removed), used only by the second iteration. Frozen v1.0 is untouched. |
| D66 | Coverage claim narrowed to the research-defined regulatory reference set, as a scope refinement of D12. Annex III point coverage and attribute coverage are reported separately. |

## Sources checked on 2026-10-12

- [Commission Implementing Decision (EU) 2026/1736: harmonised standards for DPP (EUR-Lex)](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ%3AL_202601736)
- [Commission Implementing Regulation (EU) 2026/1778: DPP registry (EUR-Lex)](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202601778)
- [GS1 support: how many GTINs for sizes and colours](https://support.gs1.org/support/solutions/articles/43000734083-how-many-gs1-gtins-do-i-need-when-i-have-a-product-with-many-sizes-and-colours-)
- [Regulation (EU) 2024/1781 (ESPR), EUR-Lex](https://eur-lex.europa.eu/eli/reg/2024/1781/oj/eng). The Annex III text was not retrievable with the tools used, so point (l) wording is pending.
- [ESPR Atlas: textiles delegated act status](https://espratlas.com/sectors/textiles/) (secondary)
