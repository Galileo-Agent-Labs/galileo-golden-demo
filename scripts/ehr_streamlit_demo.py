"""Isolated Streamlit harness for the EHR frontend — no agent/DB/Galileo.

Run:  .venv/bin/streamlit run scripts/ehr_streamlit_demo.py
Lets us verify the themed chart renders inside real Streamlit (CSS scope,
container width, SVG sparklines, selectbox/button styling) before wiring the
same code into app.py.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st  # noqa: E402

from domains.healthcare import ehr_data, ehr_theme  # noqa: E402

st.set_page_config(page_title="Evercrest Health · EHR", page_icon="✚", layout="wide")
st.markdown(ehr_theme.app_style(), unsafe_allow_html=True)

roster = ehr_data.load_roster()
options = [f"{p['patient_id']} — {p['patient_name']}" for p in roster]

st.markdown(
    ehr_theme.render_topbar("Dr. A. Morgan, MD", now=datetime(2026, 8, 1, 9, 24)),
    unsafe_allow_html=True,
)

c1, c2 = st.columns([0.8, 0.2])
with c1:
    label = st.selectbox("Patient", options, key="pt")
with c2:
    st.write("")
    st.button("🩺  Clinical Assistant", use_container_width=True)

pid = label.split(" — ", 1)[0]
chart = ehr_data.get_chart(pid)

st.markdown(
    '<div class="ehr-root">'
    + ehr_theme.render_banner(chart)
    + ehr_theme.render_chart(chart)
    + "</div>",
    unsafe_allow_html=True,
)
