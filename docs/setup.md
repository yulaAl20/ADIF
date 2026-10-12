# Setup and Run

Instructions for the ADIF prototype as it currently stands. Both Windows and Linux/macOS are covered — pick one as your primary and record it, since NFR-8 requires you to state which platforms you actually verified rather than assume portability.

---

## 1. Prerequisites

**Python 3.11.x.** Not 3.12, not 3.10. Pin it and record the exact version in your appendix, because "it ran on my machine" is not a reproducibility claim.

```bash
python --version     # Windows may need: py -3.11 --version
```

If it reports anything other than 3.11.x, install 3.11 from python.org before continuing. On Windows tick **"Add Python to PATH"** during install.

**Git**, so run records can carry a commit hash. Without it `git_commit` records as `null` — the code tolerates this, but a run you cannot trace to a commit is not evidence.

---

## 2. Virtual environment

Always work inside one. Installing project dependencies system-wide makes the dependency lock meaningless.

**Windows (PowerShell)**
```powershell
cd path\to\adif
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```
If PowerShell blocks the activation script:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

**Linux / macOS**
```bash
cd path/to/adif
python3.11 -m venv .venv
source .venv/bin/activate
```

Your prompt should now start with `(.venv)`.

---

## 3. Install dependencies

**Shortcut:** from the repository root, `setup.cmd` (Windows) or
`bash setup.sh` (Linux/macOS) does steps 2 to 5 in one command.

Use `setup.cmd` rather than `setup.ps1` on Windows. PowerShell refuses to run
unsigned scripts extracted from a downloaded zip; batch files are not subject
to that rule.


**Minimal install — enough for tests, the demo and the API.** Start here.

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Full install — adds the real embedder and the evaluation stack.** Roughly 2 GB, mostly PyTorch. You do not need this to see the pipeline work.

```bash
# CPU wheel FIRST. Letting pip resolve torch on its own can pull a CUDA build
# of several GB that this project never uses.
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-optional.txt
```

Then capture the exact resolved versions — this is the lock file your appendix cites:

```bash
pip freeze > requirements.lock.txt
```

---

## 4. Check the setup

```bash
python -m scripts.check_environment
```

Reads as: **OK** fine, **MISSING** expected at this stage, **FAIL** fix before continuing.

Right now every frozen artefact should read MISSING — the CDM schema, JSON-LD context, alias vocabulary and ADID grammar do not exist yet. That is the correct state, not a broken install.

---

## 5. Run the tests

```bash
pytest              # quiet
pytest -v           # per-test names
pytest --tb=short   # on failure
```

Expect **116 passing**. Some encode process rules rather than behaviour, and are meant to fail if discipline slips:

- `test_thresholds_are_unset_before_grid_search` fails if anyone writes an invented number into `config/default.yaml` (D11).
- `test_no_source_file_references_the_heldout_directory` fails if any code path reads sealed evaluation data (§11).
- `test_cascade_refuses_to_run_on_underived_thresholds` fails if the cascade is made to run on defaults.

If one of these fails, the fix is in the process, not the test.

---

## 6. Run the demo

```bash
python -m scripts.demo
```

Ingests a sample manufacturer export, analyses the schema, runs the three-stage cascade, and prints which stage decided each column. The built-in sample deliberately contains a typo (`Fabric_Compostion`), a duplicate concept (`origin` and `made in`), and an unmappable column — so you can see fuzzy recovery, conflict demotion and review routing in one run.

Against your own file:

```bash
python -m scripts.demo --file path/to/export.csv
```

Accepts `.csv`, `.xlsx`, and flat `.json`. Nested JSON is rejected with an error that names the scope limitation rather than a parser traceback.

> The script **refuses** any path inside `data/heldout/`. That directory is sealed until after the freeze commit, and a convenience script pointed at it by accident is precisely how the freeze discipline gets broken without anyone noticing.

Once the real model is cached (step 8), add `--real-model` to swap the stub embedder for `all-MiniLM-L6-v2`.

**What the demo is not.** The banner says this every run, and it is worth repeating: the CDM is a six-field test fixture, and the thresholds are invented so the cascade will execute. No number the demo prints is a result.

---

## 7. Run the API

```bash
uvicorn src.api.main:app --reload
```

- Interactive docs — <http://127.0.0.1:8000/docs>
- Health and build state — <http://127.0.0.1:8000/health>

`/health` is deliberately more than a liveness probe. It reports the git commit, config hash, which frozen artefacts exist, which tunables are still unset, and which stages are enabled — so the state of the build is visible without reading any files.

Only `/health` exists so far. Upload and mapping endpoints arrive with M13.

---

## 8. Embedding model — DONE (2026-10-08)

`all-MiniLM-L6-v2` is cached locally and its revision hash is pinned in
`config/default.yaml` under `matching.stages.semantic.model_revision`.

> ### ⚠ Re-extracting a distributed zip will overwrite your pinned hash
>
> `config/default.yaml` in any zip delivered from outside this machine carries
> `model_revision: null`, because the hash is specific to your local cache.
> **Before overwriting `config/` from an archive, copy your pinned value out,
> and paste it back afterwards.** An unpinned model is an unreproducible result:
> a silent upstream update changes your numbers with nothing in the run record
> to explain the difference.
>
> Check it at any time with:
> ```
> python -c "from src.config import load_config; print(load_config('config/default.yaml').matching.stages.semantic.model_revision)"
> ```
> `None` means it has been lost and must be re-pasted.

To re-cache on another machine:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-optional.txt
python -m scripts.fetch_model
```

`MiniLMEmbedder` sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and
`local_files_only=True`, so a stray download attempt fails loudly rather than
quietly passing the NFR-1 acceptance test.

**Now verify the real embedder** — this is the configuration the dissertation
claims, and it has not yet been executed:

```bash
python -m scripts.demo --real-model
pytest tests/acceptance/test_nfr.py -v
```

## 9. What you can and cannot run today

| Works now | Status |
|---|---|
| All 14 modules, M1–M14 | Complete |
| CDM v1.0 — 54 fields, clause-level provenance | Complete |
| Alias vocabulary — 253 keys | Complete, frozen |
| Four-stage cascade incl. value-based matching | Complete |
| ADID identifiers, JSON-LD, validation | Complete |
| REST API, review UI, CLI | Complete |
| Evaluation harness: grid search, calibration, ablation | Complete, awaiting ground truth |
| Embedding model cached and pinned | Complete |
| 116 tests | Passing |

| Blocked on | Needed from |
|---|---|
| Gold standards (5 schemas) | Researcher — see `goldstandard/RULEBOOK.md` |
| Derived thresholds | Grid search, which needs gold standards |
| Fitted calibrator | Needs gold standards |
| Freeze tag | `python -m scripts.freeze --check` lists blockers |
| Any evaluation result | Everything above |

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'src'`** — run from the repository root, and use `python -m scripts.demo`, not `python scripts/demo.py`.

**`UnsetTunable: Config value ... is unset`** — working as designed. Thresholds are `null` until derived by grid search (D11). The demo supplies its own; nothing else should.

**`CdmVocabularyError` / `AliasCollisionError`** — the alias vocabulary disagrees with the CDM schema, or two fields claim aliases that normalise to the same key. Both fail at load rather than degrading silently, because both would otherwise show up as unexplained accuracy loss.

**Excel file will not open** — check `openpyxl` is installed. `.xls` (old format) is not supported; re-save as `.xlsx`.

**pip tries to download a multi-gigabyte CUDA build** — you installed `requirements.txt` before the CPU torch wheel. Recreate the venv and follow step 3 in order.
