# Dependency licence inventory

Required by NFR-11. Every dependency must be free and permissively licensed
(project.md §3: "free, permissively licensed, and installable without a paid
account").

Generated 2026-10-06 from installed package metadata. **Regenerate after any
dependency change**, and spot-check the entries marked uncertain against each
project's own LICENSE file — package metadata is self-reported and occasionally
wrong or absent.

| Package | Version | Licence | Notes |
|---|---|---|---|
| `fastapi` | 0.115.14 | MIT License | core |
| `uvicorn` | 0.30.6 | BSD License | core |
| `pydantic` | 2.13.5 | see project page | core |
| `PyYAML` | 6.0.3 | MIT License | core |
| `pandas` | 2.2.3 | BSD License | core |
| `openpyxl` | 3.1.5 | MIT License | core |
| `rapidfuzz` | 3.14.6 | see project page | core |
| `jsonschema` | 4.26.0 | see project page | core |
| `python-multipart` | 0.0.32 | Apache Software License | core |
| `pytest` | 8.4.2 | MIT License | core |
| `httpx` | 0.28.1 | BSD License | core |
| `sentence-transformers` | not installed | — | optional, not in this environment |
| `torch` | not installed | — | optional, not in this environment |
| `scikit-learn` | 1.9.1 | see project page | optional |
| `matplotlib` | 3.11.2 | Python Software Foundation License | optional |
| `psutil` | 7.2.2 | BSD-3-Clause | optional |

## Model licence — verify separately

`sentence-transformers/all-MiniLM-L6-v2` is a **model**, not a package, so it
is not in the table above and its licence is not covered by any entry there.
It is published under Apache-2.0 on its Hugging Face model card at the time of
writing. **Confirm this on the model card and record it in sources.md** — a
model licence can differ from the library that loads it, and this one is a
declared component of the artefact.

## Data licences — verify separately

| Source | Used for | Licence status |
|---|---|---|
| Fashion Product Images Dataset (Kaggle) | Schema A, held-out | **UNCONFIRMED** — check the dataset page before citing (sources.md) |
| ERPNext `Item` doctype field names | Schema B, dev | GNU GPL v3 (ERPNext). Field *names* used as vocabulary, no code copied |
| Odoo `product.template` field names | Schema C, dev | LGPLv3 (Odoo Community). Field *names* only |
| Dolibarr `Product` class field names | Held-out D | GPLv3 (Dolibarr). Field *names* only |
| GOTS / OEKO-TEX style vocabulary | Held-out E | Naming conventions only, no certifier document reproduced |

Using field *names* as source vocabulary is not redistribution of the
software, but say so explicitly in Chapter 3 rather than leaving an examiner
to wonder whether GPL code entered a project you describe as permissively
licensed.
