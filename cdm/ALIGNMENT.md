# CDM Alignment Table and Precedence Rules

**Built:** 2026-10-05. Completes the procedure methodology.md specifies for Layer 2:
competency questions → term extraction per source → **alignment table** →
**precedence rules** → alias vocabulary.

Sources: ESPR (EU) 2024/1781 Annex III ¶1 (a)–(k), expanded through Art. 7(5) and
Art. 5(1); GS1 EPCIS 2.0; UN Transparency Protocol DPP; Regulation (EU) 1007/2011
for fibre composition.

---

## Precedence rules

Applied in order whenever two sources describe the same concept.

1. **ESPR wins on anything legally mandated.** It is the compliance obligation
   the artefact exists to serve; a field named after a standard the regulation
   does not reference is harder to defend at audit.
2. **EPCIS wins on event and lifecycle structure.** ESPR says a passport must
   carry information; it does not model process steps, locations or states.
3. **UNTP wins on verification and credential semantics.** Neither ESPR nor
   EPCIS structures *who attests to a claim and how that is checked*.
4. **Where a source adds qualifying detail rather than a competing name, keep
   both.** A figure and the basis on which it was computed are two facts.

---

## Resolved conflicts

| Concept | ESPR | EPCIS 2.0 | UNTP | Resolved as | Rule |
|---|---|---|---|---|---|
| Product identifier | Annex III 1(b) unique product identifier | `epcList` | `id` / `idValue` / `idScheme` | `productIdentifier` | 1 |
| Trade item number | Annex III 1(c) GTIN | `epcList` (SGTIN) | `idScheme` GS1 | `gtin` | 1 |
| Country of manufacture | Annex III 1(i) context | `bizLocation` | `countryOfProduction` | `countryOfOrigin` | 1 |
| Carbon footprint | Art. 5(1)(o) | — | `emissionsScorecard.carbonFootprint` | `carbonFootprint` + `emissionsDeclaredUnit` + `emissionsReportingStandard` | 1, 4 |
| Recycled content | Art. 5(1)(k) | — | `circularityScorecard.recycledContent` | `recycledContent` | 1 |
| Facility | Annex III 1(i) unique facility identifier | `bizLocation` / `readPoint` | `producedAtFacility` | `facilityIdentifiers` + `productionFacilityLocation` | 1, 4 |
| Manufacturer | Annex III 1(g) | `sourceList` | `producedByParty` | `manufacturerName` + `manufacturerOperatorId` | 1 |
| Compliance | Annex III 1(e) documentation | — | `conformityClaim` | `complianceDocumentation` + `conformityClaim` | 1, 3, 4 |

### Granularity conflicts

| Concept | Resolution |
|---|---|
| Material origin vs product origin | **Kept separate.** `countryOfOrigin` is where the garment was made; `materialOriginCountry` is where a constituent fibre came from. Fabric is routinely woven in one country and sewn in another — collapsing them would misstate the supply chain, and for Sri Lankan exporters importing fabric it is the common case, not the exception. |
| Carbon figure vs its basis | **Kept separate.** 4.2 kg CO2e per garment and per kilogram are different claims; a figure without its declared unit is uninterpretable. |

---

## ⚠ Finding: ADID has no batch level

ESPR Art. 9(2)(d) requires a delegated act to state whether a passport is
established at **model, batch or item** level. UNTP carries `batchNumber`
alongside `serialNumber`. EPCIS models lots through ILMD.

**ADID has three levels — family, variant, instance — and batch is not one of
them.** A variant is a colour-and-size combination; an instance is one physical
unit. A production lot of 500 navy mediums sits between the two and currently
has nowhere to live.

This matters because apparel manufacturing is batch-organised: dye lots, cut
tickets and shipment lots are how a garment factory actually tracks goods, and
several CDM fields are naturally batch-scoped (`batchNumber`, `productionDate`,
`productionStage`, `disposition`, `purchaseOrderReference`).

### What EN 18219:2026 says about this — verified 2026-10-06

CEN/CENELEC JTC 24 published six DPP standards on 27 May 2026, harmonised
15 July 2026, including **EN 18219:2026 "Digital product passport — Unique
identifiers"**.

**They do not specify identifier granularity.** Nothing in EN 18219 defines
model / batch / item structure, and nothing defines a product-family level.
EN 18223 defines a shared data model *container*; product attributes "belong to
sectoral acts, not JTC 24 standards."

Two consequences:

1. **There is no external schema ADID is failing to conform to.** Whichever
   option below is chosen, it cannot be called non-conformant with the standards,
   because the standards are silent here.
2. **The research gap survives, restated.** The standards specify identifiers,
   carriers, APIs and access control. They leave granularity and the apparel
   attribute model open. Both are what ADIF supplies — a stronger claim than the
   original gap #6 wording, which an examiner could now disprove with one search.

Three options, none taken unilaterally — **this is the student's decision**:

1. **State it as a limitation.** ADID addresses model and item level; batch is
   future work. Honest, cheap, and defensible given the timeline. The risk is an
   examiner asking why a regulation-aligned identity model omits a level the
   regulation names.
2. **Add a fourth optional level**, `family/variant/batch/instance`. Most
   faithful to ESPR. Costs a grammar change, a URI depth change, API route
   changes and re-freezing — in week 1 of 4, with evaluation behind it.
3. **Treat batch as CDM data, not ADID identity.** Consistent with D9's
   principle that only what *distinguishes which item* belongs in the path: a
   batch number describes provenance rather than addressing a different product.
   Currently implemented this way, by default rather than by decision.

Option 3 is what the code does today because the batch-scoped fields landed in
the CDM. **Log the choice as D22 either way** — an unlogged default is the one
an examiner finds.

---

## ADID identifier scheme — EN 18219 permits five, and GS1 may be the wrong one

EN 18219:2026 permits five identifier schemes: **GS1 Digital Link URI**,
**IEC 61406 self-issued links**, **W3C DIDs**, **RFID/2D identifiers**, and
**DOIs**.

ADID issues `https://dpp.{manufacturer}/adid/...` — a URI under the
manufacturer's own domain. That is structurally a **self-issued link**, pointing
at IEC 61406 rather than GS1 Digital Link.

If so, project.md §13's open decision — "compliant GS1 Digital Link profile vs
compatible extension" — is asking the wrong question, and the right answer is a
clean IEC 61406 profile claim rather than an awkward GS1 extension.

**NOT CONFIRMED.** EN 18219 is a paid CEN standard and has not been read. Obtain
it (your university library may hold CEN access), confirm the IEC 61406 profile
requirements, then set the claim. `GET /adid/conformance` records this as a
candidate with `"claim": null` and will keep doing so until the standard is read.

---

## Remaining gaps

- **EPCIS event envelope is deliberately excluded.** `eventTime`,
  `eventTimeZoneOffset`, `action`, `eventID`, `sensorElementList` and the event
  types (ObjectEvent, AggregationEvent, TransformationEvent, AssociationEvent)
  describe *events*, not products. A manufacturer spreadsheet row is a product.
  Only the EPCIS fields a product export plausibly carries were adopted. Record
  this as a scoping decision, since "synthesises EPCIS 2.0" could otherwise be
  read as claiming full event support.
- **UNTP has no published version — RESOLVED 2026-10-06.** The specification
  site states: "this content is under development and is not ready for
  implementation." No version string is published. The contradiction in
  sources.md (0.6.0 / 0.7.0 / 0.5.0) is therefore not resolvable, because UNTP
  itself does not assert a stable version. **Cite as "UN Transparency Protocol,
  under development, accessed 2026-10-06."** State as a limitation that four of
  the 54 CDM fields derive from a specification its own authors call not ready.
