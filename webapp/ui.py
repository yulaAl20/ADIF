from __future__ import annotations

import streamlit as st

import webapp  # noqa: F401
from webapp.engine import Engine, EngineError, get_engine

NO_MATCH = "— No match —"

STAGE_LABELS = {
    "alias": "Known column name",
    "fuzzy": "Similar spelling",
    "semantic": "Similar meaning",
    "value": "Looks like the values",
    "template": "Saved or confirmed",
    "none": "No match found",
}

_CSS = """
<style>
#MainMenu, footer, header[data-testid="stHeader"], [data-testid="stSidebar"],
[data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stToolbar"], [data-testid="stDecoration"] {display: none !important;}
.stApp {background: #ffffff;}
.block-container {padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1100px;}
h1, h2, h3 {color: #1b2733; font-weight: 600; letter-spacing: -0.005em;}
.hero {padding: 1.8rem 2rem; background: #f5f7fa; border: 1px solid #dde3ea;
       border-left: 4px solid #0a6ed1; border-radius: 6px; margin-bottom: 1.6rem;}
.hero h1 {margin: 0 0 .5rem 0; font-size: 1.85rem; color: #1b2733;}
.hero p {margin: 0; font-size: 1.05rem; color: #4a5a6a;}
.step {font-size: .75rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
       color: #0a6ed1; margin-bottom: .1rem;}
[data-testid="stColumn"] .stButton button, [data-testid="column"] .stButton button,
[data-testid="stColumn"] .stDownloadButton button, [data-testid="column"] .stDownloadButton button {width: 100%;}
.stButton button, .stDownloadButton button {border-radius: 4px;}
</style>
"""

_PAGES = [
    ("Home.py", "Home"),
    ("pages/1_Main_Tool.py", "Main Tool"),
    ("pages/2_Saved_Templates.py", "Saved Templates"),
    ("pages/3_How_It_Works.py", "How It Works"),
    ("pages/4_Product_Registry.py", "Registry"),
]


def stretch() -> dict:
    major, minor = (int(x) for x in st.__version__.split(".")[:2])
    return {"width": "stretch"} if (major, minor) >= (1, 50) else {"use_container_width": True}


def setup(title: str, wide: bool = False) -> None:
    st.set_page_config(
        page_title=f"{title} · Product Data Matcher",
        page_icon="🧵",
        layout="wide" if wide else "centered",
        initial_sidebar_state="collapsed",
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    cols = st.columns([1, 1.2, 1.6, 1.4, 1.1, 3.9])
    for col, (path, label) in zip(cols, _PAGES):
        col.page_link(path, label=label, disabled=(label == title))
    st.divider()


def load_engine() -> Engine:
    try:
        with st.spinner("Starting the matching engine. The first time can take about a minute..."):
            engine = get_engine()
    except EngineError as exc:
        st.error(f"The app could not start. {exc}")
        st.stop()
    return engine


def engine_notice(engine: Engine) -> None:
    if not engine.semantic_on:
        st.info(
            "This version matches columns by their names and by what the values look like. "
            "The extra step that matches by meaning is switched off here, so a few unusual "
            "column names may need your help."
        )


def footer() -> None:
    st.divider()
    st.caption(
        "Research prototype for demonstration. Please check every match before you rely on it."
    )


def to_label(field_name: str) -> str:
    return NO_MATCH if field_name == "NO_MAPPING" else field_name


def from_label(label: str) -> str:
    return "NO_MAPPING" if label == NO_MATCH else label