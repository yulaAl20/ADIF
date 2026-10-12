# Development timeline

A dated record of when the work on this artefact actually happened, built
**only** from dates that exist independently of this file. Every row cites where
its date comes from, so each one can be checked.

This exists because the repository was initialised late — on 2026-10-08, after
the prototype was complete. The commit dates therefore record when the history
was *created*, not when the work was *done*. Rather than leave that looking like
a gap, this is the record of the real sequence, with sources.

## Independent evidence

The strongest dates here are not ones I control. The project workspace stamps
documents server-side when they are created, and those timestamps cannot be
edited from inside the project:

| Date | Event | Source of the date |
|---|---|---|
| 2026-07-17 | Research objectives and the approved proposal PDF placed in the project | Project document creation timestamp (server-side) |
| 2026-08-07 | `sources.md` created — the source-verification ledger begins | Project document creation timestamp (server-side) |

Cite these in the appendix if the development timeline is ever questioned. They
are better evidence than a commit date, because a commit date is author-supplied
and these are not.

## Sequence

| Date | Milestone | Source of the date |
|---|---|---|
| 2026-07-17 | Proposal and objectives fixed | Project doc timestamp |
| 2026-08-06 | `methodology.md` and `sources.md` first full revision | "Last updated" header in those documents |
| 2026-08-07 | Source-verification ledger opened | Project doc timestamp |
| 2026-08-18 | CDM extraction from ESPR / EPCIS / UNTP **begun** | `cdm/EXTRACTION.md` line 3 |
| 2026-08-18 | ESPR clause-level verification session; Annex I → Annex III correction found | `sources.md` §1 provenance note |
| 2026-08-18 | Decisions **D17** (cascade), **D18** (seal), **D19** (value stage retained), **D20** (ablation count, raised) | Dates in `decisions.md` entries |
| 2026-09-16 | ERPNext source field list captured for development schema B | `data/sources/erpnext_item_doctype.json` `modified` field |
| 2026-10-05 | CDM extraction **completed**; alignment table and precedence rules written | `cdm/EXTRACTION.md`, `cdm/ALIGNMENT.md` headers |
| 2026-10-05 | Decisions **D22** (batch level, raised), **D23** (dev/held-out reassignment), **D24** (stage precedence) | Dates in `decisions.md` entries |
| 2026-10-06 | Standards verification: EN 18xxx series, textile delegated act, UNTP versioning | `sources.md` §2 and §4 rows |
| 2026-10-08 | Development gold standard frozen — 99 columns, 51 decisions, rulebook v1.0 | `frozen_at` field in `goldstandard/*.json` |
| 2026-10-08 | Repository initialised with increment-structured history (18 commits) | Git history |
| 2026-10-08 | Second-rater review of the development gold standard | `goldstandard/REVIEW_2026-10-08.md` |

## What the commit history is, and is not

**Is:** evidence of *ordering*. The increment commits put the CDM freeze before
the matching stages, and the rulebook before the ground truth written against
it. That ordering is what project.md §11 relies on, and it is preserved
correctly because the commits were created in that sequence.

**Is not:** evidence of elapsed time. All 18 commits carry dates from
2026-10-08 onward. Anyone reading the repository will see that, and the honest
account is the one above.

**The freeze tag is the one date that must be real and must be in the history**,
because the thesis claims the held-out schemas and their ground truth were
constructed *after* the artefacts were frozen. That tag does not exist yet —
the thresholds are not derived. When it is created, its date and its position
relative to the held-out commits is the actual methodological evidence, and
nothing in this file substitutes for it.
