import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from webapp import registry_bridge, ui
from webapp.engine import (
    EngineError,
    MappingSession,
    confirm_mappings,
    decisions_from_session,
    generate_passport,
    run_mapping,
)
from webapp.library import LibraryError, get_library
from src.templates.store import Template

ui.setup("Main Tool", wide=True)
engine = ui.load_engine()
library = get_library()

st.title("Match your product file")
st.write("Work through the steps below. You stay in control: nothing is final until you confirm it.")
ui.engine_notice(engine)

SAMPLE = Path("demo/demo_knitwear_export_spring.csv")
state = st.session_state
session: MappingSession | None = state.get("session")

with st.container(border=True):
    st.markdown('<div class="step">Step 1</div>', unsafe_allow_html=True)
    st.subheader("Upload your file")
    saved = library.list()
    ids = [None] + [t.id for t in saved]
    names = {t.id: f"{t.name} ({len(t.mappings)} columns)" for t in saved}
    if state.get("template_choice") not in ids:
        state["template_choice"] = None

    left, right = st.columns(2)
    company = left.text_input(
        "Company or factory name",
        value=state.get("company", "demo-manufacturer"),
        help="Used to build the product ID, for example https://dpp.your-company/...",
    )
    choice = right.selectbox(
        "Start from a saved template (optional)",
        options=ids,
        key="template_choice",
        format_func=lambda i: "None - start fresh" if i is None else names[i],
        help="Reuse the choices you made for an earlier file from the same supplier.",
    )
    upload = st.file_uploader("Choose your spreadsheet", type=["csv", "xlsx", "json"])
    if SAMPLE.is_file():
        st.download_button("Download a sample file to try", SAMPLE.read_bytes(), SAMPLE.name, "text/csv")

    if st.button("Check my file", type="primary", disabled=upload is None):
        state["company"] = company
        template = None
        template_name = None
        if choice is not None:
            chosen = library.get(choice)
            if chosen is not None:
                template = Template(chosen.company or "saved", chosen.id, chosen.updated_at, chosen.cdm_sha256, chosen.mappings)
                template_name = chosen.name
                if chosen.cdm_sha256 and chosen.cdm_sha256 != engine.registry.schema_sha256:
                    st.warning("This template was saved with an older list of standard fields, so some choices may no longer fit.")
        try:
            with st.spinner("Reading your file and finding matches..."):
                state["session"] = run_mapping(engine, upload.name, upload.getvalue(), company, template, template_name)
            state.pop("passport", None)
            session = state["session"]
        except EngineError as exc:
            state.pop("session", None)
            session = None
            st.error(str(exc))

if session is None:
    st.info("Upload a file and press **Check my file** to see the suggestions.")
    ui.footer()
    st.stop()

records = session.result.records
need_check = sum(1 for r in records if r.review_required or r.conflict_flagged)
no_match = sum(1 for r in records if not r.is_mapped())

with st.container(border=True):
    st.markdown('<div class="step">Step 2</div>', unsafe_allow_html=True)
    st.subheader("Check the suggestions")
    st.write(
        "Each row is a column from your file. Use the **Matched to** list to change a suggestion, "
        "or choose **— No match —** if the column does not belong in the passport."
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Columns", len(records))
    m2.metric("Rows of data", session.analysis.row_count)
    m3.metric("Please check", need_check)
    m4.metric("No match found", no_match)

    if session.reuse is not None:
        r = session.reuse
        st.success(
            f"Saved template '{session.template_name}' applied: {len(r.reused)} columns recognised, "
            f"{len(r.new_columns)} new or renamed columns need a look, "
            f"{len(r.drifted_missing)} columns from the template are not in this file."
        )
        with st.expander("See which columns changed"):
            st.write("**New or renamed in this file:** " + (", ".join(r.new_columns) or "none"))
            st.write("**In the template but missing here:** " + (", ".join(r.drifted_missing) or "none"))

    rows = []
    for rec in records:
        values = session.frame.iloc[:, rec.source_position].dropna().astype(str).head(3).tolist()
        if rec.deciding_stage.value == "template":
            sure = "Confirmed"
        elif rec.confidence is not None:
            sure = f"{rec.confidence:.0%}"
        else:
            sure = "—"
        if rec.conflict_flagged:
            flag = "Clash - please check"
        elif rec.review_required:
            flag = "Please check"
        else:
            flag = "Looks fine"
        rows.append(
            {
                "Column in your file": rec.raw_header,
                "Example values": " | ".join(v[:28] for v in values),
                "Matched to": ui.to_label(rec.target_field),
                "How it was found": ui.STAGE_LABELS.get(rec.deciding_stage.value, rec.deciding_stage.value),
                "How sure": sure,
                "Check?": flag,
            }
        )
    frame = pd.DataFrame(rows)
    edited = st.data_editor(
        frame,
        hide_index=True,
        height=min(36 * (len(frame) + 1) + 4, 720),
        key=f"editor-{session.token}-{session.confirmed}",
        disabled=[c for c in frame.columns if c != "Matched to"],
        column_config={
            "Matched to": st.column_config.SelectboxColumn(
                "Matched to", options=[ui.NO_MATCH] + engine.field_names, required=True
            ),
            "Check?": st.column_config.TextColumn("Check?", width="medium"),
        },
        **ui.stretch(),
    )
    st.caption(
        "Many rows say 'Please check' on purpose: the app only skips the check when it is very sure."
    )

with st.container(border=True):
    st.markdown('<div class="step">Step 3</div>', unsafe_allow_html=True)
    st.subheader("Confirm your choices")
    st.write("When you are happy with the table above, confirm it. This keeps a record of your choices.")
    if st.button("Confirm these matches", type="primary"):
        decisions = {
            row["Column in your file"]: ui.from_label(row["Matched to"]) for _, row in edited.iterrows()
        }
        try:
            summary = confirm_mappings(engine, session, decisions)
            state["summary"] = summary
            st.rerun()
        except EngineError as exc:
            st.error(str(exc))
    if session.confirmed and state.get("summary"):
        s = state["summary"]
        st.success(f"Confirmed. You kept {s['kept']} of {s['total']} suggestions and changed {s['changed']}.")
        with st.form("save-template"):
            st.write("**Save these choices as a template** so you can reuse them next time.")
            default_name = f"{session.company} - {Path(session.filename).stem}"
            name = st.text_input("Template name", value=default_name)
            notes = st.text_area("Notes (optional)", height=70)
            saved_now = st.form_submit_button("Save template")
        if saved_now:
            try:
                library.save(
                    name,
                    decisions_from_session(session),
                    company=session.company,
                    notes=notes,
                    source_file=session.filename,
                    cdm_sha256=engine.registry.schema_sha256,
                )
                st.success("Template saved. Find it on the Saved Templates page.")
            except LibraryError as exc:
                st.error(str(exc))

if session.confirmed:
    with st.container(border=True):
        st.markdown('<div class="step">Step 4</div>', unsafe_allow_html=True)
        st.subheader("Register your products and create their passports")
        st.write(
            "Every design, every colour-and-size version, every production batch and every individually "
            "numbered item in your file gets its own permanent product ID in the registry. The ID is a random "
            "code that never changes, even if you later correct a colour or a size."
        )
        if st.button("Register all products in this file", type="primary"):
            try:
                state["registration"] = registry_bridge.register_session(engine, session).as_dict()
            except Exception as exc:  # surfaced, never swallowed
                state.pop("registration", None)
                st.error(f"Registration stopped: {exc}")
        reg = state.get("registration")
        if reg:
            created, updated, unchanged = reg["created"], reg["updated"], reg["unchanged"]
            c1, c2, c3, c4 = st.columns(4)
            for col, kind, label in ((c1, "family", "Families"), (c2, "variant", "Variants"),
                                     (c3, "instance", "Instances"), (c4, "instance", "Instances")):
                total = created.get(kind, 0) + updated.get(kind, 0) + unchanged.get(kind, 0)
                col.metric(label, total, help=f"{created.get(kind, 0)} new, {updated.get(kind, 0)} updated, "
                                              f"{unchanged.get(kind, 0)} already registered")
            for item in reg["skipped"] + reg["conflicts"]:
                st.warning(f"Row {item.get('row', '?')}: {item.get('reason') or item.get('error')}")
            rows = [r for r in reg["row_adids"] if "variant" in r or "model" in r]
            if rows:
                options = list(range(len(rows)))
                pick = st.selectbox(
                    "Show the passport for row",
                    options,
                    format_func=lambda i: f"Row {i + 1}",
                )
                chosen = rows[pick]
                target = chosen.get("instance") or chosen.get("variant") or chosen["model"]
                node = registry_bridge.get_node()
                st.write("**Product ID** (print this in the QR code)")
                st.code(node.uri(target), language=None)
                with st.expander("How this product ID works"):
                    st.write(
                        "The ID is a random code (a UUID). It says nothing about the product by itself, so nothing "
                        "you correct later can change it. Colour, size and everything else are kept in the registry "
                        "record that the ID points to. The design, colour-and-size version and single item each have "
                        "their own ID and are linked to each other in the registry."
                    )
                    st.table([{"Level": k, "Product ID": v} for k, v in chosen.items()])
                document = registry_bridge.passport(target, registry_bridge.owner(session.company))
                text = json.dumps(document, indent=2, default=str)
                st.download_button("Download passport (JSON-LD)", text, "product-passport.jsonld", "application/ld+json")
                with st.expander("See the full passport"):
                    st.json(document, expanded=False)
                st.page_link("pages/4_Product_Registry.py", label="Open the public registry lookup")
