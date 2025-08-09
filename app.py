# app.py — Play Tagger v6
import streamlit as st
import pandas as pd
from datetime import datetime

# =======================
# CONFIG
# =======================
st.set_page_config(page_title="Play Tagger v6", layout="wide")

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

GAME_HEADERS = [
    "Timestamp","Play Name","Call Type","Caller","Outcome","Points",
    "2nd Chance?","2nd Chance Outcome","Quarter","Opponent","Game Type"
]

def get_or_create_game_ws(game_name: str):
    ws_title = game_ws_title(game_name)
    ws_names = [ws.title for ws in sh.worksheets()]
    if ws_title not in ws_names:
        ws = sh.add_worksheet(ws_title, rows=6000, cols=len(GAME_HEADERS))
        ws.update(f"A1:{chr(64+len(GAME_HEADERS))}1", [GAME_HEADERS])
    else:
        ws = sh.worksheet(ws_title)
        # If an older sheet exists without the new column, rewrite header to include it
        header = ws.row_values(1)
        if header != GAME_HEADERS:
            ws.update(f"A1:{chr(64+len(GAME_HEADERS))}1", [GAME_HEADERS])
    return ws

def sheets_append_play(game_name: str, row: list):
    ws = get_or_create_game_ws(game_name)
    ws.append_row(row, value_input_option="USER_ENTERED")

def sheets_overwrite_game(game_name: str, df: pd.DataFrame):
    ws = get_or_create_game_ws(game_name)
    ws.resize(rows=1)  # keep header
    if df.empty:
        ws.update(f"A1:{chr(64+len(GAME_HEADERS))}1", [GAME_HEADERS])
        return
    # Ensure all columns exist / order
    for col in GAME_HEADERS:
        if col not in df.columns:
            df[col] = ""
    df = df[GAME_HEADERS]
    ws.update(f"A1:{chr(64+len(GAME_HEADERS))}{len(df)+1}", [GAME_HEADERS] + df.fillna("").values.tolist())

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
# Base outcomes
OUTCOMES = [
    "Made 2","Missed 2","Made 3","Missed 3",
    "Foul (Made 1/2)","Foul (Made 2/2)","Foul (Missed Both)",
    "Turnover","Dead Ball","Timeout","Dead Ball Foul"
]
SECOND_CHANCE_OUTCOMES = ["Made 2","Missed 2","Made 3","Missed 3","Foul","Turnover","Reset/Other"]

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
ss.setdefault("game_clock_min", 12)
ss.setdefault("game_clock_sec", 0)
ss.setdefault("pending_action", None)  # for Quick Bar confirm

# =======================
# CSS
# =======================
st.markdown("""
<style>
.stButton > button { border-radius: 999px; padding: 0.8rem 1.1rem; font-size: 1.05rem; }
.stDataFrame { border-radius: 10px; }
.quickbar button { margin-bottom: 6px; }
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

st.title("🏀 Play Call Tagging v6")

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
# 1) GAME CLOCK — scroll dial feel (pickers)
# =======================
st.markdown("**1) Game clock**")
cmin, csep, csec = st.columns([1,0.3,1])
with cmin:
    ss["game_clock_min"] = st.selectbox("Min", list(range(12, -1, -1)), index=0, label_visibility="collapsed")
with csep:
    st.markdown("<div style='text-align:center;font-size:1.6rem;padding-top:0.6rem'>:</div>", unsafe_allow_html=True)
with csec:
    ss["game_clock_sec"] = st.selectbox("Sec", [f"{s:02d}" for s in range(59, -1, -1)], index=0, label_visibility="collapsed")
game_clock = f"{ss['game_clock_min']}:{ss['game_clock_sec']}"

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
# 3–6) Call Type / Caller / 2nd Chance / Outcomes
# =======================
call_type = st.radio("3) Call Type", CALL_TYPES, horizontal=False, index=0)
caller = st.radio("4) Who called it?", CALLERS, horizontal=True, index=0)

second_chance = st.radio("5) 2nd Chance?", ["No","Yes"], horizontal=True, index=0)
sc_outcome = None
if second_chance == "Yes":
    sc_outcome = st.radio("Second‑Chance Outcome", SECOND_CHANCE_OUTCOMES, horizontal=False, index=0)

# Standard (non‑quick bar) outcome selector (still available)
outcome = st.radio("6) Outcome", OUTCOMES, horizontal=False, index=0)

meta = ss["game_meta"][ss["current_game"]]
quarter = meta.get("quarter", "Q1")
opponent = meta.get("opponent", "")
game_type = meta.get("type", "Game")

def _row_dict(play, ts, outc, sc_flag, sc_detail):
    return {
        "Timestamp": ts,
        "Play Name": play,
        "Call Type": call_type,
        "Caller": caller,
        "Outcome": outc,
        "Points": (2 if outc=="Made 2" else 3 if outc=="Made 3" else 1 if outc=="Foul (Made 1/2)" else 2 if outc=="Foul (Made 2/2)" else 0),
        "2nd Chance?": sc_flag,
        "2nd Chance Outcome": (sc_detail or ""),
        "Quarter": quarter,
        "Opponent": opponent,
        "Game Type": game_type
    }

def _push_to_sheets_row(r):
    if USE_SHEETS:
        sheets_append_play(ss["current_game"], [
            r["Timestamp"], r["Play Name"], r["Call Type"], r["Caller"],
            r["Outcome"], r["Points"], r["2nd Chance?"], r["2nd Chance Outcome"],
            r["Quarter"], r["Opponent"], r["Game Type"]
        ])

# =======================
# QUICK BAR (with Confirm)
# =======================
st.markdown("**Quick Bar**")
q1, q2, q3, q4, q5, q6 = st.columns(6)
quick_map = {
    "Made 2": "Made 2", "Miss 2": "Missed 2",
    "Made 3": "Made 3", "Miss 3": "Missed 3",
    "Foul 1/2": "Foul (Made 1/2)", "Foul 2/2": "Foul (Made 2/2)", "Foul 0/2": "Foul (Missed Both)",
    "TO": "Turnover", "Dead Ball": "Dead Ball", "Timeout": "Timeout", "DB Foul": "Dead Ball Foul"
}
# Lay out buttons
if q1.button("Made 2"): ss["pending_action"] = "Made 2"
if q1.button("Miss 2"): ss["pending_action"] = "Missed 2"
if q2.button("Made 3"): ss["pending_action"] = "Made 3"
if q2.button("Miss 3"): ss["pending_action"] = "Missed 3"
if q3.button("Foul 1/2"): ss["pending_action"] = "Foul (Made 1/2)"
if q3.button("Foul 2/2"): ss["pending_action"] = "Foul (Made 2/2)"
if q3.button("Foul 0/2"): ss["pending_action"] = "Foul (Missed Both)"
if q4.button("TO"): ss["pending_action"] = "Turnover"
if q5.button("Dead Ball"): ss["pending_action"] = "Dead Ball"
if q5.button("Timeout"): ss["pending_action"] = "Timeout"
if q6.button("DB Foul"): ss["pending_action"] = "Dead Ball Foul"

# Confirm banner
if ss.get("pending_action"):
    with st.container(border=True):
        st.write(f"Pending: **{ss['pending_action']}** | Plays: **{', '.join(sorted(ss['selected_plays'])) or '(none)'}** | Clock: **{game_clock}** | Q: **{quarter}**")
        if second_chance == "Yes":
            st.write(f"2nd‑Chance Outcome: **{sc_outcome or '(select)'}**")
        c1, c2 = st.columns([1,1])
        with c1:
            if st.button("Confirm"):
                if not ss["selected_plays"]:
                    st.warning("Select at least one play.")
                else:
                    rows = []
                    for play in sorted(ss["selected_plays"], key=str.lower):
                        r = _row_dict(play, game_clock, ss["pending_action"], second_chance, sc_outcome)
                        rows.append(r)
                    ss["game_data"].setdefault(ss["current_game"], []).extend(rows)
                    for r in rows: _push_to_sheets_row(r)
                    st.success(f"Logged {len(rows)} entr{'y' if len(rows)==1 else 'ies'} via Quick Bar.")
                    # reset only selection; keep clock and radios sticky
                    ss["selected_plays"].clear()
                    ss["pending_action"] = None
                    st.rerun()
        with c2:
            if st.button("Cancel"):
                ss["pending_action"] = None
                st.info("Quick action canceled.")

# =======================
# STANDARD ADD ENTRY (non‑quick)
# =======================
if st.button("✅ Add Entry", use_container_width=True):
    if not ss["selected_plays"]:
        st.warning("Select at least one play.")
    else:
        rows = []
        for play in sorted(ss["selected_plays"], key=str.lower):
            r = _row_dict(play, game_clock, outcome, second_chance, sc_outcome)
            rows.append(r)
        ss["game_data"].setdefault(ss["current_game"], []).extend(rows)
        for r in rows: _push_to_sheets_row(r)
        st.success(f"Added {len(rows)} entr{'y' if len(rows)==1 else 'ies'}.")
        ss["selected_plays"].clear()
        st.rerun()

# =======================
# TABLE + QUARTER FILTER + EDIT/DELETE
# =======================
df = pd.DataFrame(ss["game_data"].get(ss["current_game"], []))
st.subheader(f"Logged Plays — {ss['current_game']}")
if df.empty:
    st.info("No possessions yet.")
else:
    # Quarter filter so you can view prior quarters while continuing to log
    fcol = st.columns([2,1,1,1])
    with fcol[0]:
        q_filter = st.multiselect("Filter by Quarter", ["Q1","Q2","Q3","Q4","OT"], default=["Q1","Q2","Q3","Q4","OT"])
    view_df = df[df["Quarter"].isin(q_filter)] if q_filter else df

    edit_df = view_df.copy().reset_index().rename(columns={"index":"Row"})
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
            # Merge edits back into master df by Row index
            updated = edited.drop(columns=["Select"]).set_index("Row").sort_index()
            # Replace those rows in the original df
            master = df.copy()
            for row_idx, row_vals in updated.iterrows():
                master.iloc[row_idx] = row_vals[master.columns]
            ss["game_data"][ss["current_game"]] = master.to_dict(orient="records")
            if USE_SHEETS:
                sheets_overwrite_game(ss["current_game"], master)
            st.success("Edits saved.")

    with cdelete:
        if st.button("🗑️ Delete Selected"):
            to_drop = edited[edited["Select"]]["Row"].tolist()
            if not to_drop:
                st.warning("No rows selected to delete.")
            else:
                master = df.drop(index=to_drop).reset_index(drop=True)
                ss["game_data"][ss["current_game"]] = master.to_dict(orient="records")
                if USE_SHEETS:
                    sheets_overwrite_game(ss["current_game"], master)
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