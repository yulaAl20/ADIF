# Ground Truth Rulebook

**Version 1.0 — frozen 2026-10-05.** Governs every gold standard in this directory.

The rulebook exists so that two people, working independently, reach the same answer. If you find yourself deciding a case it doesn't cover, **add a rule** rather than deciding ad hoc — then re-check any earlier decision the new rule touches.

---

## The one rule that protects everything

**Write the gold standard before you run the matcher, and never from its output.**

If you map a column because the system proposed it, you are not measuring the system — you are recording its own answer and calling it truth. Work from the header, the sample values, and the CDM specification. Nothing else.

The same applies to the second rater, who additionally must **not** see the perturbation log. A rater who knows which columns were renamed is reading an answer key.

---

## R1 — Cardinality

**R1.1** Each source column maps to **exactly one** CDM field, or to `NO_MAPPING`.

**R1.2** Two source columns must **not** map to the same CDM field. If two genuinely carry the same meaning, map the more complete or more authoritative one and mark the other `NO_MAPPING`, recording why in the rationale.

**R1.3** A column whose content would split across several CDM fields (e.g. `"Navy / M"` holding colour and size together) maps to `NO_MAPPING`. Field splitting is an explicit scope exclusion; recording it as a correct mapping would credit the system with something it does not do.

---

## R2 — Columns with no CDM target

**R2.1** Record them **explicitly** as `NO_MAPPING`. Never omit a column from the file.

An omitted column is silently excluded from scoring, so the system pays nothing for mapping it wrongly. Distractor columns exist precisely to test whether it knows when to decline.

**R2.2** `NO_MAPPING` is correct when the column is operationally real but outside the CDM — prices, stock flags, internal keys, audit fields, units of measure that belong to another column.

---

## R3 — Meaning, not resemblance

Decide on what the column **contains**, never on what its name looks like.

**R3.1 — A flag is not a value.** A boolean indicating whether something exists is not that thing.
> `has_batch_no` holds `1`/`0`, meaning "this item is batch-tracked". It is **not** `batchNumber`, which holds `DL-7781`. → `NO_MAPPING`

**R3.2 — A unit is not a quantity.** A column holding the unit belongs to the quantity column, not to the CDM field.
> `weight_uom` holds `"Kg"`. `weight_per_unit` holds `0.180`. Only the latter is a candidate for `netWeight`. → `weight_uom` is `NO_MAPPING`

**R3.3 — A label is not an identifier.** Free-text descriptions are not identity fields.
> `description` holding `"Single jersey crew neck"` is marketing copy, not `productFamily` (which holds `TSH-1000`). → `NO_MAPPING`

**R3.4 — Resemblance is irrelevant.** `x_studio_coo` looks like nothing; it holds `LK` and means country of origin. → `countryOfOrigin`. Conversely `standard_price` reads clearly and maps to nothing in the CDM. → `NO_MAPPING`

---

## R4 — Ambiguity

**R4.1** Where two CDM fields could fit, choose the **more specific**.
> A column of `IN`, `BD` sitting beside a separate garment-origin column is `materialOriginCountry`, not `countryOfOrigin`.

**R4.2** Where neither is clearly more specific, consult the field's `description` and `x-adif.clause` in `cdm/cdm_v1.0.schema.json`. The regulatory clause is the tiebreaker.

**R4.3** If still genuinely ambiguous after R4.1 and R4.2, record `NO_MAPPING` and write the ambiguity in the rationale. **Do not guess.** An honest `NO_MAPPING` costs the system one recall point; a guess corrupts the ground truth itself.

---

## R5 — Granularity

A column maps to a CDM field regardless of which level (family / variant / batch / instance) that field sits at. Granularity is the CDM's property, not the mapping's. Do not reject a mapping because the source file mixes levels — manufacturer exports almost always do.

---

## R6 — Recording

Every row carries a **rationale**, even the obvious ones. One short clause is enough. The rationale is what lets the second rater agree or disagree with your *reasoning* rather than just your answer, and it is what you will rely on at the viva when asked why `has_batch_no` scored as a miss.

---

## Second rater (methodology.md, Ground truth)

The gold standard is one person's judgement. Independent checking is what turns
it into evidence that the rulebook constrains decisions rather than merely
recording yours.

**Draw the sample:**
`python -m scripts.second_rater sample data/dev/<schema>.csv --fraction 0.25`

**Give the rater exactly three things:** the blank worksheet, this rulebook, and
`CDM_FIELDS.txt` plus `cdm/cdm_v1.0.schema.json` for the field descriptions.

**Give them nothing else.** Not your gold standard — a rater shown your answers
confirms rather than checks, and people accept roughly 95% of supplied
annotations without re-deriving them. Not the perturbation log, which names the
renamed columns. Not any matcher output.

**Measure:**
`python -m scripts.second_rater agree goldstandard/<schema>.json goldstandard/<schema>.rater2.worksheet.csv`

Target is ≥90% pre-adjudication. **Below target is a finding, not a failure** —
it means the rulebook under-specifies something. The fix is a new rule, then
re-checking every earlier decision that rule touches, recorded in decisions.md.
A disagreement settled by one rater simply deferring to the other, with no rule
added, means the ambiguity is still there.

---

## Procedure

1. Generate the worksheet: `python -m scripts.make_gold_worksheet data/dev/<schema>.csv`
2. Fill `cdm_field` and `rationale` for every row. Valid values are any CDM field name, or `NO_MAPPING`.
3. Convert: `python -m scripts.build_gold_standard goldstandard/<schema>.worksheet.csv`
4. Commit, dated. **Freeze before any evaluation run.**
5. Second rater independently fills a fresh worksheet for ≥25% of rows, using this rulebook and the CDM spec only. Report agreement before adjudication; target ≥90%.
6. Adjudicate disagreements, record each in the rationale, and note whether the rulebook needed a new rule.
