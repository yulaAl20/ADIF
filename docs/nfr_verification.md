# Non-functional requirement verification record

Evidence for project.md §14 Definition of Done #2 and #6. Cite these in Chapter 6.

## NFR-8 — runs on both Windows and Linux

| Platform | Python | Tests | Date | By |
|---|---|---|---|---|
| Windows (10/11, PowerShell 5.1) | 3.12 | 116 passed | 2026-10-06 | researcher |
| Linux 6.18 x86_64, glibc 2.39 | 3.13.16 | 116 passed | 2026-10-06 | AI assistant |

**Verified.** Note the version spread: the suite passes on 3.12 and 3.13, which
is wider than `scripts/check_environment.py` accepts (3.11–3.12). The narrower
accepted range is deliberate — it is the range actually exercised by a
documented clean install — but the code is not 3.12-specific.

**Not verified:** macOS. Do not claim it.

## NFR-1 — fully offline at runtime

Verified by `tests/acceptance/test_nfr.py`:

- `test_full_pipeline_runs_with_networking_disabled` replaces `socket.socket`
  and `socket.create_connection` with objects that raise, then runs ingestion →
  analysis → four-stage cascade → validation → JSON-LD. Stricter than bringing
  an interface down, because it fails on the *attempt* rather than on a timeout,
  so a library that would silently fall back to a cache still trips it.
- `test_no_source_module_imports_a_network_client` greps `src/` for `requests`,
  `urllib.request`, `httpx` and `urlopen`.

**Caveat for Chapter 6 — now actionable.** Both tests ran with the *stub*
embedder. The model is cached and pinned as of 2026-10-08, so the real-model
path can and must now be executed:

```bash
pytest tests/acceptance/test_nfr.py -v        # with the model cached
python -m scripts.demo --real-model
```

Record the result here with the date. Until that line exists, the dissertation's
offline claim rests on a configuration that was never run.

## NFR-4 — 50 columns × 1,000 rows within budget

`test_fifty_columns_by_one_thousand_rows_within_budget`: **0.16 s** against a
60 s budget, on the Linux machine above.

**This figure is not yet citable as the headline result.** It used the stub
embedder, so it measures pipeline overhead rather than semantic inference —
0.16 s is the cost of ingestion, analysis, alias, fuzzy and value matching, with
embedding stubbed out. The real model is the expensive part.

Re-run with the cached model and record both figures. Reporting the stub number
as the system's performance would overstate it by whatever the embedding costs,
which on CPU is likely to be the dominant term.

## NFR-5 — deterministic and reproducible

`test_identical_input_and_config_give_byte_identical_output` runs the full
pipeline twice and compares serialised output. Sampling is first-N in row order,
never random, and all tie-breaks fall back to source position.

## NFR-6 — all tunables externalised

`test_no_threshold_literals_in_matching_source` greps `src/matching/` for
threshold comparisons against literals. Reinforced by `UnsetTunable`: an
underived threshold raises rather than defaulting.

## NFR-10 — type hints and docstrings

`test_public_functions_have_docstrings` walks the AST of every module in `src/`.
It found and forced the fix of six undocumented public functions on first run.

## Still unverified

- **NFR-3** (8 GB RAM, 4-core, no GPU): declare your actual test machine spec.
- **NFR-9** (clean install on a second machine): §14 #6 requires it. Your own
  install counts as one machine; a second is still needed.
- **NFR-11** (`docs/licences.md`): the file does not exist. Every dependency's
  licence must be recorded.
- **NFR-1 and NFR-4 with the real model**: the model is now cached and pinned,
  so run both and record the figures here.
