import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import base64

# =======================
# CONFIG
# =======================
st.set_page_config(page_title="Play Tagger v5.1.1", layout="wide")

# Embedded logo loader
def logo_image_bytes():
    with open("Transition Defense.png", "rb") as f:
        return f.read()

# =======================
# CHIP HELPER
# =======================
def chip_group(label, options, key, cols=4, multi=False):
    st.markdown(f"**{label}**")
    if multi:
        st.session_state.setdefault(key, set())
    else:
        st.session_state.setdefault(key, options[0])
    c = st.columns(cols)
    for i, opt in enumerate(options):
        active = opt in st.session_state[key] if multi else (st.session_state[key] == opt)
        style = (
            "background-color:#e10600;color:white;border:none;border-radius:999px;padding:0.6rem 0.8rem;font-weight:bold;"
            if active else
            "background-color:#333;color:white;border-radius:999px;padding:0.6rem 0.8rem;opacity:0.85;"
        )
        if c[i % cols].button(opt, key=f"{key}_{opt}"):
            if multi:
                if opt in st.session_state[key]:
                    st.session_state[key].remove(opt)
                else:
                    st.session_state[key].add(opt)
            else:
                st.session_state[key] = opt
    return list(st.session_state[key]) if multi else st.session_state[key]

# =======================
# GOOGLE SHEETS
# =======================
USE_SHEETS = False
gc = None
sh = None

def init_sheets():
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

        # Ensure core tabs exist
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
        st.info("Running without Google Sheets sync.")
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

def sheets_add_game(game_name: str, game_type: str, opponent: str):
    ws = sh.worksheet("Games")
    ws.append_row([game_name, game_type, opponent, datetime.now().isoformat(timespec="seconds")],
                  value_input_option="USER_ENTERED")

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

# =======================
# STATE
# =======================
ss = st.session_state
ss.setdefault("plays_master", PLAY_NAMES)
ss.setdefault("game_data", {})
ss.setdefault("current_game", "Default Game")
ss.setdefault("quarter", "Q1")
ss.setdefault("opponent", "")
ss.setdefault("roster", ["#1", "#2", "#3"])

# =======================
# CSS
# =======================
st.markdown("""
<style>
.stButton > button {
    border-radius: 999px !important;
    font-size: 1rem !important;
}
</style>
""", unsafe_allow_html=True)

# =======================
# INIT SHEETS + LOAD DATA
# =======================
if init_sheets():
    import gspread
    playbook_df = pd.DataFrame(sh.worksheet("Playbook").get_all_records())
    if not playbook_df.empty:
        ss["plays_master"] = sorted(set(playbook_df["Play Name"].dropna().tolist()))
    roster_df = pd.DataFrame(sh.worksheet("Roster").get_all_records())
    if not roster_df.empty:
        ss["roster"] = [r for r in roster_df["Player"].dropna().tolist()]

# =======================
# SIDEBAR - Add Plays / Roster
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
col1, col2, col3 = st.columns([1,2,1])
with col2:
    st.image(logo_image_bytes(), use_column_width=True)

st.title("🏀 Play Call Tagging v5.1.1")

# =======================
# FORM
# =======================
with st.form("tag_form", clear_on_submit=True):
    ts_now = st.checkbox("Use current time", value=True)
    timestamp = datetime.now().strftime("%H:%M:%S") if ts_now else st.text_input("Timestamp", "")

    play_name = chip_group("1) Play Name", ss["plays_master"], key="chip_play_name", cols=4)
    call_type = chip_group("2) Call Type", CALL_TYPES, key="chip_call_type", cols=4)
    caller = chip_group("3) Caller", CALLERS, key="chip_caller", cols=2)
    outcome = chip_group("4) Outcome", OUTCOMES, key="chip_outcome", cols=4)
    second_chance = chip_group("5) 2nd Chance?", ["No","Yes"], key="chip_second", cols=2)

    quarter = st.selectbox("Quarter", ["Q1","Q2","Q3","Q4","OT"], index=["Q1","Q2","Q3","Q4","OT"].index(ss["quarter"]))
    opponent = st.text_input("Opponent", value=ss["opponent"])

    submitted = st.form_submit_button("✅ Add Entry", use_container_width=True)
    if submitted:
        ss["quarter"] = quarter
        ss["opponent"] = opponent
        entry = {
            "Timestamp": timestamp,
            "Play Name": play_name,
            "Call Type": call_type,
            "Caller": caller,
            "Outcome": outcome,
            "Points": 2 if outcome=="Made 2" else 3 if outcome=="Made 3" else 1 if outcome=="Foul (Made 1/2)" else 2 if outcome=="Foul (Made 2/2)" else 0,
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
# DATA TABLE
# =======================
df = pd.DataFrame(ss["game_data"].get(ss["current_game"], []))
if not df.empty:
    st.subheader(f"Logged Plays — {ss['current_game']}")
    st.dataframe(df, use_container_width=True)
    csv = df.to_csv(index=False).encode()
    st.download_button("⬇️ Download CSV", data=csv, file_name="plays.csv", mime="text/csv")
