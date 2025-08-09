# app.py — Play Tagger v5.1.2
import streamlit as st
import pandas as pd
from datetime import datetime

# =======================
# CONFIG
# =======================
st.set_page_config(page_title="Play Tagger v5.1.2", layout="wide")

# Embedded logo loader (file in repo root)
def logo_image_bytes():
    try:
        with open("Transition Defense.png", "rb") as f:
            return f.read()
    except Exception:
        return None

# =======================
# CHIP HELPER (pill buttons)
# =======================
def chip_group(label, options, key, cols=4):
    """Render pill buttons as a single-choice chip group. Stores selection in st.session_state[key]."""
    st.markdown(f"**{label}**")
    st.session_state.setdefault(key, options[0])
    c = st.columns(cols)
    for i, opt in enumerate(options):
        active = (st.session_state[key] == opt)
        # style purely visual; Streamlit ignores inline CSS on buttons, but we still group visually via layout
        if c[i % cols].button(opt, key=f"{key}_{opt}"):
            st.session_state[key] = opt
    return st.session_state[key]

# =======================
# GOOGLE SHEETS (optional)
# =======================
USE_SHEETS = False
gc = None
sh = None

def init_sheets():
    """Initialize Sheets using secrets. Creates core tabs if missing."""
    global USE_SHEETS, gc, sh
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        secrets = st.secrets
        creds_info = secrets["gcp_service_account"]
        sheet_id = secrets["SHEET_ID"]

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        USE_SHEETS = True

        # Ensure baseline tabs exist
        ws_names = [ws.title for ws in sh.worksheets()]
        if "Playbook" not in ws_names:
            sh.add_worksheet("Playbook", rows=1000, cols=3)
            sh.worksheet("Playbook").update("A1:C1", [["Code","Play Name","System"]])
        if "Games" not in ws_names:
            sh.add_worksheet("Games", rows=1000, cols=4)
            sh.worksheet("Games").update("A1:D1", [["Game Name","Type","Opponent","Created At"]])
        if "Roster" not in ws_names:
            sh.add_worksheet("Roster", rows=200, cols=1)
            sh.worksheet("Roster").update("A1:A1", [["Player"]])

        return True
    except Exception:
        st.info("Running without Google Sheets sync. Add Streamlit secrets to enable cloud sync.")
        return False

def get_or_create_game_ws(game_name: str):
    ws_title = f"Game - {game_name}"
    ws_names = [ws.title for ws in sh.worksheets()]
    if ws_title not in ws_names:
        ws = sh.add_worksheet(ws_title, rows=5000, cols=30)
        ws.update("A1:K1", [[
            "Timestamp","Play Name","Call Type","Caller","Outcome","Points","2nd Chance?",
            "Quarter","Opponent","Game Type"
        ]])
    return sh.worksheet(ws_title)

def sheets_append_play(game_name: str, row: list):
    ws = get_or_create_game_ws(game_name)
    ws.append_row(row, value_input_option="USER_ENTERED")

def sheets_add_playbook(play_name: str, code: str = "", system: str = ""):
    ws = sh.worksheet("Playbook")
    ws.append_row([code, play_name, system], value_input_option="USER_ENTERED")

def sheets_overwrite_roster(players: list[str]):
    ws = sh.worksheet("Roster")
    ws.clear()
    rows = [["Player"]] + [[p] for p in players]
    ws.update(f"A1:A{len(rows)}", rows)

# =======================
# DATA
# =======================
PLAY_NAMES = [
    "Flow","Zoom","Shake","Broken Play","Random","Transition","Delay","Pistol",
    "Chin Quick - Spain","Flex - Rifle","Pitch","ATO","Open Sets","Elbow","Punch",
    "Spain","Roll","Step","Iverson","Flare - Quick","Line 1","Rub","Slice","Rifle",
    "Triple Staggers","High","X","Flat 14","College","Mustang"
]
CALL_TYPES = ["Early Offense","Half Court","BLOB","SLOB","Zone"]
CALLERS = ["Coach","Player"]
OUTCOMES = [
    "Made 2","Missed 2","Made 3","Missed 3",
    "Foul (Made 1/2)","Foul (Made 2/2)","Foul (Missed Both)",
    "Turnover","Dead Ball"
]

def points_from_outcome(o: str) -> int:
    return 2 if o=="Made 2" else 3 if o=="Made 3" else 1 if o=="Foul (Made 1/2)" else 2 if o=="Foul (Made 2/2)" else 0

# =======================
# STATE
# =======================
ss = st.session_state
ss.setdefault("plays_master", PLAY_NAMES.copy())
ss.setdefault("game_data", {})          # dict[game] -> list of entries
ss.setdefault("current_game", "Default Game")
ss.setdefault("quarter", "Q1")
ss.setdefault("opponent", "")
ss.setdefault("roster", ["#1", "#2", "#3"])

# =======================
# CSS (pill look + larger tap targets)
# =======================
st.markdown("""
<style>
.stButton > button {
    border-radius: 999px !important;
    font-size: 1.05rem !important;
    padding: 0.8rem 1.1rem !important;
}
.stDataFrame { border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# =======================
# INIT SHEETS + HYDRATE
# =======================
if init_sheets():
    try:
        playbook_df = pd.DataFrame(sh.worksheet("Playbook").get_all_records())
        if not playbook_df.empty and "Play Name" in playbook_df:
            ss["plays_master"] = sorted(set(ss["plays_master"]) | set(playbook_df["Play Name"].dropna().tolist()))
    except Exception:
        pass
    try:
        roster_df = pd.DataFrame(sh.worksheet("Roster").get_all_records())
        if not roster_df.empty and "Player" in roster_df:
            ss["roster"] = [r for r in roster_df["Player"].dropna().tolist()]
    except Exception:
        pass

# =======================
# SIDEBAR — Playbook / Roster
# =======================
with st.sidebar:
    st.header("Manage Playbook")
    np = st.text_input("Play Name")
    if st.button("➕ Add Play"):
        if np.strip():
            if np not in ss["plays_master"]:
                ss["plays_master"].append(np)
                ss["plays_master"].sort()
                if USE_SHEETS:
                    sheets_add_playbook(np)
                st.success(f"Added play: {np}")
        else:
            st.warning("Enter a play name.")

    st.divider()
    st.header("Roster")
    roster_edit = st.text_area("Players (one per line)", value="\n".join(ss["roster"]), height=150)
    if st.button("Save Roster"):
        players = [p.strip() for p in roster_edit.splitlines() if p.strip()]
        ss["roster"] = players or ss["roster"]
        if USE_SHEETS:
            sheets_overwrite_roster(ss["roster"])
        st.success("Roster saved.")

# =======================
# HEADER
# =======================
c1, c2, c3 = st.columns([1,2,1])
with c2:
    _logo = logo_image_bytes()
    if _logo:
        st.image(_logo, use_container_width=True)

st.title("🏀 Play Call Tagging v5.1.2")

# =======================
# CHIP SECTIONS (OUTSIDE FORM)
# =======================
chip_play_name = chip_group("1) Play Name", ss["plays_master"], key="chip_play_name", cols=4)
chip_call_type = chip_group("2) Call Type", CALL_TYPES, key="chip_call_type", cols=4)
chip_caller    = chip_group("3) Caller",     CALLERS,    key="chip_caller",    cols=2)
chip_outcome   = chip_group("4) Outcome",    OUTCOMES,   key="chip_outcome",   cols=4)
chip_second    = chip_group("5) 2nd Chance?",["No","Yes"], key="chip_second", cols=2)

# =======================
# FORM (timestamp + confirm only)
# =======================
with st.form("tag_form", clear_on_submit=True):
    use_now = st.checkbox("Use current time", value=True, key="use_now_ts")
    timestamp = datetime.now().strftime("%H:%M:%S") if use_now else st.text_input("Timestamp", key="manual_ts")

    quarter = st.selectbox("Quarter", ["Q1","Q2","Q3","Q4","OT"],
                           index=["Q1","Q2","Q3","Q4","OT"].index(ss.get("quarter","Q1")))
    opponent = st.text_input("Opponent", value=ss.get("opponent",""))

    submitted = st.form_submit_button("✅ Add Entry", use_container_width=True)

if submitted:
    ss["quarter"] = quarter
    ss["opponent"] = opponent

    play_name     = st.session_state["chip_play_name"]
    call_type     = st.session_state["chip_call_type"]
    caller        = st.session_state["chip_caller"]
    outcome       = st.session_state["chip_outcome"]
    second_chance = st.session_state["chip_second"]

    entry = {
        "Timestamp": timestamp,
        "Play Name": play_name,
        "Call Type": call_type,
        "Caller": caller,
        "Outcome": outcome,
        "Points": points_from_outcome(outcome),
        "2nd Chance?": second_chance,
        "Quarter": quarter,
        "Opponent": opponent,
        "Game Type": "Game"
    }
    ss["game_data"].setdefault(ss["current_game"], []).append(entry)

    if USE_SHEETS:
        sheets_append_play(ss["current_game"], [
            entry["Timestamp"], entry["Play Name"], entry["Call Type"], entry["Caller"],
            entry["Outcome"], entry["Points"], entry["2nd Chance?"], entry["Quarter"],
            entry["Opponent"], entry["Game Type"]
        ])

    st.success("Play logged.")

# =======================
# TABLE + EXPORT
# =======================
df = pd.DataFrame(ss["game_data"].get(ss["current_game"], []))
if not df.empty:
    st.subheader(f"Logged Plays — {ss['current_game']}")
    st.dataframe(df, use_container_width=True, height=320)
    csv = df.to_csv(index=False).encode()
    st.download_button("⬇️ Download CSV", data=csv, file_name="plays.csv", mime="text/csv")
