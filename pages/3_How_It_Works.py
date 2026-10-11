import pandas as pd
import streamlit as st

from webapp import story, ui

ui.setup("How It Works")
engine = ui.load_engine()
cfg = engine.cfg
stages = cfg.matching.stages

st.title("How it works")
st.write(
    "This page is for readers who want the technical detail. You do not need any of it to use the app."
)

st.header("The idea")
st.write(
    "Every manufacturer names spreadsheet columns differently. The app reads a file, decides which "
    "standard product field each column most likely holds, and lets a person confirm the result. "
    "Confirmed choices become a reusable template. A confirmed file can then be turned into a "
    "digital product passport: a structured, checked record with its own identifier."
)

st.header("The matching steps")
st.write(
    "Each column is tried against four steps, in order, and the first step that is confident enough "
    "decides. Later steps only run if earlier ones found nothing."
)
steps = pd.DataFrame(
    [
        {"Step": "1. Known names", "What it does": "Looks the column name up in a list of known synonyms (for example 'colour', 'shade').", "Setting": "Exact match"},
        {"Step": "2. Similar spelling", "What it does": "Compares the name to the standard field names, tolerating typos and abbreviations (fuzzy string matching).", "Setting": f"Score of at least {stages.fuzzy.threshold:g} out of 100"},
        {"Step": "3. Similar meaning", "What it does": "Compares the meaning of the name using a small language model (sentence embeddings).", "Setting": (f"Similarity of at least {stages.semantic.threshold:g}" if engine.semantic_on else "Switched off in this version")},
        {"Step": "4. Look at the values", "What it does": "Checks what the values look like (country codes, barcodes, customs codes) when the name tells us nothing.", "Setting": f"Score of at least {stages.value.threshold:g} out of 100"},
    ]
)
st.dataframe(steps, hide_index=True, **ui.stretch())
st.write(
    "If two columns compete for the same field, the one with stronger evidence wins and the other "
    "is flagged for review."
)

st.header("How sure is 'How sure'?")
st.write(
    "A raw similarity score is not a probability. For each step, the app learned from example files "
    "how often its answers were right at each score (a logistic calibration), and reports that "
    "as a percentage. Anything below "
    f"{cfg.confidence.bands.review:.0%} is marked for a person to check."
    if cfg.confidence.bands.review is not None
    else "Confidence values are learned from example files with known answers."
)

st.header("From columns to a passport")
st.markdown(
    "- **Standard fields.** Matches point at a fixed list of "
    f"{len(engine.field_names)} product fields, each defined in a JSON Schema.\n"
    "- **Product ID.** Each design, colour-and-size version, batch and single item is registered and gets a "
    "permanent random ID (a UUID). Its details are stored with the ID in the registry.\n"
    "- **Checks.** The record is validated against the schema and against lists of allowed values, "
    "and the share of required fields that are filled is reported.\n"
    "- **Output.** The passport is written as JSON-LD, a standard format for linked data."
)

st.header("Saved templates")
st.write(
    "A template stores only column names and the field each was matched to. Applying it to a new file "
    "reuses those choices for columns it recognises and sends new or renamed columns back through the "
    "matching steps. Templates are kept in a small SQLite database file."
)

st.header("The product ID (ADID) and the registry (ADIR)")
st.write(
    "A barcode (GTIN) usually identifies one colour and size of a product. A passport often has to talk about the "
    "whole design too, and a design has no barcode of its own. The Apparel Digital Identity Registry gives every "
    "level its own ID."
)
st.dataframe(
    pd.DataFrame(
        [
            {"Level": "Design (model)", "Meaning": "The style, whatever the colour or size", "Linked to": "its versions and batches"},
            {"Level": "Variant", "Meaning": "One colour and size of the design", "Linked to": "its design; its barcode"},
            {"Level": "Batch", "Meaning": "One production or dye lot", "Linked to": "its design; the items made in it"},
            {"Level": "Single item", "Meaning": "One physical unit (barcode plus serial number)", "Linked to": "its variant and batch"},
        ]
    ),
    hide_index=True,
    **ui.stretch(),
)
st.markdown(
    "- **The ID carries no information.** It is a random UUID, so nothing you correct later can change it. Colour, size "
    "and every other detail are versioned records in the registry, and every change is kept in a tamper-evident history.\n"
    "- **The levels are links, not parts of the ID.** The registry records which variant belongs to which design and "
    "which items came from which batch, so a design's page lists all its versions, and an authority can list every item "
    "from one batch.\n"
    "- **Not everything is public.** Anyone can look up designs and versions. Batches, single-item lists and supply-chain "
    "details are visible only to the manufacturer and to authorities.\n"
    "- **It works with GS1, not against it.** Barcodes and serial numbers are stored as other names for the same record. "
    "The registry is a research design from this project, not an official standard, and makes no claim to any "
    "standard's identifier scheme. The web addresses shown are illustrations.\n"
    "- **Several registries can work together.** A central index records which registry holds each ID, so registries "
    "can be added or moved without any ID changing."
)

st.header("Technologies")
st.dataframe(
    pd.DataFrame(
        [
            {"Part": "Interface", "Technology": "Streamlit"},
            {"Part": "Reading files", "Technology": "Python and pandas (CSV, Excel, flat JSON)"},
            {"Part": "Similar spelling", "Technology": "RapidFuzz"},
            {"Part": "Similar meaning", "Technology": "Sentence-Transformers, model all-MiniLM-L6-v2"},
            {"Part": "Checking records", "Technology": "JSON Schema (jsonschema) and JSON-LD"},
            {"Part": "Saved templates", "Technology": "SQLite"},
            {"Part": "Settings", "Technology": "One YAML configuration file, fixed before testing"},
        ]
    ),
    hide_index=True,
    **ui.stretch(),
)

st.header("This installation")
st.dataframe(
    pd.DataFrame(
        [
            {"Item": "Standard fields", "Value": str(len(engine.field_names))},
            {"Item": "Meaning-based matching", "Value": "On" if engine.semantic_on else "Off"},
            {"Item": "Confidence available", "Value": "Yes" if engine.calibrator is not None else "No"},
            {"Item": "Settings file", "Value": str(cfg.source_path) if getattr(cfg, "source_path", None) else "config/default.yaml"},
        ]
    ),
    hide_index=True,
    **ui.stretch(),
)

st.header("The development story")
st.write("How the project was built, what went wrong, how it was tested and what it found.")
if st.button("Read the full development story" if not st.session_state.get("show_story") else "Hide the development story"):
    st.session_state["show_story"] = not st.session_state.get("show_story", False)
    st.rerun()
if st.session_state.get("show_story"):
    story.render()

st.header("Limits")
st.markdown(
    "- It is a research prototype, not a certified compliance tool.\n"
    "- It suggests matches; a person must confirm them.\n"
    "- A column that holds several things at once (for example colour and size together) is not split.\n"
    "- Results depend on the file: columns with clear names or recognisable values match best."
)
ui.footer()