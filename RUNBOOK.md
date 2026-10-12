# RUNBOOK — step by step, start to freeze tag

Every command runs in **PowerShell**, from
`C:\Users\User\Desktop\Degree\Research\research-product-software\adif\adif`,
with the venv active. If your prompt does not start with `(.venv)`, run:

```powershell
..\.venv\Scripts\Activate.ps1
```

Each step below has: the command, what you should see, and what to do if you
see something else. **Do not skip a step because the previous one looked fine.**
Steps 1 and 2 are checks precisely because the thing they check already went
wrong once.

---

## STEP 1 — Check which git repository you are in

```powershell
git rev-parse --show-toplevel
```

**Expect:**
```
C:/Users/User/Desktop/Degree/Research/research-product-software/adif/adif
```

**If you see `C:/Users/User` instead** — stop. Your home folder is a git
repository and every commit will go into it. Go to RECOVER.md §1 and deal with
that first. Nothing below is safe until this line ends in `/adif/adif`.

**If you see `fatal: not a git repository`** — fine, you have not initialised
yet. Carry on; Step 7 does it.

---

## STEP 2 — Unzip the new code over the top

Extract `adif.zip` into the project folder, overwriting.

**Before you do:** if `config/default.yaml` already has your model revision in
it, back it up first, because the copy in the zip has `model_revision: null`:

```powershell
Copy-Item config\default.yaml config\default.yaml.mine
```

After extracting, if you backed it up, put your version back:

```powershell
Copy-Item config\default.yaml.mine config\default.yaml -Force
Remove-Item config\default.yaml.mine
```

**Check the fix arrived:**

```powershell
Select-String -Path src\matching\stage3_semantic.py -Pattern "inspect.signature"
```

**Expect:** one line of output. If you get nothing, the extract did not
overwrite — check you extracted into `adif\adif` and not into a new subfolder.

---

## STEP 3 — Record the model revision

Open `config/default.yaml` in a text editor. Find this block:

```yaml
    semantic:                   # M5
      enabled: true
      threshold: null
      top_k: 5
      model: "sentence-transformers/all-MiniLM-L6-v2"
      model_revision: null
```

Change the last line to:

```yaml
      model_revision: "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
```

That hash is the one your own `fetch_model` run resolved. Keep the quotes.
Leave `threshold: null` alone — Step 5 fills that.

**Check:**

```powershell
Select-String -Path config\default.yaml -Pattern "1110a243"
```

**Expect:** one line. The revision now actually constrains which model loads;
before this week's fix it was recorded but ignored.

---

## STEP 4 — Confirm the crash is gone

```powershell
python -m pytest -q
```

**Expect:** `119 passed`.

Then the one that was failing:

```powershell
python -m scripts.demo --real-model
```

**Expect:** the pipeline runs end to end and prints a mapped result. It will
load the model from `.model_cache` with networking disabled.

**If you still get** `TypeError: ... unexpected keyword argument
'local_files_only'` — Step 2 did not overwrite the file. Go back to Step 2.

**If you get** `OSError` or anything about not finding the model — the cache is
missing or incomplete. Re-run `python -m scripts.fetch_model`.

---

## STEP 5 — Derive the thresholds  ← this is the blocker

```powershell
python -m eval.grid_search --real-model
```

**Expect:**
```
Searching 11x11 threshold pairs over 6 schema(s)...

Best macro-F1 0.XXXX at fuzzy=NN.0, semantic=NN.0

Written to config\thresholds.yaml and config\grid_trace.json.
```

It should take **one to three minutes**. (It used to reload the model on all
121 iterations; that is fixed, so if it runs for half an hour something is
wrong — stop it.)

**Note the three numbers it prints.** Then open `config/default.yaml` and set
them **by hand**:

```yaml
    fuzzy:
      threshold: NN.0            # from the grid search, YYYY-MM-DD
    semantic:
      threshold: NN.0            # from the grid search, YYYY-MM-DD
```

Hand-copying is deliberate. `config/thresholds.yaml` is the search's *output*
and is gitignored; `config/default.yaml` is the committed input, and the thing
a run record names. Do not point the config at the generated file.

**Also record them in `methodology.md` §5 Results**, with today's date, the
search range (50–100 step 5) and the macro-F1 at the optimum. Label them as
**development-set** results. They are not evaluation findings.

**If it refuses with a message about the sealed directory** — you passed
`--schemas data/heldout`. Don't. The default is `data/dev` and that is correct.

**If it refuses with a message about the stub embedder** — you left off
`--real-model`. Add it. Never use `--allow-stub` for real values; that flag
exists for smoke tests and its output must be discarded.

### One honest caveat about this step

The search ties the **value stage** threshold to the fuzzy one rather than
searching it independently. That is a shortcut in my code, not a finding. With
the four-stage ladder it means Stage 4's threshold is inherited, not derived.
Note it as a limitation in Chapter 6, or search it separately if you have time
after the main run. Do not describe all four thresholds as "grid-searched" in
the thesis, because one of them is not.

---

## STEP 6 — Fit the calibrator

```powershell
python -m eval.fit_calibration --real-model
```

**Expect:** per-stage observation counts and a written `config/calibrator.json`.

**If it warns that a stage has very few observations** — that is real and worth
reading. Note the counts; they belong in Chapter 6 as a limitation on the ECE
figure. A Platt curve fitted on a handful of points is weak evidence, and D6
chose Platt over isotonic precisely because the data is thin.

---

## STEP 7 — Initialise the repository (skip if Step 1 showed `/adif/adif`)

```powershell
python -m scripts.init_repo --name "yulaAl20" --email "yulani.alwis0@gmail.com"
```

**Expect:** 18 numbered commits, then
`18 commit(s). Review with: git log --oneline --stat`

**If it refuses** with "Repository root: C:/Users/User" — that is the new guard
doing its job. RECOVER.md §1.

---

## STEP 8 — Commit the derived values

```powershell
git add -A -- .
git commit -m "Pin all-MiniLM-L6-v2 revision; record grid-searched thresholds and calibrator"
```

**Check nothing unwanted went in:**

```powershell
git show --stat HEAD
```

**Expect:** `config/default.yaml`, `config/calibrator.json`, and the patched
source files. **Not** `.venv/`, `.model_cache/`, `var/`, `__pycache__/`, or
anything under `data/heldout/`.

---

## STEP 9 — Check the freeze gate

```powershell
python -m scripts.freeze --check
```

**Expect:** `READY`.

Previously this reported three blockers — no thresholds, no calibrator, dirty
tree. Steps 5, 6 and 8 clear all three, in that order.

**If it still says "working tree is dirty"** — run `git status` and commit or
ignore whatever it lists.

---

## STEP 10 — STOP. Three decisions before the tag.

Do not tag yet. **D20** (how many ablation conditions), **D21** (how a demoted
conflict loser is scored), **D22** (batch as ADID identity or CDM data) are all
open, and all three change either what you run or how you score it. D21 in
particular must be settled *before* the first scored run — deciding it
afterwards is choosing a definition once you have seen the numbers, and it will
read that way.

They are written up in `decisions.md` with a recommendation on each. Deciding
them is maybe an hour's thought. None is a coding task.

---

## STEP 11 — Tag the freeze

```powershell
python -m scripts.freeze --tag freeze-v1.0
git log --oneline -1
git tag -l
```

**From this moment: `cdm/`, `config/default.yaml`, `goldstandard/` and
`cdm/vocabularies/signatures.yaml` are frozen.** A change to any of them after
this point is a new version with a logged reason and a re-run, not an edit.

---

## STEP 12 — Only now: build the held-out schemas

In this order, never reversed:

1. Build the three held-out schemas from sources you have **not** inspected
   per-column matcher output on — Dolibarr, a certification form, a buyer
   tech-pack. Put them in `data/heldout/`.
2. Download the Kaggle dataset, record its SHA-256 in `decisions.md` D18, place
   it in `data/heldout/` **unopened**.
3. Write their ground truth using only `goldstandard/RULEBOOK.md` and
   `goldstandard/CDM_FIELDS.txt`.
4. Book the second rater for ≥25% of entries.
5. Then run the ablation:

```powershell
python -m eval.run_ablation --schemas data\heldout --real-model --status EVALUATION
python -m eval.run_ablation --schemas data\heldout --real-model --status EVALUATION --conditions semantic_only
python -m eval.run_template_reuse --schemas data\heldout --real-model --status EVALUATION
python -m eval.run_template_reuse --schemas data\heldout --real-model --status EVALUATION --template-from cascade
```

The first gives Metrics 1-3 and the ladder. The second is the supplementary
AI-only condition, reported outside the ladder (D20). The last two give
Metric 4: `run_ablation` leaves template reuse empty, so cite these records
for it. Read the note the reuse script prints — with the default template,
reuse on unchanged columns is ~100% by construction, and the informative
numbers are delta-field F1 and the `--template-from cascade` reuse rate.

The tag's position *before* these commits is the entire anti-circularity
argument in your methodology. The history is the only evidence of it, so the
ordering is not a formality.

---

## Quick reference

| Step | Command | Gate |
|---|---|---|
| 1 | `git rev-parse --show-toplevel` | ends in `/adif/adif` |
| 2 | extract zip | `inspect.signature` present |
| 3 | edit `config/default.yaml` | `1110a243` present |
| 4 | `python -m pytest -q` | 119 passed |
| 4 | `python -m scripts.demo --real-model` | no TypeError |
| 5 | `python -m eval.grid_search --real-model` | thresholds printed |
| 6 | `python -m eval.fit_calibration --real-model` | calibrator.json |
| 7 | `python -m scripts.init_repo --name ... --email ...` | 18 commits |
| 8 | `git add -A -- .` then `git commit` | clean `git show --stat` |
| 9 | `python -m scripts.freeze --check` | READY |
| 10 | decide D20, D21, D22 | — |
| 11 | `python -m scripts.freeze --tag freeze-v1.0` | tag exists |
| 12 | held-out schemas, then ablation | tag predates them |
