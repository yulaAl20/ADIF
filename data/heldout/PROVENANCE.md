# Held-out schema provenance

Created 2026-10-10, **after** the `freeze-v1.0` tag.

| File | What it is | How it was made |
|---|---|---|
| `styles.csv.zip` | Kaggle Fashion Product Images metadata (H1) | Downloaded unopened; SHA-256 recorded in decisions.md D18 |
| `heldout_h2_dolibarr.csv` | Dolibarr-style product export (H2) | Compiled by an AI assistant (Claude) |
| `heldout_h3_techpack.csv` | Buyer garment tech-pack lines (H3) | Compiled by an AI assistant (Claude) |
| `*_drift.csv` | "Season two" variants of H2 and H3 | `scripts/perturb_schema.py --level drift --seed 7` |

## Disclosure (cite this, do not hide it)

- **Headers** for H2 follow Dolibarr's product-table and extrafield naming
  conventions (`llx_product` columns; extrafields prefixed `options_`), and the
  H3 headers follow typical buyer tech-pack vocabulary. Both were written from
  the assistant's recollection of those sources, **not copied from a live
  Dolibarr instance or a specific buyer's document.** Before citing, check the
  H2 header list against your Dolibarr instance or its documentation and record
  any difference.
- **Values** (references, barcodes, weights, prices, factory names, dates) are
  invented. Barcodes are 13-digit and pass the GTIN-13 check digit.
- The assistant knew the CDM and the system when writing these. To limit
  circularity, headers were taken from source vocabulary rather than chosen to
  match or avoid CDM fields, and **the matcher was not run on them.**
- Gold standards are **not** included. They are written by the researcher from
  `goldstandard/RULEBOOK.md` only.
- The `*.perturbation_log.json` files are the researcher's records. **Never
  give them to the second rater.**
