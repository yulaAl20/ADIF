import pandas as pd
import streamlit as st


def _table(rows: list[dict]) -> None:
    frame = pd.DataFrame(rows)
    st.table(frame.set_index(frame.columns[0]))


def render() -> None:
    tabs = st.tabs(
        [
            "The problem",
            "Architecture",
            "Design decisions",
            "Problems found and fixed",
            "How it was tested",
            "Results",
            "Limits",
        ]
    )

    with tabs[0]:
        st.subheader("The problem")
        st.write(
            "The EU's Ecodesign for Sustainable Products Regulation introduces the digital product passport: "
            "a standard, machine-readable record for each product. Small and medium manufacturers already hold "
            "the underlying facts, but in their own systems and spreadsheets, under their own column names. "
            "One factory's 'Colourway' is another's 'shade' and a third's 'x_studio_colour'."
        )
        st.write(
            "The project builds and tests a framework with three layers: an identity model (ADID) that gives "
            "products stable identifiers, a canonical data model (CDM) that defines the standard fields, and a "
            "gateway that maps a manufacturer's own columns onto that model with a person confirming the result."
        )
        st.write("The work follows a Design Science approach: build an artefact, then evaluate it against stated measures.")
        st.subheader("Timeline (from the project records)")
        _table(
            [
                {"Date": "2026-07-17", "Milestone": "Proposal and research objectives fixed"},
                {"Date": "2026-08-18", "Milestone": "Canonical data model extraction begun from the regulation, EPCIS 2.0 and UNTP; core design decisions made (cascade matching, sealed test data)"},
                {"Date": "2026-10-05", "Milestone": "Canonical data model completed; mapping rulebook written and frozen"},
                {"Date": "2026-10-08", "Milestone": "Development answer keys frozen (99 columns); second-rater review of them"},
                {"Date": "2026-10-10", "Milestone": "Settings derived and frozen (tag freeze-v1.0); held-out data created afterwards; evaluation run"},
            ]
        )

    with tabs[1]:
        st.subheader("Architecture")
        st.write("The artefact is fourteen modules, built in increments in this order:")
        _table(
            [
                {"Module": "M1", "Job": "Ingestion: read CSV, Excel or flat JSON, detect encoding and delimiter"},
                {"Module": "M2", "Job": "Schema analysis: profile each column, infer its data type"},
                {"Module": "M3", "Job": "Alias lookup: known synonyms for each standard field"},
                {"Module": "M4", "Job": "Fuzzy matching: tolerant string comparison"},
                {"Module": "M5", "Job": "Semantic matching: sentence embeddings (all-MiniLM-L6-v2)"},
                {"Module": "M6", "Job": "Value matching: recognise a column from what its values look like"},
                {"Module": "M7", "Job": "Cascade arbitration and calibrated confidence"},
                {"Module": "M8", "Job": "Review interface"},
                {"Module": "M9", "Job": "Template store with drift reporting"},
                {"Module": "M10", "Job": "Validation against the data model and allowed-value lists"},
                {"Module": "M11", "Job": "ADID identity model"},
                {"Module": "M12", "Job": "JSON-LD output"},
                {"Module": "M13", "Job": "REST API"},
                {"Module": "M14", "Job": "Instrumentation and the evaluation harness"},
            ]
        )
        st.write(
            "The canonical data model has 54 fields, derived from the regulation (Annex III), GS1's EPCIS 2.0 "
            "and the UN Transparency Protocol through a documented extraction procedure. Every setting that "
            "could change a result (thresholds, stage switches, paths) lives in one YAML file and is read, "
            "never hard-coded."
        )

    with tabs[2]:
        st.subheader("Design decisions")
        st.write("Each decision was written down with its reason before it was built on.")
        _table(
            [
                {"Decision": "Cascade, not a weighted blend", "Reason": "Scores from different methods are not on one scale. A strict fallback order with early exit is simpler to explain, test and attribute."},
                {"Decision": "Confidence is learned, not copied", "Reason": "A similarity of 90 is not '90% likely right'. A per-step logistic (Platt) calibration turns scores into probabilities that can be checked."},
                {"Decision": "Thresholds are derived, never typed in", "Reason": "An unset threshold raises an error. Values come from a search on development data only, and are then frozen."},
                {"Decision": "Identity and data are kept apart", "Reason": "The product ID uses only what identifies an item. A corrected fibre percentage must never change an ID that is already printed on labels."},
                {"Decision": "A column is judged on its contents", "Reason": "A yes/no flag is not the thing it flags, a unit is not a quantity, a label is not an identifier. This became the rulebook used for the answer keys."},
                {"Decision": "Template reuse is tested on a changed file", "Reason": "Reapplying a template to an identical file cannot fail, so it proves nothing. Reuse is measured on a file with renamed, new and dropped columns."},
                {"Decision": "Test data sealed until the freeze", "Reason": "Held-out schemas were created only after the settings were frozen, and the code refuses to read the sealed folder."},
            ]
        )

    with tabs[3]:
        st.subheader("Problems found and fixed")
        st.write(
            "Each of these would have corrupted results silently rather than failing loudly. They were found by testing, "
            "and are reported because they show the artefact was checked, not just written."
        )
        _table(
            [
                {"#": 1, "Problem": "pandas turned the barcode 0012345678905 into 12345678905 and style 00742 into 742", "Fix": "Read every column as text; infer types only for labelling"},
                {"#": 2, "Problem": "Duplicate headers were silently renamed (origin.1) before they could be handled", "Fix": "Read the true header row first, for all three formats"},
                {"#": 3, "Problem": "The alias 'po' sits inside 'fabric compostion', so a fabric column matched purchase order at full score and pushed out the correct column", "Fix": "Minimum length and length ratio for partial matching"},
                {"#": 4, "Problem": "When two columns claimed one field the tie broke on raw score; a customs code that happens to look like a hex colour took the colour field", "Fix": "Stage precedence first, then score"},
                {"#": 5, "Problem": "Loose value patterns (any number, any six hex characters) won conflicts against correct matches", "Fix": "Patterns tightened; the stage-by-stage test shows exactly this kind of harm"},
                {"#": 6, "Problem": "A calibration fitted on one configuration crashed on another", "Fix": "Fit across every configuration; never borrow another step's curve"},
                {"#": 7, "Problem": "Early threshold search ran on a placeholder embedder and produced a plausible-looking but meaningless value", "Fix": "Tuning tools now refuse to run without the real model"},
                {"#": 8, "Problem": "A product family ID could be built from a barcode, making every variant its own family", "Fix": "Now an explicit error with the reason"},
            ]
        )
        st.subheader("A process correction")
        st.write(
            "Three of the fixes above were found by looking at the per-column output of two schemas that were "
            "meant to be held out for testing. That is tuning on test data, whatever the intent. Those schemas "
            "were moved into the development set, and a fresh held-out set was built from sources not yet "
            "inspected. Several rules are enforced by tests, so a lapse fails the build."
        )

    with tabs[4]:
        st.subheader("How it was tested")
        st.markdown(
            "1. **Development set.** Three manufacturer exports (ERPNext, Odoo and a retail-style export) and a "
            "changed version of each, with answer keys written from the rulebook before any run.\n"
            "2. **Settings derived on development data only.** A search over 1,331 combinations of the three "
            "matching thresholds chose 85, 85 and 75 (macro-F1 0.7685).\n"
            "3. **Confidence calibrated and the review rule set.** The review threshold is the lowest confidence "
            "at which accuracy on the development data reaches 90% (0.9608).\n"
            "4. **Freeze.** Everything above was fixed and tagged freeze-v1.0 before any held-out data existed.\n"
            "5. **Held-out set.** Five schemas: a Kaggle fashion catalogue, a Dolibarr-style export and a buyer "
            "tech-pack, with changed versions of the last two. Answer keys were written from the rulebook only.\n"
            "6. **Second rater.** An independent person answered a blank, random sample of 17 of the 59 columns "
            "without seeing the answer keys: 17 of 17 agreed.\n"
            "7. **Ablation.** Stages were added one at a time (similar spelling, then known names, then meaning, "
            "then values) to attribute each gain."
        )

    with tabs[5]:
        st.subheader("Results on the held-out schemas (version 1.0)")
        _table(
            [
                {"Configuration": "Similar spelling only", "F1": 0.541, "Precision": 0.575, "Recall": 0.525},
                {"Configuration": "+ known names", "F1": 0.560, "Precision": 0.597, "Recall": 0.542},
                {"Configuration": "+ meaning", "F1": 0.582, "Precision": 0.602, "Recall": 0.575},
                {"Configuration": "+ values (full)", "F1": 0.628, "Precision": 0.610, "Recall": 0.658},
                {"Configuration": "Meaning only", "F1": 0.062, "Precision": 0.400, "Recall": 0.033},
            ]
        )
        st.markdown(
            "- **Each added step raised the average F1**, mostly through recall. The value step helped most on the "
            "two larger schemas and added nothing on the 10-column Kaggle file.\n"
            "- **Meaning alone is weak.** Embedding similarity on its own found almost nothing the cheaper steps did not.\n"
            "- **Confidence tracked accuracy** (calibration error 0.054), but with the 90% rule about 93% of columns "
            "still go to a person. The tool is a proposer, not an autopilot.\n"
            "- **Template reuse** from the system's own uncorrected output was 3 of 6 (Dolibarr) and 8 of 9 (tech-pack) "
            "on the changed files, with the full system. Reuse from a person-corrected template is 100% by construction "
            "and is not counted as a result.\n"
            "- **Where it fails on development data:** barcode-like style numbers (header says identifier, values say barcode) "
            "and look-alike columns that belong to nothing, such as a description matched to a product family."
        )

    with tabs[6]:
        st.subheader("Limits")
        st.markdown(
            "- **Small test set.** Five schemas, 59 base columns, 22 of them mappable. A difference of a few points is one or two columns.\n"
            "- **Two of the three held-out schemas were compiled by an AI assistant** that knew the system. Their headers follow "
            "real source vocabulary and the matcher was not run on them first, but independence is argued, not proven.\n"
            "- **One main rater and one second rater**, 17 sampled rows.\n"
            "- **Changed files test header changes only**, not changed value formats or changed meanings.\n"
            "- **The hosted version may run without the meaning-based step**, which needs the language model files.\n"
            "- **Two defects were found after the freeze** and are recorded rather than patched: stored comparison figures in the run "
            "record pair different schemas, and a malformed export fails with a raw parser error."
        )