# sources.md — the honesty ledger
**Last updated:** 2026-10-11
**Supersedes:** the 2026-10-08 revision. Three rows in the 2026-08-06 version were **overturned** by later verification; they are listed in §0 rather than quietly deleted, because a ledger that erases its own errors is not a ledger.

**Status key**
- **VERIFIED — PRIMARY** — read directly from the issuing body's own text (regulation, standard, specification, paper) in one of these sessions, with a working link.
- **VERIFIED — SECONDARY** — corroborated across independent third-party sources with working links, but the primary document was not read. Usable; say "reportedly" in the thesis, or upgrade it before submission.
- **CARRIED** — taken from the original supervisor-approved proposal's reference list. Not independently re-checked in any of these sessions.
- **UNVERIFIED** — stated from general model knowledge, checked against no primary source at all. **Treat as flagged. Do not cite confidently until you have checked it yourself.**
- **OVERTURNED** — previously recorded here as true, later found to be wrong. Kept visible deliberately.
- **REJECTED** — found during research and deliberately not used, because the sourcing was not good enough.

A claim being written confidently elsewhere in this project — in a chapter, in project.md, in methodology.md, in a code comment, **in the web interface's public text** — does **not** mean it is verified. This file is the only record that does.

---

## 0. What this revision overturns

| Previously recorded | Now | Consequence |
|---|---|---|
| "ESPR textile delegated act still pending; adoption expected ~2026–27" — recorded VERIFIED | **Confirmed still pending.** The row stands, but a *different* source found in August claiming the textile act was "already finalised and stable as of 2026" is **wrong and must not be cited.** | Favourable. The CDM's small mandatory set and D12's constructed reference set are both now justified rather than merely cautious |
| "UNTP current version 0.6.0 (maintained), 0.7.0 (public review)" — VERIFIED | **OVERTURNED.** The UNTP specification site states the content "is under development and is not ready for implementation" and publishes **no version number** on its about page. | Cite UNTP by **access date**, not version. Add a limitation: eleven of the 54 CDM fields derive from a specification its own authors call not-ready |
| Research gap #6: the key standards "have never been realised in one unified transformation architecture" | **OVERTURNED by the EN 18xxx series.** EN 18223:2026 defines a shared data-model container. | **Gap #6 must be restated** before more of Ch2 is written. The restated gap is stronger — see the EN rows below and methodology.md §6 |

**Changes in this revision (2026-10-11):** the Kaggle licence moved from UNVERIFIED to verified; the `styles.csv` column list was read after the freeze as D18 requires; the held-out schemas H2 and H3 were built from **unverified** provenance and are now recorded as such; four new rows were added (tech-pack vocabulary, the `styles.csv` data defect, the software-evaluation citations, and the hosting claims).

---

## 1. Regulation — ESPR (EU) 2024/1781

All rows below were read from the consolidated text at `eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX%3A02024R1781-20240628`. Primary source, not a summary.

| Claim / source | Status | Where used | Reference / note |
|---|---|---|---|
| ESPR regulation (EU) 2024/1781 — official text | VERIFIED — PRIMARY | Ch1, Ch2, Ch3, references, web interface "problem" text | eur-lex.europa.eu/eli/reg/2024/1781/oj/eng |
| **Annex III, not Annex I, is the DPP data annex.** Art. 9(2)(a): delegated acts specify the data to be included "pursuant to Annex III". Annex III is headed "Digital product passport (referred to in Articles 9 to 12)" | VERIFIED — PRIMARY | **Correction needed in Ch1, Ch2, Ch3, methodology.md, research objectives** | Annex I is the product-parameters list for performance and information requirements (Arts. 5, 6, 7). Both are relevant; only Annex I is currently cited |
| Art. 10(1)(d): DPP data must be open-standards-based, interoperable, machine-readable, structured, searchable and transferable **"without vendor lock-in"** | VERIFIED — PRIMARY | Ch1 §1.1, §1.2 — replaces an asserted motivation with a citation | **The regulation itself mandates vendor neutrality.** Strongest available support for the thesis title, currently uncited |
| Art. 9(2)(d) and Art. 10(1)(f): delegated acts specify whether the DPP is at **model, batch or item** level | VERIFIED — PRIMARY | Ch3 ADID justification, FR-11.6, decisions.md D22 | The regulation establishes that the levels exist but not how to **address** them — the gap ADID fills. Load-bearing for the contribution claim |
| Art. 2(30): the unique product identifier "also enables a web link to the digital product passport" | VERIFIED — PRIMARY | Ch3 ADID URI rationale | Supports the URI-based identity approach |
| Art. 18(5)(c): the first working plan must prioritise "textiles, in particular garments and footwear" | VERIFIED — PRIMARY | Ch1 §1.1 | Replaces industry-blog sourcing for the textiles-are-a-priority claim |
| Art. 7(5)(a)–(e): substances-of-concern field list — IUPAC name, other names, EC number, CAS name and number, location in the product, concentration, safe-use instructions, end-of-life information | VERIFIED — PRIMARY | CDM extraction, `cdm/provenance.csv` | A directly citable, clause-level field list |
| Art. 5(1)(a)–(p): the sixteen product aspects | VERIFIED — PRIMARY | CDM extraction | The Annex I parameter families |
| Annex III ¶2: identifiers comply with ISO/IEC 15459-1 to -6 | VERIFIED — PRIMARY | Ch2, Ch3 | Relevant to the ADID conformance argument |
| Art. 22: the Commission is to accompany delegated acts with digital tools and guidelines for SMEs | VERIFIED — PRIMARY | Ch1 SME framing | |
| Art. 13(1): registry to be set up by 19 July 2026 | VERIFIED — PRIMARY | Ch1, scope exclusion | |
| **Full verbatim text of Annex III ¶1, points (a) to (k)** | **NOT YET READ IN FULL** | The reference attribute set behind the ≥80% coverage claim | Points (b), (c), (g), (h), (i) confirmed via Arts. 10 and 12. **The remainder must be transcribed directly from the regulation, not paraphrased from any summary — including mine.** `cdm/ANNEX_III_TEMPLATE.csv` exists for this. **Priority 1** |
| **Textile delegated act is NOT adopted.** Stakeholder consultation in progress; adoption expected 2025–2026; mandatory compliance expected 2027–2028. No binding list of mandatory DPP attributes for textiles exists; the categories circulating publicly come from the Commission's preparatory study, not from law | VERIFIED — SECONDARY | Ch1, Ch2, and the ≥80% coverage claim | Resolves the August contradiction. **Upgrade to primary** against the Commission's delegated-acts register before submission. Sources: esprregistry.com/textile-delegated-act-tracker/ ; cosh.eco/en/articles/eu-digital-product-passport-espr-explained-fashion-textiles |
| **EU DPP Registry reportedly live from 20 July 2026; Implementing Reg. (EU) 2026/1778 applies from 6 August 2026** | **UNVERIFIED** — secondary sources only, not re-checked | Ch1 framing | If true, **Ch1 must not describe the registry as forthcoming.** The scope exclusion stands either way. Check the Commission's own announcement |

---

## 2. European standards — CEN/CENELEC JTC 24

Published 27 May 2026; harmonised 15 July 2026. Two further standards completed formal voting on 16 July 2026. **This series did not exist when the proposal was written, and it is the single most consequential development for this thesis.**

| Claim / source | Status | Where used | Reference / note |
|---|---|---|---|
| Six DPP standards published 27 May 2026 by CEN/CENELEC JTC 24 | VERIFIED — SECONDARY | Ch1, Ch2, **research gap #6 restatement** | regenstudio.world/blog/dpp-system-standards/ ; wiot-group.com/think/en/news/cen-cenelec-six-eu-dpp-standards-en-18xxx/ |
| **EN 18219:2026** — unique identifiers; permits **five** schemes: GS1 Digital Link URI, **IEC 61406 self-issued links**, W3C DIDs, RFID/2D identifiers, DOIs | VERIFIED — SECONDARY | Ch3 ADID conformance, decisions.md D9/D22 | Catalogue entry: standards.iteh.ai/catalog/standards/cen/2291b0e4-6061-45e2-a37c-a52d911e2b9d/en-18219-2026 |
| EN 18220:2026 data carriers · EN 18216:2026 data exchange (REST over HTTPS/TLS) · EN 18221:2026 storage and persistence · EN 18222:2026 lifecycle APIs · EN 18223:2026 system interoperability / shared data-model container | VERIFIED — SECONDARY | Ch2 standards landscape | EN 18216's REST-over-HTTPS choice is **convergent with the artefact's own API design**, which was fixed before publication |
| EN 18239 (access rights, security, confidentiality) and EN 18246 (data authentication, integrity) completed formal voting 16 July 2026 | VERIFIED — SECONDARY | Ch2, scope exclusions | Access control is an explicit scope exclusion; cite these as the standards that cover what ADIF does not |
| **The published standards do NOT specify identifier granularity**, and do **NOT** specify product attributes — "attributes belong to sectoral acts, not JTC 24 standards" | VERIFIED — SECONDARY | **Restated gap #6**, Ch3 contribution claim, decisions.md D22 | This is what keeps the contribution alive. The standards specify the plumbing; no apparel attribute model, no granularity definition, no open SME implementation exists |
| **Full text of EN 18219:2026, and the IEC 61406 profile requirements** | **NOT READ** | The ADID conformance claim | A paid CEN standard, not on the open web. **Ask your university library about CEN access.** Until read, `GET /adid/conformance` records EN 18219 with `"claim": null` and IEC 61406 as a *candidate* scheme. **Priority 2** |

---

## 3. Identification standards — GS1

| Claim / source | Status | Where used | Reference / note |
|---|---|---|---|
| GS1 Digital Link and EPCIS 2.0 — current standard pages | VERIFIED — PRIMARY | Ch2, Ch3, references | ref.gs1.org/standards/digital-link/ ; gs1.org/standards/epcis |
| A GTIN identifies one specific colour+size combination (variant level), never a whole design | **UNVERIFIED** — professional/industry knowledge, not checked against GS1's General Specifications | **Load-bearing** for the ADID design (decisions.md D9), Ch3, methodology.md, **and now stated on the web interface's home and How It Works pages (D40)** | High confidence, but it supports a Critical-severity design decision, anchors an appendix conformance argument, and is now public-facing text. It deserves a primary-source check against the GS1 General Specifications before the interface is published. **Priority 3** |
| SGTIN = GTIN + serial number, identifies one physical instance | **UNVERIFIED** — same basis | Ch3, methodology.md, web interface "single item" level | Same action. Check against GS1 / EPCIS primary documentation |
| ADID's URI grammar conforms to GS1 Digital Link path syntax | **NOT TESTED** | Ch3 appendix | Must be settled by running candidate URIs against GS1's own validator, not by assertion (project.md §13). Until then the claim is **"compatible extension", not "compliant"** — and the EN 18219 finding suggests IEC 61406 may be the right target instead. The web interface states that ADID is not an official standard and that its example addresses are illustrative |
| GS1 DPP application-standard identifier mapping | **UNVERIFIED** | Ch2 | Noted during CDM work; not pursued. Low priority unless the conformance claim moves back to GS1 |

---

## 4. Specifications and data sources used in the CDM and the evaluation

| Claim / source | Status | Where used | Reference / note |
|---|---|---|---|
| **UNTP is under development with no published version number.** Site states: "this content is under development and is not ready for implementation" | VERIFIED — PRIMARY | Ch2 §2.2/2.3, CDM provenance, references | uncefact.github.io/spec-untp/docs/about/ — **supersedes** the 0.6.0 / 0.7.0 row in the earlier revision. **Cite as: UN Transparency Protocol, under development, accessed 2026-10-06.** Add a limitation: 11 of 54 CDM fields derive from it |
| Regulation (EU) 1007/2011 — textile fibre names and labelling | VERIFIED — PRIMARY | CDM `fibreComposition`, Stage 4 value signatures | The source for the controlled fibre-name vocabulary |
| ERPNext Item doctype field list — source material for the development schema `manufacturer_b_erpnext` | VERIFIED — PRIMARY | methodology.md §4.1 | Manufacturer-side documentation, per the D3 circularity guard. Record the exact documentation URL and access date in Ch3 |
| Odoo `product.template` field list — source material for `manufacturer_c_odoo` | VERIFIED — PRIMARY | methodology.md §4.1 | Same. Record URL and access date |
| **Dolibarr product field list — used for held-out schema H2, but NOT read from Dolibarr** | **UNVERIFIED** | H2 `heldout_h2_dolibarr`, decisions.md D31 | H2's headers were compiled by an AI assistant from its recollection of Dolibarr's `llx_product` and extrafield naming, **not from the documentation or a live instance**. Check against a Dolibarr instance or its documentation and record every difference before H2 is cited as a Dolibarr export. **Priority 4** |
| **Buyer tech-pack vocabulary — used for held-out schema H3** | **UNVERIFIED** | H3 `heldout_h3_techpack`, decisions.md D31 | H3's headers follow typical tech-pack vocabulary as recalled by an AI assistant, **not a specific buyer's real document.** The circularity guard (D3) asks for manufacturer-side documents; compliance is argued, not proven. State this in Ch3 |
| ISO 3166-1 alpha-2 country code list used in the value-signature vocabulary (249 codes) | **UNVERIFIED** | Stage 4 value matching, CDM validation, **used in the evaluation** | **Compiled from model knowledge, not from the ISO register.** A wrong code silently accepts bad data and silently rejects good data. Verify against the ISO Online Browsing Platform. **Priority 5** |
| CIRPASS-2 project runs 2024–2027; sector pilots include textiles | VERIFIED — PRIMARY | Ch1 §1.1, Ch2 §2.3, references | cirpass2.eu/project-results/ |
| Fashion Product Images Dataset exists on Kaggle, uploaded by paramaggarwal, ~44,000 products, metadata in `styles.csv` | VERIFIED — PRIMARY | Held-out schema H1, methodology.md, decisions.md D15/D18 | kaggle.com/datasets/paramaggarwal/fashion-product-images-dataset. File actually used: `fashion-dataset/styles.csv`, 44,446 data rows, zip SHA-256 in D18 |
| **Licence terms for the above dataset: MIT** | **VERIFIED — as reported by the Kaggle CLI (`License(s): MIT`), 2026-10-10** | Held-out schema H1, `docs/licences.md` | Reported by Kaggle's own API output. **Confirm once on the dataset page in a browser and cite that page** before final submission |
| **`styles.csv` column list** | **READ post-freeze, as D18 requires** | Ch6 | `id, gender, masterCategory, subCategory, articleType, baseColour, season, year, usage, productDisplayName` (10 columns). Prior awareness of a `masterCategory` field, from before the freeze, is declared contamination |
| **`styles.csv` has malformed rows** | VERIFIED — by running the repair script | decisions.md D32, Ch6 limitations | 22 rows have an unquoted comma in the last column (first at source line 6044), giving 11 fields against a 10-column header. A strict reader refuses the file. Repaired outside the frozen system; checksums in D32 |

---

## 5. Methodology and technique literature

| Claim / source | Status | Where used | Reference / note |
|---|---|---|---|
| Peffers et al. (2007) DSRM — full citation and DOI | VERIFIED — PRIMARY | Ch2 §2.2, Ch3, methodology.md | doi.org/10.2753/MIS0742-1222240302 |
| Gregor & Hevner (2013) knowledge contribution framework | VERIFIED — PRIMARY | Ch2 §2.2, Ch3, methodology.md | doi.org/10.25300/MISQ/2013/37.2.01 |
| Venable, Pries-Heje & Baskerville (2016) FEDS | VERIFIED — PRIMARY | Ch3 §3.1, methodology.md, software evaluation plan | doi.org/10.1057/ejis.2014.36 |
| Gregor & Hevner's survey found "exaptation" in 3 of 13 sampled DSR papers | VERIFIED, **but secondhand** | Ch2 §2.2 | Same DOI as above, but the figure came from a search snippet, not from reading the primary text. **Re-confirm by reading the paper before it goes into a submitted chapter** |
| Sentence-BERT (Reimers & Gurevych, 2019) | VERIFIED — PRIMARY | Ch2 §2.2/2.3, references | aclanthology.org/D19-1410/ |
| RapidFuzz's canonical repository is github.com/rapidfuzz/RapidFuzz | VERIFIED — PRIMARY | References | Moved from a personal repo; the old URL is stale |
| Hevner et al. (2004) — seven guidelines, three-cycle view | CARRIED | Ch2, Ch3, methodology.md, software evaluation plan | DOI carried from the original proposal reference list |
| **Brooke (1996), System Usability Scale, and the "about 68 is average" benchmark** | **UNVERIFIED** | `docs/software_evaluation_plan.md` (only if the user study runs, D38) | Named from model knowledge. Find the original citation and a source for the benchmark before use |
| **Rahm & Bernstein (2001) taxonomy, and the "hybrid beats single strategy" finding** | CARRIED | Ch2, Ch3 — cited as **direct justification for the entire four-stage architecture** | Not independently read. This is the justification for your core design choice, not a minor supporting citation. **Read the actual paper. Priority 8** |
| Parciak et al. (2024) — LLM schema-matching findings | CARRIED | Ch2 §2.3 | Not re-checked |
| Jæger & Myrold (2023) — EPCIS textile case studies | CARRIED | Ch2 §2.3 | Not re-checked |
| Hugging Face `all-MiniLM-L6-v2` — training details, offline capability | CARRIED | Ch2, Ch3 | Not re-checked. The **model revision hash** (`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`) is pinned in `config/default.yaml` and recorded in every run record, which is the reproducibility claim that actually matters |
| European Commission (2022) DPP feasibility study | CARRIED | Ch1, Ch2 | Not re-checked |

---

## 6. Context and justification statistics

| Claim / source | Status | Where used | Reference / note |
|---|---|---|---|
| **"Apparel = 44%+ of Sri Lanka's total export earnings"** | CARRIED (Export Development Board, 2023) | Ch1 §1.1 | **The single most load-bearing statistic in the whole justification section, and it is unchecked. Priority 6** |
| "~92 million tonnes of textile waste generated annually" | CARRIED (Global Fashion Agenda & BCG, 2017) | Ch1 §1.1 | Not re-checked |
| "Global clothing production roughly doubled in the two decades to 2020" | CARRIED (Ellen MacArthur Foundation, 2017) | Ch1 §1.1 | Not re-checked |
| Sri Lankan SME suppliers hold their own GS1 prefixes / GTINs | **UNVERIFIED, AND UNRESOLVED AS A DESIGN QUESTION** | project.md §13 GTIN fallback decision | Still an open decision, and it depends on a fact about the Sri Lankan market that nobody has checked. If SMEs typically do *not* hold prefixes, the ADID self-issued-link approach is **strengthened** — which would be worth saying |
| "81% of European companies lack structured lifecycle data required for DPP compliance" (KPMG survey, via an industry blog) | **REJECTED** | Not used anywhere | Thirdhand — a vendor blog citing a KPMG survey. If you want it, find KPMG's original report and cite that |

---

## 7. Tooling and hosting claims

| Claim / source | Status | Where used | Reference / note |
|---|---|---|---|
| Streamlit Community Cloud deployment steps, free-tier storage behaviour, supported Python versions | **UNVERIFIED** — from general knowledge | `README_WEBAPP.md`, decisions.md D39 | Check Streamlit's own documentation before relying on the steps. In particular confirm that free-tier local disk may be reset, which is why template backup and restore exist |
| Kaggle CLI single-file download and licence output | VERIFIED — by use, 2026-10-10 | decisions.md D18 | Run during the session; output recorded in D18 |

---

## 8. Priority check list, in order

Ordered by what breaks if it is wrong, not by how quick it is.

1. **Annex III ¶1 points (a)–(k), verbatim.** Everything about the ≥80% coverage claim rests on this list. Nobody has read it in full. `cdm/ANNEX_III_TEMPLATE.csv` is waiting.
2. **EN 18219:2026 full text, and the IEC 61406 profile requirements.** Decides the ADID conformance claim, which is currently null on purpose. Ask the library about CEN access.
3. **GTIN / SGTIN claims against the GS1 General Specifications.** Supports a Critical design decision **and is now public text on the web interface**. Verify before publishing the app, or soften the wording (decisions.md D40).
4. **Check H2's headers against Dolibarr, and record H3's provenance.** The held-out schemas are the evidence for Chapter 5; their source claims are currently unverified.
5. **ISO 3166 code list against the ISO register.** Silently corrupts Stage 4 and CDM validation if wrong, and the failure is invisible.
6. **The 44% Sri Lanka export figure.** Most load-bearing statistic in the thesis.
7. **Upgrade the textile-delegated-act row to primary** against the Commission's delegated-acts register.
8. **Rahm & Bernstein (2001), read firsthand.** Justifies the entire architecture.
9. **Confirm the Kaggle licence on the dataset page, and verify Brooke (1996) and the Streamlit hosting claims.**
10. **Everything still marked CARRIED**, before final submission. These came from the original proposal's reference list, which presumably someone checked at some point — but "presumably" is not "verified".

### Items that are mine to do and cannot be done from here

| Item | Why | Status |
|---|---|---|
| Kaggle licence and dataset download | The licence renders client-side; the download needs an authenticated Kaggle account | **Done 2026-10-10** (MIT; zip hashed, D18). Browser confirmation of the licence still to do |
| EN 18219 full text | A paid CEN standard, not on the open web | Open |
| ISO 3166 register spot-check | The authoritative list is behind the ISO Online Browsing Platform | Open |
| NFR-3 performance baseline | Your hardware. Record CPU, RAM and the absence of a GPU | **Done 2026-10-10** (i5-1135G7, 11.8 GB, no discrete GPU; decisions.md D37) |
| NFR-9 clean install verification | Requires a second physical machine | Open |
| Second-rater agreement | Requires a second person | **Done** (17/17, LiviruM; decisions.md D33) |
| User study (decisions.md D38) | Requires participants and, first, an ethics decision | Open |
