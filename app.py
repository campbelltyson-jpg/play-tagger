# app.py  v8.0.2
import streamlit as st
import pandas as pd
import json
import time
from datetime import datetime

# -------------------------
# Google Sheets Setup
# -------------------------
import gspread
from google.oauth2.service_account import Credentials

# Load Google credentials from Streamlit Secrets
cred = json.loads(st.secrets["gcp_service_account"], strict=False)
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
credentials = Credentials.from_service_account_info(cred, scopes=scopes)
gc = gspread.authorize(credentials)

SHEET_URL = st.secrets["private_gsheets_url"]
sh = gc.open_by_url(SHEET_URL)
worksheet = sh.sheet1

# -------------------------
# Initialize State
# -------------------------
if "games" not in st.session_state:
    st.session_state.games = {}
if "current_game" not in st.session_state:
    st.session_state.current_game = None
if "play_log" not in st.session_state:
    st.session_state.play_log = []

# -------------------------
# UI Styling
# -------------------------
st.markdown("""
<style>
/* Chip style */
.stButton > button {
    background-color: #e0e0e0 !important;
    color: black !important;
    border-radius: 20px !important;
    padding: 0.4em 1em !important;
    border: 1px solid #ccc !important;
}
.stButton > button:hover {
    background-color: #ffcccc !important;
}
.stButton > button:active, .stButton > button:focus {
    background-color: red !important;
    color: white !important;
}

/* Game clock chip adjustments for iPad/iPhone */
.clock-chip {
    font-size: 16px !important;
    padding: 0.3em 0.6em !important;
    border-radius: 16px !important;
}
</style>
""", unsafe_allow_html=True)

# -------------------------
# Helper Functions
# -------------------------
def add_play_entry(play_names, quarter, clock, called_by, outcome, credit_play=None):
    entry = {
        "Timestamp": datetime.now().strftime("%H:%M:%S"),
        "Quarter": quarter,
        "Clock": clock,
        "Play Names": play_names,
        "Called By": called_by,
        "Outcome": outcome,
        "Credit Play": credit_play
    }
    st.session_state.play_log.append(entry)
    worksheet.append_row(list(entry.values()))

def undo_last_play():
    if st.session_state.play_log:
        st.session_state.play_log.pop()

# -------------------------
# Create or Load Game
# -------------------------
st.sidebar.title("Game Controls")

with st.sidebar.expander("Create / Load Game", expanded=True):
    new_game = st.text_input("Game Title")
    if st.button("Start New Game"):
        if new_game.strip():
            st.session_state.current_game = new_game.strip()
            st.session_state.games[new_game] = {"created": datetime.now().isoformat()}
            st.success(f"Game '{new_game}' created & loaded.")
    if st.session_state.current_game:
        st.info(f"Current Game: {st.session_state.current_game}")
        if st.button("Rename Game"):
            new_title = st.text_input("Enter new name", key="rename_game_input")
            if new_title.strip():
                st.session_state.games[new_title] = st.session_state.games.pop(st.session_state.current_game)
                st.session_state.current_game = new_title
                st.success(f"Renamed to '{new_title}'")

# -------------------------
# Quarter & Clock
# -------------------------
if st.session_state.current_game:
    st.subheader(f"Current Game: {st.session_state.current_game}")

    if "quarter" not in st.session_state:
        st.session_state.quarter = 1

    col1, col2, col3 = st.columns([1,2,1])
    with col1:
        st.markdown(f"**Quarter {st.session_state.quarter}**")
        if st.button("Next Quarter ➡️"):
            st.session_state.quarter += 1
    with col2:
        minutes = st.number_input("Min", 0, 12, 12, key="clock_min", format="%d")
        seconds = st.number_input("Sec", 0, 59, 0, key="clock_sec", format="%d")
    with col3:
        if st.button("Undo Last Possession ⬅️"):
            undo_last_play()

    clock_val = f"{minutes}:{seconds:02d}"

# -------------------------
# Play Calls (Categorized)
# -------------------------
st.subheader("Play Tagging")

playbook = {
    "Pace & Space": ["Transition", "Flow", "Pistol", "Zoom", "Random", "Broken Play", "Punch"],
    "2 Man Game": ["7", "Shake", "Rub", "Roll", "Flat", "Pitch", "15 Step", "14 Step", "51 Step"],
    "3 Man Game": ["77", "Delay", "Pistol", "Away", "Slice", "Elbow", "Stack", "Gets"],
    "Specials": ["Open Sets", "ATO", "College", "Mustang", "1", "Zip Quick", "High", "X"]
}

selected_plays = []
for category, plays in playbook.items():
    exp = st.expander(category, expanded=(category in ["Pace & Space", "2 Man Game"]))
    with exp:
        cols = st.columns(4)
        for i, play in enumerate(plays):
            if cols[i % 4].button(play, key=f"{category}_{play}_{time.time()}"):
                selected_plays.append(play)

# -------------------------
# Quick Bar Outcomes
# -------------------------
st.subheader("Quick Bar")
qb_cols = st.columns(6)
qb_options = ["Made 2", "Made 3", "Missed", "Foul", "Turnover", "Timeout"]
outcome = None
for i, opt in enumerate(qb_options):
    if qb_cols[i].button(opt, key=f"qb_{opt}_{time.time()}"):
        outcome = opt

if outcome and selected_plays:
    add_play_entry(
        play_names=", ".join(selected_plays),
        quarter=st.session_state.quarter,
        clock=clock_val,
        called_by="Coach",
        outcome=outcome,
        credit_play=selected_plays[-1]  # most recent
    )
    st.success(f"Logged: {selected_plays} | {outcome}")

# -------------------------
# Live Dashboard
# -------------------------
st.subheader("Live Dashboard")
df = pd.DataFrame(st.session_state.play_log)

if not df.empty:
    st.dataframe(df)

    # Metrics (PPP, Frequency, Success Rate)
    freq = df["Play Names"].value_counts(normalize=True) * 100
    st.write("**Frequency % per Play**")
    st.bar_chart(freq)

    made_mask = df["Outcome"].isin(["Made 2", "Made 3"])
    success = df.groupby("Play Names")["Outcome"].apply(lambda x: (x.isin(["Made 2","Made 3","Foul"]).mean())*100)
    st.write("**Success Rate % per Play**")
    st.bar_chart(success)

    outcome_points = {"Made 2": 2, "Made 3": 3, "Foul": 1}
    df["Points"] = df["Outcome"].map(outcome_points).fillna(0)
    ppp = df.groupby("Play Names").apply(lambda x: x["Points"].sum()/len(x))
    st.write("**PPP per Play**")
    st.bar_chart(ppp)
