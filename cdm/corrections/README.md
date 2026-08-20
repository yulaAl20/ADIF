# Post-freeze corrections to the CDM evidence (D59)

The frozen v1.0 files are **not edited**. `cdm/annex_iii_transcription.csv`, `cdm/EXTRACTION.md` and the schema stay exactly as they were at `freeze-v1.0`. The corrections live here so that both the original evidence and the correction remain inspectable.

| File | What it corrects |
|---|---|
| `annex_iii_transcription_v1.1.csv` | Adds the missing point **(l)**, so the denominator is 12 points, not 11. Point (l) is a paraphrase until its verbatim text is copied from the OJ. Corrects the field references for (c) `dataCarrierStandard` → `gtin`, (g) `operatorIdentifier` → `manufacturerOperatorId`, (h) and (i) (singular → plural), and fills the blanks for (a), (d), (e), (f), (j) and (k). |
| `reference_attribute_set.csv` | The constructed reference attribute set that D12 describes but v1.0 never materialised. Every row has a clause and the CDM field (if any) that covers it. |

Run `python -m scripts.coverage_report` to recompute the coverage figures.

Results on 2026-10-12:

| Measure | Coverage |
|---|---|
| Annex III lettered points | 11/12 (91.7%) |
| **Core reference attributes (O2 figure)** | **27/30 (90.0%)** |
| With Art 5(1) parameter aspects (sensitivity only) | 34/46 (73.9%) |

**Scope refinement (D66).** D12 said the reference set would also draw on the Commission's preparatory documentation and CIRPASS outputs. That set was never built or evaluated. The coverage claim is narrowed to what was actually used: a **research-defined regulatory reference set** drawn from primary legal text only (ESPR Annex III (a)–(l), Art 7(5) and Art 5(1), and Reg. 1007/2011).

Report it as a scope refinement of D12, not as though a CIRPASS-inclusive set had been evaluated. Two different measures must not be equated:
- coverage of the 12 Annex III points;
- coverage of reference attributes.

Neither is coverage of a legally mandatory apparel attribute list, because none exists yet. The CDM itself is described as synthesised from ESPR requirements, with supporting GS1 (EPCIS 2.0), UNTP and textile-fibre (Reg. 1007/2011) semantics.

**The four mandatory fields** (productFamily, productIdentifier, manufacturerOperatorId and fibreComposition) are a **research-defined minimum** for evaluation. They are not a legally confirmed textile DPP obligation, because the textiles delegated act has not been adopted.
