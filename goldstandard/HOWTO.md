# How to write the gold standards — step by step

**Total real work: 51 decisions.** The other 48 derive mechanically (Step 5).
Budget roughly two hours, spread however you like. Start with the 7-row file.

Everything you need is in this directory. Nothing here requires me.

---

## Before you start: what you are actually doing

A gold standard is the **answer key**. For each column in a manufacturer file
you record which CDM field it should map to — or `NO_MAPPING` if there is no
correct target. The evaluation then compares what the system proposed against
what you said was right. That subtraction is where F1, the mandatory-field
match rate, ECE and the template reuse rate all come from.

**One rule above all others: write it before you run the matcher, and never
from its output.** If you record what the system proposed, you are measuring
whether the system agrees with itself. The worksheet deliberately shows you the
column's *contents* and never the system's guess.

There is no single right answer for every row. Several are genuine judgement
calls. What makes your answer defensible is the **rationale** you write beside
it, citing a rulebook rule. At a viva, "why did `has_batch_no` score as a
miss?" needs an answer you wrote in advance, not one reconstructed afterwards.

---

## Step 0 — Read two files (20 minutes)

1. **`RULEBOOK.md`** — the decision rules. R1 cardinality, R2 no-target
   columns, R3 meaning-not-resemblance, R4 ambiguity, R5 granularity,
   R6 recording.
2. **`../docs/example/toy_schema.COMPLETED.csv`** — a worked example on an
   invented schema that appears nowhere in the research. Nine rows filled in
   with reasoning shown, including a unit column, a boolean flag and an
   uninformative header. **This is the pattern to copy.**

`CDM_FIELDS.txt` lists the 54 valid field names plus `NO_MAPPING`. Keep it open.
Field descriptions and source clauses live in `../cdm/cdm_v1.0.schema.json`.

---

## Step 1 — Schema A (7 rows, ~15 minutes)

Open `manufacturer_a.worksheet.csv` in Excel.

Columns: `raw_header`, `datatype`, `sample_values`, `rulebook_rule`,
`what_to_check`, then **`cdm_field`** and **`rationale`** for you to fill.

The `rulebook_rule` column tells you which rule governs each row. It is a
pointer to the decision procedure, not the answer — three of these rows are
ten seconds each, and the real work is one decision covering two rows.

For each row:

1. Read the **sample values**, not the header name.
2. Ask: *what does this column actually contain?*
3. Copy a field name from `CDM_FIELDS.txt` into `cdm_field` — **copy-paste, do
   not retype.** A typo becomes a permanent false negative that the system can
   never score against, and the resulting dip looks like an algorithm problem.
4. Write one clause in `rationale` saying why, citing the rule.
5. Every row gets an entry. `NO_MAPPING` is an answer; a blank cell is not.

Save as CSV. Excel will warn about keeping the format — keep it.

### Convert it

```powershell
python -m scripts.build_gold_standard goldstandard\manufacturer_a.worksheet.csv --rater GDYDA
```

Use your own initials. On success you get
`goldstandard/manufacturer_a.json` and a count of mapped vs `NO_MAPPING`.

It **refuses** on:

| Message | Meaning |
|---|---|
| `'X' is not a CDM field` | Typo. Copy from `CDM_FIELDS.txt`. |
| `'X' has no decision` | Blank cell. Use `NO_MAPPING` (R2.1). |
| `'X' is claimed by 2 columns` | Two columns mapped to one field. R1.2 allows one. |

Nothing is written until every error is fixed.

---

## Step 2 — Schema B (22 rows, ~40 minutes)

`manufacturer_b_erpnext.worksheet.csv`. Real ERPNext field names.

Three rows where the name and the contents disagree — exactly the cases R3
exists for:

- **`stock_uom`** holds `Nos`. A unit of measure for stock counting. (R3.2, R2.2)
- **`has_batch_no`** holds `1`/`0`. A flag meaning "this item is batch-tracked",
  not a batch number. (R3.1)
- **`weight_uom`** holds `Kg` while `weight_per_unit` holds `0.180`. (R3.2)

The toy example covers all three shapes — `uom_code`, `is_serialised` and
`net_kg` respectively. Reuse that reasoning.

Also think about `item_code` vs `variant_of`: one identifies the sellable item,
one points at the design. R4.1 and R4.2 apply, and the schema `description`
fields break the tie.

---

## Step 3 — Schema C (22 rows, ~40 minutes)

`manufacturer_c_odoo.worksheet.csv`. Odoo names, deliberately harder.

`default_code`, `categ_id`, `uom_id`, `x_studio_fiber_comp`. Several headers
carry almost no information and the values carry all of it — R3.4 territory.

Expect more `NO_MAPPING` here: Odoo's `list_price`, `standard_price`,
`sale_ok`, `type` are commercial and workflow fields with no CDM counterpart.
That is correct, not a failure to find something.

---

## Step 4 — Convert all three, then check

```powershell
python -m scripts.build_gold_standard goldstandard\manufacturer_b_erpnext.worksheet.csv --rater GDYDA
python -m scripts.build_gold_standard goldstandard\manufacturer_c_odoo.worksheet.csv --rater GDYDA
python -m scripts.check_environment
```

The ground-truth line should now read `OK  3 gold standards written`.

---

## Step 5 — Derive the three drift gold standards (5 minutes, no judgement)

A drifted schema is its parent with four headers renamed and one dropped.
**Renaming a header does not change what the column contains**, so each renamed
column maps to the same CDM field it did before. There is nothing new to decide,
and inventing a decision here would risk contradicting the parent.

```powershell
python -m scripts.derive_drift_gold manufacturer_a
python -m scripts.derive_drift_gold manufacturer_b_erpnext
python -m scripts.derive_drift_gold manufacturer_c_odoo
```

Each writes a `_drift.json` recording that it was derived, from which parent,
and that parent's hash. If a column cannot be accounted for, it says which and
exits — decide those by hand in the worksheet instead.

> **Using the perturbation log is legitimate for you.** You generated the
> perturbation, so you already know what changed. The independence that matters
> is the **second rater's**, and the rulebook forbids showing them the log for
> exactly that reason.

That is all six dev gold standards: **99 columns, 51 of them your judgement.**

---

## Step 6 — Commit, then the thresholds

```powershell
git add goldstandard/
git commit -m "Add ground truth for development schemas, rulebook v1.0"
```

Then `NEXT_STEPS.md` Step 2 onward: grid search → calibrator → freeze →
held-out schemas → their gold standards → the ablation run.

---

## Step 7 — The held-out schemas (46 rows, later)

**Only after the freeze tag.** `heldout_package.zip` contains two schemas and
blank worksheets. Same process.

`heldout_e_certification` is the hardest in the set — certifier vocabulary,
SPACED CAPS, parenthesised units. Expect more `NO_MAPPING` and more R4.3
"genuinely ambiguous, record it and say so" calls than the ERP schemas. That is
why it is in there.

---

## If you get stuck on a row

**R4.3 exists for this.** If after checking the field descriptions and the
regulatory clause it is still genuinely ambiguous, record `NO_MAPPING` and write
the ambiguity in the rationale. An honest `NO_MAPPING` costs the system one
recall point. A guess corrupts the answer key itself, and every metric computed
from it.

If you think one of my rulebook rules is wrong, **change the rule** and note
why. It is your instrument. Changing a rule and documenting it is a legitimate
research decision; deciding case-by-case without a rule is not.

---

## When you are done

Send me the filled worksheets. I will run an adversarial pass — argue against
each decision, look for rules applied inconsistently between schemas, and flag
what a hostile examiner would press on. That review is independent of your
judgement, which is why it is worth having; me filling the cells would not be.
