# CDM Extraction Record

**Status: COMPLETE.** Started 2026-08-18, completed 2026-10-05.
**Result:** `cdm_v1.0.schema.json` — 54 fields, 4 mandatory, every field carrying
its source clause in `x-adif`. Audit trail in `provenance.csv`; conflict
resolution and precedence in `ALIGNMENT.md`.

Procedure followed (methodology.md, Layer 2): competency questions → term
extraction per source → alignment table → precedence rules → alias vocabulary.

---

## Sources and their contribution

| Source | Fields | How it was read |
|---|---|---|
| ESPR (EU) 2024/1781 | 35 | Annex III ¶1 (a)–(k) transcribed verbatim, then expanded through Art. 7(5) and Art. 5(1) where point (a) refers out |
| UNTP DPP | 11 | Specification site, 2026-10-05 |
| GS1 EPCIS 2.0 | 4 | `ref.gs1.org/standards/epcis/2.0.0/` |
| Regulation (EU) 1007/2011 | 1 | Textile labelling — `fibreComposition` |
| ADIF (no external source) | 3 | `productFamily`, `colour`, `size` — the contribution, marked `ARTEFACT` not `VERIFIED` in provenance.csv |

Annex III coverage: **11/11 lettered points**. The verbatim transcription is
preserved in `annex_iii_transcription.csv`.

---

## Correction this extraction produced: Annex I vs Annex III

Your proposal, research_objectives, methodology.md and Chapter 3 all said the
CDM synthesises **"ESPR Annex I"**. Verified against the consolidated
regulation, that is the wrong annex for DPP data.

- **Annex III** is the Digital Product Passport annex, headed "(referred to in
  Articles 9 to 12)". Art. 9(2)(a) states that delegated acts specify the data
  "pursuant to Annex III".
- **Annex I** is the list of **product parameters** behind performance and
  information requirements (Art. 5, 6, 7).

Both are used, for different things, and `provenance.csv` distinguishes them.
**Amend every document that says "Annex I" when it means DPP data elements.**
Keep "Annex I" where you mean sustainability parameters.

---

## Verified citations this extraction produced

Each replaces an assertion with a clause.

| Claim | Clause |
|---|---|
| DPP data must be open-standard, interoperable, machine-readable and transferable **"without vendor lock-in"** | Art. 10(1)(d) |
| Delegated acts specify whether a passport is at **model, batch or item** level | Art. 9(2)(d); Art. 10(1)(f) |
| A unique product identifier "also enables a web link to the digital product passport" | Art. 2(30) |
| The first working plan must prioritise "textiles, in particular garments and footwear" | Art. 18(5)(c) |
| Substances-of-concern field list (IUPAC, EC number, CAS, location, concentration, safe use, end-of-life) | Art. 7(5)(a)–(e) |
| Identifiers comply with ISO/IEC 15459-1 to -6 | Annex III ¶2; Art. 10(1)(c) |
| Commission to accompany delegated acts with SME tools and guidelines | Art. 22 |
| Registry to be set up by 19 July 2026 | Art. 13(1) |

The "vendor lock-in" clause is the strongest available support for the thesis
title: vendor neutrality is a regulatory requirement, not the researcher's
framing.

Art. 9(2)(d) is the strongest support for ADID's levels — and note what it does
*not* do. It establishes that the levels exist; it says nothing about how to
structure or address them. That silence is the gap ADID fills.

---

## Resolved since the first draft of this file

| Question | Resolution |
|---|---|
| Were six EN DPP standards published 27 May 2026? | **Yes.** Verified 2026-10-06. See `ALIGNMENT.md` — it changes research gap #6 and the ADID conformance decision. |
| Is the textile delegated act adopted? | **No.** Still unadopted; no binding attribute list exists. Verified 2026-10-06. This vindicates the conservative 4-field mandatory set. |
| Which UNTP version? | **None published.** The specification states it is "under development and not ready for implementation." Cite by access date. |

---

## Still outstanding

- **Kaggle dataset licence** — unconfirmed. Schema A cannot be cited until
  checked on the dataset page.
- **ISO 3166 spot-check** — all 249 alpha-2 codes are in
  `vocabularies/signatures.yaml`, compiled from knowledge rather than from the
  ISO register. Verify against the ISO Online Browsing Platform before the
  freeze.
- **EPCIS event envelope is deliberately excluded.** `eventTime`, `action`,
  `eventID`, `sensorElementList` and the event types describe *events*; a
  manufacturer spreadsheet row is a *product*. Only the EPCIS fields a product
  export plausibly carries were adopted. Record this as a scoping decision —
  "synthesises EPCIS 2.0" could otherwise be read as claiming full event support.

---

## Post-freeze correction (2026-10-12, D59)

The line "Annex III coverage: **11/11 lettered points**" above is preserved as written at freeze. It is **superseded**: Annex III ¶1 has twelve points, (a)–(l), and point (l) (the DPP service provider hosting the back-up copy) was missing from the transcription. Several field references in `annex_iii_transcription.csv` were also wrong. See `cdm/corrections/`. The corrected figures are 11/12 Annex III points and 27/30 core reference attributes (90.0%), from `python -m scripts.coverage_report`.
