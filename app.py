# app.py — Play Tagger v5.3.2
import streamlit as st
import pandas as pd
from datetime import datetime

# =======================
# CONFIG
# =======================
st.set_page_config(page_title="Play Tagger v5.3.2", layout="wide")

def logo_image_bytes():
    try:
        with open("Transition Defense.png", "rb") as f:
            return f.read()
    except Exception:
        return None

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

        # Ensure baseline tabs
        ws_names = [ws.title for ws in sh.worksheets()]
        if "Playbook" not in ws_names:
            sh.add_worksheet("Playbook", rows=1000, cols=3)
            sh.worksheet("Playbook").update("A1:C1", [["Code","Play Name","System"]])
        if "Games" not in ws_names:
            sh.add_worksheet("Games", rows=2000, cols=4)
            sh.worksheet("Games").update("A1:D1", [["Game Name","Type","Opponent","Created At"]])
        if "Roster" not in ws_names:
            sh.add_worksheet("Roster", rows=200, cols=1)
            sh.worksheet("Roster").update("A1:A1", [["Player"]])
        return True
    except Exception:
        st.info("Running without Google Sheets sync. Add Streamlit secrets to enable cloud sync.")
        return False

def game_ws_title(game_name: str) -> str:
    return f"Game - {game_name}"

def get_or_create_game_ws(game_name: str):
    ws_title = game_ws_title(game_name)
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

def sheets_overwrite_game(game_name: str, df: pd.DataFrame):
    """Overwrite the entire game worksheet with current df (keeps header)."""
    ws = get_or_create_game_ws(game_name)
    ws.resize(rows=1)
    ws.update("A1:K1", [[
        "Timestamp","Play Name","Call Type","Caller","Outcome","Points","2nd Chance?",
        "Quarter","Opponent","Game Type"
    ]])
    if df.empty:
        return
    values = df[[
        "Timestamp","Play Name","Call Type","Caller","Outcome","Points","2nd Chance?",
        "Quarter","Opponent","Game Type"
    ]].fillna("").values.tolist()
    ws.update(f"A2:K{len(values)+1}", values)

def sheets_add_game(game_name: str, game_type: str, opponent: str):
    ws = sh.worksheet("Games")
    ws.append_row([game_name, game_type, opponent, datetime.now().isoformat(timespec="seconds")],
                  value_input_option="USER_ENTERED")
    get_or_create_game_ws(game_name)

# =======================
# DATA / CONSTANTS
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
ss.setdefault("games", ["Default Game"])
ss.setdefault("game_meta", {})  # name -> {"quarter": "Q1", "opponent": "", "type": "Game"}
ss.setdefault("current_game", "Default Game")
ss.setdefault("game_data", {})  # name -> list of rows
ss.setdefault("roster", ["#1", "#2", "#3"])
ss.setdefault("selected_plays", set())
ss.setdefault("game_clock_prefill", "")

# =======================
# CSS
# =======================
st.markdown("""
<style>
.stButton > button { border-radius: 999px; padding: 0.8rem 1.1rem; font-size: 1.05rem; }
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
    try:
        games_df = pd.DataFrame(sh.worksheet("Games").get_all_records())
        if not games_df.empty:
            for r in games_df.to_dict("records"):
                name = r.get("Game Name")
                if name and name not in ss["games"]:
                    ss["games"].append(name)
                if name:
                    meta = ss["game_meta"].setdefault(name, {})
                    if r.get("Type"): meta["type"] = r["Type"]
                    if r.get("Opponent"): meta["opponent"] = r["Opponent"]
            ss["games"] = sorted(set(ss["games"]))
    except Exception:
        pass

ss["game_data"].setdefault(ss["current_game"], [])
ss["game_meta"].setdefault(ss["current_game"], {"quarter": "Q1", "opponent": "", "type": "Game"})

# =======================
# HEADER + LOGO
# =======================
c1, c2, c3 = st.columns([1,2,1])
with c2:
    _logo = logo_image_bytes()
    if _logo:
        st.image(_logo, use_container_width=True)

st.title("🏀 Play Call Tagging v5.3.2")

# =======================
# GAME MANAGER (TOP BAR)
# =======================
gm1, gm2, gm3, gm4 = st.columns([2,2,2,2])
with gm1:
    current_game = st.selectbox("Current Game", options=ss["games"],
                                index=ss["games"].index(ss["current_game"]) if ss["current_game"] in ss["games"] else 0)
    if current_game != ss["current_game"]:
        ss["current_game"] = current_game
        ss["game_data"].setdefault(ss["current_game"], [])
        ss["game_meta"].setdefault(ss["current_game"], {"quarter": "Q1", "opponent": "", "type": "Game"})

with gm2:
    meta = ss["game_meta"].setdefault(ss["current_game"], {"quarter": "Q1", "opponent": "", "type": "Game"})
    meta["quarter"] = st.selectbox("Quarter (preset)", ["Q1","Q2","Q3","Q4","OT"],
                                   index=["Q1","Q2","Q3","Q4","OT"].index(meta.get("quarter","Q1")))

with gm3:
    meta["opponent"] = st.text_input("Opponent (saved per game)", value=meta.get("opponent",""))

with gm4:
    meta["type"] = st.selectbox("Game Type", ["Game","Scrimmage","Scout"],
                                index=["Game","Scrimmage","Scout"].index(meta.get("type","Game")))

with st.expander("➕ Create New Game"):
    ng1, ng2, ng3, ng4 = st.columns([2,2,2,2])
    with ng1:
        new_name = st.text_input("Game Name")
    with ng2:
        new_type = st.selectbox("Type", ["Game","Scrimmage","Scout"], key="new_type")
    with ng3:
        new_opp = st.text_input("Opponent", key="new_opp")
    with ng4:
        if st.button("Create"):
            if new_name.strip():
                if new_name not in ss["games"]:
                    ss["games"].append(new_name)
                ss["game_meta"][new_name] = {"quarter": "Q1", "opponent": new_opp, "type": new_type}
                ss["game_data"].setdefault(new_name, [])
                if USE_SHEETS:
                    sheets_add_game(new_name, new_type, new_opp)
                st.success(f"Created game: {new_name}")
                ss["current_game"] = new_name
                st.rerun()
            else:
                st.warning("Enter a game name first.")

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
                    sh.worksheet("Playbook").append_row(["", np, ""], value_input_option="USER_ENTERED")
            st.success(f"Added play: {np}")
            st.rerun()
        else:
            st.warning("Enter a play name.")

    st.divider()
    st.header("Roster")
    roster_edit = st.text_area("Players (one per line)", value="\n".join(ss["roster"]), height=150)
    if st.button("Save Roster"):
        players = [p.strip() for p in roster_edit.splitlines() if p.strip()]
        ss["roster"] = players or ss["roster"]
        if USE_SHEETS:
            ws = sh.worksheet("Roster")
            ws.clear(); ws.update("A1:A1", [["Player"]])
            ws.update(f"A2:A{len(ss['roster'])+1}", [[p] for p in ss["roster"]])
        st.success("Roster saved.")

# =======================
# 1) GAME CLOCK (manual)
# =======================
gc_cols = st.columns([3,1,1])
with gc_cols[0]:
    game_clock = st.text_input("1) Game clock (mm:ss)", value=ss.get("game_clock_prefill",""), placeholder="e.g., 6:37")
with gc_cols[1]:
    if st.button("Set to Now"):
        ss["game_clock_prefill"] = datetime.now().strftime("%M:%S")
        st.rerun()
with gc_cols[2]:
    if st.button("Clear"):
        ss["game_clock_prefill"] = ""
        st.rerun()

# =======================
# 2) PLAY NAMES — multi-select checkbox grid (4 cols)
# =======================
st.markdown("**2) Select Play Name(s)**")
cols = st.columns(4)
selected = set(ss["selected_plays"])
for i, name in enumerate(sorted(ss["plays_master"], key=str.lower)):
    with cols[i % 4]:
        checked = st.checkbox(name, value=(name in selected), key=f"play_chk_{name}")
        if checked:
            selected.add(name)
        else:
            selected.discard(name)
ss["selected_plays"] = selected

# =======================
# 3–6) Call Type / Caller / Outcome / 2nd Chance
# =======================
call_type = st.radio("3) Call Type", CALL_TYPES, horizontal=False, index=0)
caller = st.radio("4) Who called it?", CALLERS, horizontal=True, index=0)
outcome = st.radio("5) Outcome", OUTCOMES, horizontal=False, index=0)
second_chance = st.radio("6) 2nd Chance?", ["No","Yes"], horizontal=True, index=0)

meta = ss["game_meta"][ss["current_game"]]
quarter = meta.get("quarter", "Q1")
opponent = meta.get("opponent", "")
game_type = meta.get("type", "Game")

# =======================
# CONFIRM / DUPLICATE ENTRY
# =======================
bcol1, bcol2 = st.columns([3,2])
with bcol1:
    add_clicked = st.button("✅ Add Entry", use_container_width=True)
with bcol2:
    dup_clicked = st.button("🔁 Duplicate Last", use_container_width=True)

def _push_to_sheets_row(r):
    if USE_SHEETS:
        sheets_append_play(ss["current_game"], [
            r["Timestamp"], r["Play Name"], r["Call Type"], r["Caller"],
            r["Outcome"], r["Points"], r["2nd Chance?"], r["Quarter"],
            r["Opponent"], r["Game Type"]
        ])

if add_clicked:
    if not game_clock.strip():
        st.warning("Enter the game clock (mm:ss) before adding.")
    elif not ss["selected_plays"]:
        st.warning("Select at least one play.")
    else:
        rows = []
        for play in sorted(ss["selected_plays"], key=str.lower):
            rows.append({
                "Timestamp": game_clock.strip(),
                "Play Name": play,
                "Call Type": call_type,
                "Caller": caller,
                "Outcome": outcome,
                "Points": points_from_outcome(outcome),
                "2nd Chance?": second_chance,
                "Quarter": quarter,
                "Opponent": opponent,
                "Game Type": game_type
            })
        ss["game_data"].setdefault(ss["current_game"], []).extend(rows)
        for r in rows:
            _push_to_sheets_row(r)
        st.success(f"Added {len(rows)} entr{'y' if len(rows)==1 else 'ies'}.")

        # Reset properly for next possession
        ss["selected_plays"].clear()
        ss["game_clock_prefill"] = ""
        st.rerun()

if dup_clicked:
    rows_list = ss["game_data"].get(ss["current_game"], [])
    if not rows_list:
        st.warning("No previous entry to duplicate.")
    else:
        last = rows_list[-1].copy()
        # If a game clock is provided, use it; else keep last timestamp
        ts_val = game_clock.strip() if game_clock.strip() else last.get("Timestamp", "")
        last["Timestamp"] = ts_val
        ss["game_data"][ss["current_game"]].append(last)
        _push_to_sheets_row(last)
        st.success("Duplicated last entry.")

# =======================
# TABLE + EDIT/DELETE
# =======================
df = pd.DataFrame(ss["game_data"].get(ss["current_game"], []))
st.subheader(f"Logged Plays — {ss['current_game']}")
if df.empty:
    st.info("No possessions yet.")
else:
    edit_df = df.copy().reset_index().rename(columns={"index":"Row"})
    edit_df["Select"] = False
    edited = st.data_editor(
        edit_df,
        use_container_width=True,
        height=360,
        column_config={
            "Row": st.column_config.NumberColumn(disabled=True),
            "Select": st.column_config.CheckboxColumn(help="Toggle to delete selected rows on Save/Delete"),
        },
        hide_index=True,
        key="editor",
    )

    csave, cdelete, cexport = st.columns([1,1,1])
    with csave:
        if st.button("💾 Save Edits"):
            merged = edited.drop(columns=["Select"]).set_index("Row").sort_index()
            merged = merged[df.columns]
            ss["game_data"][ss["current_game"]] = merged.to_dict(orient="records")
            if USE_SHEETS:
                sheets_overwrite_game(ss["current_game"], merged)
            st.success("Edits saved.")

    with cdelete:
        if st.button("🗑️ Delete Selected"):
            to_drop = edited[edited["Select"]]["Row"].tolist()
            if not to_drop:
                st.warning("No rows selected to delete.")
            else:
                keep = edited[~edited["Select"]].drop(columns=["Select"]).set_index("Row").sort_index()
                keep = keep[df.columns]
                ss["game_data"][ss["current_game"]] = keep.to_dict(orient="records")
                if USE_SHEETS:
                    sheets_overwrite_game(ss["current_game"], keep)
                st.success(f"Deleted {len(to_drop)} row(s).")

    with cexport:
        csv = df.to_csv(index=False).encode()
        st.download_button(
            "⬇️ Download CSV",
            data=csv,
            file_name=f"{ss['current_game'].replace(' ','_')}.csv",
            mime="text/csv",
            use_container_width=True
        )
