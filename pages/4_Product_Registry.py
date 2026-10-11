"""Public registry lookup — ADIR (identity layer v2)."""

import json

import streamlit as st

from src.registry.store import FACET_FIELDS
from src.registry.views import AccessDenied, NotFound, summary
from webapp import registry_bridge, ui

ui.setup("Registry", wide=True)
node = registry_bridge.get_node()
state = st.session_state

st.title("Product registry")
st.write(
    "Look up any registered product by its ID, its barcode (GTIN) or its readable name, and find related "
    "products. This page shows what **anyone** can see: single items and production batches are never listed "
    "publicly, and supply-chain details stay private to the manufacturer and the authorities."
)

c1, c2, c3, c4 = st.columns(4)
for col, kind, label in ((c1, "family", "Families"), (c2, "variant", "Variants"),
                         (c3, "instance", "Instances"), (c4, "instance", "Instances")):
    col.metric(label, node.store.count(kind))

with st.container(border=True):
    st.subheader("Look up a product")
    query = st.text_input(
        "Product ID, barcode, or readable name",
        value=state.get("registry_query", ""),
        placeholder="e.g. 3f2b…-…  ·  5941234000013  ·  demoknit/ts-1000/navy_m",
    )
    if st.button("Look up", type="primary"):
        state["registry_query"] = query
        state["registry_adid"] = registry_bridge.lookup(query)
        if state["registry_adid"] is None:
            st.warning("Nothing is registered under that ID, barcode or name.")

adid = state.get("registry_adid")
if adid:
    try:
        rec = registry_bridge.record(adid)
    except (AccessDenied, NotFound) as exc:
        st.error(str(exc))
        rec = None
    if rec:
        with st.container(border=True):
            st.subheader(f"{rec['kind'].capitalize()} · {rec['status']}")
            st.code(rec["identifiers"]["uri"], language=None)
            if "tombstone" in rec:
                st.error(rec["tombstone"])
            left, right = st.columns([3, 2])
            with left:
                for section, values in rec.get("sections", {}).items():
                    st.write(f"**{section.replace('_', ' ').capitalize()}**")
                    st.table([{"Field": k, "Value": v} for k, v in values.items()])
                if rec.get("withheld_sections"):
                    st.caption("Not shown publicly: " + ", ".join(rec["withheld_sections"]))
            with right:
                st.write("**Other identifiers**")
                st.json({k: v for k, v in rec["identifiers"].items() if k not in ("uri",)}, expanded=False)
                for rel, items in rec.get("relations", {}).items():
                    st.write(f"**{rel}**")
                    for item in items:
                        if st.button(f"{item.get('kind', '')}: {item.get('label', item['adid'][:8])}",
                                     key=f"{rel}-{item['adid']}"):
                            state["registry_adid"] = item["adid"]
                            st.rerun()
                ver = node.store.verify(adid)
                st.write("**Integrity**")
                (st.success if ver.ok else st.error)(
                    f"Record history {'verified' if ver.ok else 'FAILED verification'} "
                    f"({ver.versions} version{'s' if ver.versions != 1 else ''})."
                )
            if rec["status"] != "withdrawn":
                doc = registry_bridge.passport(adid)
                st.download_button("Download passport (JSON-LD)", json.dumps(doc, indent=2, default=str),
                                   "product-passport.jsonld", "application/ld+json")
                with st.expander("See the full passport"):
                    st.json(doc, expanded=False)

with st.container(border=True):
    st.subheader("Find related products")
    st.write("Search designs and colour/size versions by their details. Spelling of case, spaces and hyphens does not matter.")
    with st.form("search"):
        cols = st.columns(3)
        registrar = cols[0].text_input("Manufacturer (registrar ID)")
        kind = cols[1].selectbox("Show", ["Designs and versions", "Designs only", "Versions only"])
        values = {}
        fields = [f for f in FACET_FIELDS if f != "gtin"]
        grid = st.columns(4)
        for i, f in enumerate(fields):
            values[f] = grid[i % 4].text_input(f)
        go = st.form_submit_button("Search")
    if go:
        kinds = {"Designs and versions": ["model", "variant"], "Designs only": ["model"], "Versions only": ["variant"]}[kind]
        filters = {k: v for k, v in values.items() if v.strip()}
        hits = node.store.search(filters, kinds=kinds, registrar=registrar.strip() or None, limit=node.policy.max_page_size)
        st.write(f"{len(hits)} result{'s' if len(hits) != 1 else ''} (at most {node.policy.max_page_size} shown).")
        if hits:
            st.dataframe([summary(node, node.store.get(a)) for a in hits], **ui.stretch())

ui.footer()
