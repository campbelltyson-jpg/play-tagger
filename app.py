import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import streamlit.components.v1 as components
import gspread

# --- CONSTANTS & CONFIGURATION ---
# The URL for the publicly shared Google Sheets spreadsheet
SHEETS_URL = st.secrets["SHEETS_URL"]

# Master lists for UI dropdowns/multiselects
CALLERS = ["John", "Paul", "George", "Ringo", "Other"]
QUARTERS = ["Q1", "Q2", "Q3", "Q4", "OT", "2OT", "3OT", "4OT"]
SC_OUTCOMES = [
    "Made 2", "Missed 2", "Made 3", "Missed 3", "Foul (Made 1/2)", "Foul (Made 2/2)",
    "Turnover", "Dead Ball", "Timeout", "Dead Ball Foul", "Blocked", "Free Throw"
]
AUTO_DEC_SECONDS = 30 # seconds to auto-decrement the clock on a successful possession

GAME_HEADERS = [
    "Timestamp", "Plays", "Credit Play", "Call Type", "Caller", "Outcome", "Points",
    "2nd Chance?", "2nd Chance Outcome", "Quarter", "Opponent", "Game Type", "Success"
]

# ===== Play categories (your list) =====
USER_PLAY_CATEGORIES = {
    "2 Man Game": ["7","Shake","Rub","Roll","Flat","Pitch","15 Step","14 Step","51 Step"],
    "3 Man Game": ["77","Delay","Pistol","Away","Slice","Elbow","Stack","Gets"],
    "Pace & Space": ["Transition","Flow","Pistol","Zoom","Random","Broken Play","Punch"],
    "Specials": ["Open Sets","ATO","College","Mustang","1","Zip Quick","High","X"],
}
UNCATEGORIZED = "Uncategorized"

# --- HELPER FUNCTIONS ---
def is_success(outcome: str):
    """Checks if an outcome is a 'successful' play."""
    if not isinstance(outcome, str): return False
    return outcome in ["Made 2", "Made 3", "Foul (Made 1/2)", "Foul (Made 2/2)", "Free Throw"]

def points_from_outcome(outcome: str):
    """Returns the points scored for a given outcome."""
    if not isinstance(outcome, str): return 0
    if outcome == "Made 2": return 2
    if outcome == "Made 3": return 3
    if outcome == "Foul (Made 1/2)": return 1
    if outcome == "Foul (Made 2/2)": return 2
    return 0

def get_ss(key, default):
    """Returns a value from session_state, or sets a default if it doesn't exist."""
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]

def chip_check_group(label, options, key, cols=4, default_selected=None, small=False):
    if label: st.markdown(f"**{label}**")
    if default_selected is None: default_selected = []
    st.session_state.setdefault(key, set(default_selected))
    selected = set(st.session_state[key])
    col_list = st.columns(cols)
    pad = "6px 10px" if small else "8px 12px"
    st.markdown(f"<style>div[data-key^='{key}__'] label{{padding:{pad} !important;}}</style>", unsafe_allow_html=True)
    for i, opt in enumerate(options):
        with col_list[i % cols]:
            checked = st.checkbox(opt, value=(opt in selected), key=f"{key}__{opt}")
            if checked: selected.add(opt)
            else: selected.discard(opt)
    st.session_state[key] = selected
    return sorted(selected)

def chip_clock_group(label, options, key, cols=4):
    st.markdown(f"**{label}**")
    st.session_state.setdefault(key, "")
    col_list = st.columns(cols)
    for i, opt in enumerate(options):
