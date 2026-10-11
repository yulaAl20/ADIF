import pandas as pd
import streamlit as st

from webapp import ui
from webapp.library import LibraryError, get_library

ui.setup("Saved Templates")
engine = ui.load_engine()
library = get_library()
fields = set(engine.field_names) | {"NO_MAPPING"}

st.title("Saved templates")
st.write(
    "A template remembers how the columns of one file were matched, so you do not have to "
    "repeat your work for the next file from the same supplier."
)

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

query = st.text_input("Search", placeholder="Search by name, company, notes or column name")
items = library.list(query)
total = library.count()

if total == 0:
    st.info("You have no saved templates yet. Create one in the Main Tool after confirming a file.")
    st.page_link("pages/1_Main_Tool.py", label="Go to the Main Tool", icon="➡️")
elif not items:
    st.warning("No templates match your search.")
else:
    st.caption(f"Showing {len(items)} of {total} templates")

for t in items:
    with st.expander(f"{t.name}  ·  {len(t.mappings)} columns  ·  saved {t.updated_at[:10]}"):
        if t.company or t.source_file:
            st.write(f"**Company:** {t.company or '—'}   **From file:** {t.source_file or '—'}")
        if t.notes:
            st.write(t.notes)
        table = pd.DataFrame(
            [{"Column in the file": h, "Matched to": ui.to_label(f)} for h, f in t.mappings.items()]
        )
        st.dataframe(table, hide_index=True, **ui.stretch())

        a, b = st.columns([3, 1])
        new_name = a.text_input("Rename", value=t.name, key=f"name-{t.id}")
        b.write("")
        b.write("")
        if b.button("Rename", key=f"rename-{t.id}"):
            try:
                library.rename(t.id, new_name)
                st.rerun()
            except LibraryError as exc:
                st.error(str(exc))

        u, d, x = st.columns(3)
        if u.button("Use in Main Tool", key=f"use-{t.id}", type="primary"):
            st.session_state["template_choice"] = t.id
            st.switch_page("pages/1_Main_Tool.py")
        d.download_button(
            "Download this template",
            library.export_one(t.id),
            file_name=f"{t.name}.json",
            mime="application/json",
            key=f"dl-{t.id}",
        )
        sure = x.checkbox("I want to delete this", key=f"sure-{t.id}")
        if x.button("Delete", key=f"del-{t.id}", disabled=not sure):
            library.delete(t.id)
            st.rerun()

st.divider()
st.subheader("Backup and restore")
st.write(
    "Templates are stored on the computer or server that runs this app. On a free hosting service "
    "that storage can be reset, so download a backup now and then."
)
c1, c2 = st.columns(2)
with c1:
    st.download_button(
        "Download all templates (backup)",
        library.export_json(),
        "template-backup.json",
        "application/json",
        disabled=total == 0,
    )
with c2:
    uploaded = st.file_uploader("Restore from a backup, or add a mapping list", type=["json", "csv"], key="restore")
    csv_name = st.text_input("Name for a CSV import", value="Imported mapping", help="Only used for .csv files with columns source_column and cdm_field.")
    if uploaded is not None and st.button("Add to my templates"):
        text = uploaded.getvalue().decode("utf-8-sig", errors="replace")
        try:
            if uploaded.name.lower().endswith(".csv"):
                library.import_csv(text, csv_name, fields)
                st.session_state["flash"] = "Mapping list added as a new template."
            else:
                added = library.import_json(text)
                st.session_state["flash"] = f"Added {added} template(s)."
        except LibraryError as exc:
            st.error(str(exc))
        else:
            st.rerun()

ui.footer()