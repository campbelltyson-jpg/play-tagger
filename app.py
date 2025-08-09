import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime
import base64, io

# --- Chip helpers (button groups) ---
def chip_group(label, options, key, cols=0):
    """Renders a row of buttons like chips. Stores selection in st.session_state[key]."""
    st.markdown(f"**{label}**")
    # init default
    st.session_state.setdefault(key, options[0])
    # make columns
    n = cols or len(options)
    c = st.columns(n)
    for i, opt in enumerate(options):
        active = (st.session_state[key] == opt)
        style = "opacity:1;border:1px solid #e10600;background:#e10600;color:white;" if active else "opacity:.85;"
        with c[i % n]:
            if st.button(opt, key=f"{key}_{opt}", use_container_width=True, type="secondary"):
                st.session_state[key] = opt
    return st.session_state[key]

# =======================
# Embedded Logo (optional)
# =======================
LOGO_B64 = st.secrets.get("LOGO_B64", "").strip()  # or paste a hard-coded base64 string here
def _logo_io():
    if not LOGO_B64:
        return None
    try:
        return io.BytesIO(base64.b64decode(LOGO_B64))
    except Exception:
        return None

# =======================
# Google Sheets (optional)
# =======================
USE_SHEETS = False
gc = None
sh = None

def init_sheets():
    """
    Expects in Secrets:
      SHEET_ID = "<id>"
      [gcp_service_account] block
    """
    global USE_SHEETS, gc, sh
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_info = st.secrets["gcp_service_account"]
        sheet_id = st.secrets["SHEET_ID"]

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        USE_SHEETS = True

        # Ensure baseline tabs
        ws_names = [ws.title for ws in sh.worksheets()]
        if "Playbook" not in ws_names:
            sh.add_worksheet("Playbook", rows=2000, cols=3)
            sh.worksheet("Playbook").update("A1:C1", [["Code","Play Name","System"]])
        if "Games" not in ws_names:
            sh.add_worksheet("Games", rows=2000, cols=4)
            sh.worksheet("Games").update("A1:D1", [["Game Name","Type","Opponent","Created At"]])
        if "Roster" not in ws_names:
            sh.add_worksheet("Roster", rows=200, cols=1)
            sh.worksheet("Roster").update("A1:A1", [["Player"]])

        playbook = pd.DataFrame(sh.worksheet("Playbook").get_all_records())
        games = pd.DataFrame(sh.worksheet("Games").get_all_records())
        roster = pd.DataFrame(sh.worksheet("Roster").get_all_records())
        return playbook, games, roster
    except Exception:
        st.info("Running without Google Sheets sync. Add Streamlit secrets to enable cloud sync.")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def _game_ws(game_name: str):
    ws_title = f"Game - {game_name}"
    ws_names = [ws.title for ws in sh.worksheets()]
    if ws_title not in ws_names:
        ws = sh.add_worksheet(ws_title, rows=8000, cols=30)
        ws.update("A1:K1", [[
            "Timestamp","Play Name","Call Type","Caller","Outcome","Points","2nd Chance?",
            "Quarter","Opponent","Player","Game Type"
        ]])
    return sh.worksheet(ws_title)

def sheets_append_play(game_name: str, row: list):
    ws = _game_ws(game_name)
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
# Helpers & constants
# =======================
def points_from_outcome(o: str) -> int:
    return 2 if o=="Made 2" else 3 if o=="Made 3" else 1 if o=="Foul (Made 1/2)" else 2 if o=="Foul (Made 2/2)" else 0

CALL_TYPES = ["Early Offense","Half Court","Baseline Out of Bounds","Sideline Out of Bounds","Zone"]
CALLERS = ["Coach","Player"]
OUTCOMES = ["Made 2","Missed 2","Made 3","Missed 3","Foul (Made 1/2)","Foul (Made 2/2)","Foul (Missed Both)","Turnover","Dead Ball"]
QUARTERS = ["Q1","Q2","Q3","Q4","OT"]

# Your v5 play list (preloaded)
PRELOADED_PLAYS = [
    "7","Flow","Zoom","Shake","Broken Play","Random","Transition","Delay","Pistol",
    "Chin Quick - Spain","Flex - Rifle","Pitch","ATO","Open Sets","Elbow","Punch",
    "Spain","Roll","Step","Iverson","Flare - Quick","Line 1","Rub","Slice","Rifle",
    "Triple Staggers","High","X","Flat 14","College","Mustang"
]

def games_by_type(view: str, games, meta):
    if view == "All":
        return sorted(games)
    out = [g for g in games if meta.get(g, {}).get("type", "Game") == view]
    return sorted(out) if out else ["(none)"]

# =======================
# App config & state
# =======================
st.set_page_config(page_title="Play Tagger v5", layout="wide")
playbook_df, games_df, roster_df = init_sheets()

ss = st.session_state
ss.setdefault("plays_master", PRELOADED_PLAYS.copy())
ss.setdefault("games", ["Scrimmage"])
ss.setdefault("game_data", {})       # dict[game] -> list[dict]
ss.setdefault("game_meta", {})       # dict[game] -> {"type": "...", "opponent": "...", "quarter": "..."}
ss.setdefault("roster", ["#1","#3","#5","Lead Guard","Wing","Big"])
ss.setdefault("selected_plays", set())  # current selection set for checkbox grid

# hydrate from Sheets
if not playbook_df.empty:
    from_sheet = [p for p in playbook_df.get("Play Name", []).tolist() if p]
    if from_sheet:
        ss["plays_master"] = sorted(set(ss["plays_master"]) | set(from_sheet))
if not games_df.empty:
    for row in games_df.to_dict(orient="records"):
        name = row.get("Game Name")
        if name:
            if name not in ss["games"]:
                ss["games"].append(name)
            ss["game_meta"].setdefault(name, {})
            if row.get("Type"): ss["game_meta"][name]["type"] = row["Type"]
            if row.get("Opponent"): ss["game_meta"][name]["opponent"] = row["Opponent"]
    ss["games"] = sorted(set(ss["games"]))
if not roster_df.empty:
    rlist = [r.get("Player") for r in roster_df.to_dict(orient="records") if r.get("Player")]
    if rlist:
        ss["roster"] = rlist

# =======================
# Header / Branding
# =======================
c1, c2, c3 = st.columns([1,2,1])
with c2:
    _io = _logo_io()
    if _io:
        st.image(_io, use_column_width=True)

# iPad-friendly CSS
st.markdown("""
<style>
/* Larger touch targets for 'form' feel */
.stSelectbox > div > div,
.stTextInput > div > div > input,
.stButton > button,
.stRadio > div,
.stCheckbox > label {
    font-size: 1.25rem !important;
}
.stButton > button {
    padding: 0.8rem 1.2rem !important;
    border-radius: 12px;
}
[data-baseweb="select"] div { background: transparent; }
.stDataFrame { border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; }
.stDownloadButton button { border-radius: 12px; }
</style>
""", unsafe_allow_html=True)
.stButton > button {
padding: 0.8rem 1.0rem !important;
border-radius: 999px;           /* pill look */
}

# ===== Game-type chips =====
type_chip = st.radio("View games by type", ["All", "Game", "Scrimmage", "Scout"], horizontal=True)

# =======================
# Sidebar: Game / Playbook / Roster / Presets
# =======================
with st.sidebar:
    st.header("Game Manager")
    filtered = games_by_type(type_chip, ss["games"], ss["game_meta"])
    game = st.selectbox("Select Game", options=filtered, index=0)

    new_game = st.text_input("Create new game")
    colGA, colGB = st.columns(2)
    with colGA:
        game_type = st.selectbox("Type", ["Game","Scrimmage","Scout"], key="game_type_new")
    with colGB:
        opp_in = st.text_input("Opponent", key="opponent_new")
    if st.button("➕ Add Game"):
        if new_game.strip():
            if new_game not in ss["games"]:
                ss["games"].append(new_game)
                ss["games"].sort()
            ss["game_meta"].setdefault(new_game, {})
            ss["game_meta"][new_game]["type"] = game_type
            ss["game_meta"][new_game]["opponent"] = opp_in
            if USE_SHEETS:
                sheets_add_game(new_game, game_type, opp_in)
            st.success(f"Game '{new_game}' created.")
            game = new_game
        else:
            st.warning("Enter a game name first.")

    # Preset quarter (saved per game)
    ss["game_meta"].setdefault(game, {})
    default_q = ss["game_meta"][game].get("quarter", "Q1")
    ss["game_meta"][game]["quarter"] = st.selectbox("Preset Quarter", QUARTERS, index=QUARTERS.index(default_q))
    ss["game_meta"][game]["opponent"] = st.text_input("Opponent (saved per game)", value=ss["game_meta"][game].get("opponent",""))
    ss["game_meta"][game]["type"] = st.selectbox("Game Type (saved per game)", ["Game","Scrimmage","Scout"],
                                                 index=["Game","Scrimmage","Scout"].index(ss["game_meta"][game].get("type","Game")))

    st.divider()
    st.header("Playbook")
    with st.expander("➕ Add Play"):
        np = st.text_input("Play Name")
        ncode = st.text_input("Short Code (optional)")
        nsys = st.text_input("System/Group (optional)")
        if st.button("Add to Playbook"):
            if np.strip():
                if np not in ss["plays_master"]:
                    ss["plays_master"].append(np)
                    ss["plays_master"].sort()
                    if USE_SHEETS:
                        sheets_add_playbook(np, ncode, nsys)
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

    st.divider()
    game_mode = st.toggle("Game Mode (hide analytics)", value=False)

# Ensure containers
ss["game_data"].setdefault(game, [])
meta = ss["game_meta"][game]
meta.setdefault("type", "Game")
meta.setdefault("opponent", "")
meta.setdefault("quarter", "Q1")

# =======================
# FORM FLOW (like Google Form)
# =======================
st.title("🏀 Play Call Tagging (v5)")

# 1) Timestamp (game clock when crossing half court)
ts = st.text_input("1) Timestamp (game clock, e.g., 6:37 Q2)")

# 2) Play Names — checkbox grid (4 columns). You can toggle multiple.
st.markdown("**2) Select Play Name(s)**")
# Initialize local set
selected = set(ss["selected_plays"])
cols = st.columns(4)
# Sort plays A-Z for fast scanning
for i, name in enumerate(sorted(ss["plays_master"], key=str.lower)):
    with cols[i % 4]:
        checked = st.checkbox(name, value=(name in selected), key=f"play_chk_{name}")
        if checked:
            selected.add(name)
        else:
            selected.discard(name)
# Store back
ss["selected_plays"] = selected

# 3) Call Type — chips
call_type = chip_group("3) Call Type", CALL_TYPES, key="chip_call_type", cols=4)

# 4) Who Called It — chips
caller = chip_group("4) Who called it?", CALLERS, key="chip_caller", cols=2)

# 5) Outcome — chips (break into 2 lines for readability)
outcome = chip_group("5) Outcome", OUTCOMES, key="chip_outcome", cols=4)

# 6) Second Chance — chips
second_chance = chip_group("6) 2nd Chance?", ["No","Yes"], key="chip_second", cols=2)

# Quarter preset (already saved per game; show it here for clarity)
st.markdown(f"**Quarter preset:** {meta.get('quarter', 'Q1')}  |  **Opponent:** {meta.get('opponent','')}  |  **Game Type:** {meta.get('type','Game')}")

# Optional Player tag (single select)
player = st.selectbox("Player involved (optional)", ["—"] + ss["roster"])

# Confirm button — fill + confirm (safer)
confirm = st.button("✅ Add Entry")

if confirm:
    # Validate minimal fields
    if not ts.strip():
        st.warning("Please enter the timestamp (game clock) before adding.")
    elif not ss["selected_plays"]:
        st.warning("Please select at least one play name.")
    else:
        # For multiple plays selected, create one row per play (same metadata)
        rows_added = 0
        for play in sorted(ss["selected_plays"], key=str.lower):
            entry = {
                "Timestamp": ts.strip(),
                "Play Name": play,
                "Call Type": call_type,
                "Caller": caller,
                "Outcome": outcome,
                "Points": points_from_outcome(outcome),
                "2nd Chance?": second_chance,
                "Quarter": meta.get("quarter","Q1"),
                "Opponent": meta.get("opponent",""),
                "Player": (None if player=="—" else player),
                "Game Type": meta.get("type","Game"),
            }
            ss["game_data"][game].append(entry)
            if USE_SHEETS:
                sheets_append_play(game, [
                    entry["Timestamp"], entry["Play Name"], entry["Call Type"], entry["Caller"],
                    entry["Outcome"], entry["Points"], entry["2nd Chance?"],
                    entry["Quarter"], entry["Opponent"], entry["Player"] or "", entry["Game Type"]
                ])
            rows_added += 1

        st.success(f"Added {rows_added} entr{'y' if rows_added==1 else 'ies'} for {game}.")

        # Reset for next possession: clear timestamp & selected plays only
        for name in list(ss["selected_plays"]):
            # Uncheck the checkboxes by resetting their widget keys
            st.session_state[f"play_chk_{name}"] = False
        ss["selected_plays"].clear()
        st.session_state["1) Timestamp (game clock, e.g., 6:37 Q2)"] = ""  # best effort, Streamlit might ignore this
        # Keep call_type, caller, outcome, second_chance, and quarter sticky by design


# =======================
# Table + Export
# =======================
df = pd.DataFrame(ss["game_data"][game])
st.subheader(f"Logged Plays — {game}")
st.dataframe(df, use_container_width=True, height=320)
if not df.empty:
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download CSV", data=csv, file_name=f"{game.replace(' ','_')}_plays.csv", mime="text/csv")

# =======================
# Analytics (hide in game mode)
# =======================
if not game_mode and not df.empty:
    st.subheader("Quick Analytics")

    # Filters
    fcols = st.columns(4)
    with fcols[0]:
        f_quarter = st.multiselect("Filter: Quarter", ["Q1","Q2","Q3","Q4","OT"])
    with fcols[1]:
        f_opp = st.text_input("Filter: Opponent (contains)", "")
    with fcols[2]:
        f_2nd = st.selectbox("Filter: 2nd Chance", ["All","Yes","No"])
    with fcols[3]:
        f_type = st.selectbox("Filter: Game Type", ["All","Game","Scrimmage","Scout"])

    f = df.copy()
    if f_quarter: f = f[f["Quarter"].isin(f_quarter)]
    if f_opp: f = f[f["Opponent"].str.contains(f_opp, case=False, na=False)]
    if f_2nd != "All": f = f[f["2nd Chance?"] == f_2nd]
    if f_type != "All": f = f[f["Game Type"] == f_type]

    if f.empty:
        st.info("No rows match filters.")
    else:
        # PPP by Play (top by volume)
        ppp_by_play = f.groupby("Play Name")["Points"].mean().reset_index().rename(columns={"Points":"PPP"})
        ppp_by_play["Count"] = f.groupby("Play Name")["Points"].count().values
        top = ppp_by_play.sort_values("Count", ascending=False).head(12)
        st.altair_chart(
            alt.Chart(top).mark_bar().encode(
                x=alt.X("PPP:Q"),
                y=alt.Y("Play Name:N", sort="-x"),
                tooltip=["Play Name","PPP","Count"]
            ).properties(height=300, title="PPP by Play (Top by volume)"),
            use_container_width=True
        )

        # PPP by Call Type
        ppp_type = f.groupby("Call Type")["Points"].mean().reset_index().rename(columns={"Points":"PPP"})
        st.altair_chart(
            alt.Chart(ppp_type).mark_bar().encode(
                x=alt.X("Call Type:N", sort="-y"),
                y=alt.Y("PPP:Q"),
                tooltip=["Call Type","PPP"]
            ).properties(height=300, title="PPP by Call Type"),
            use_container_width=True
        )

        # PPP by Quarter
        ppp_q = f.groupby("Quarter")["Points"].mean().reset_index().rename(columns={"Points":"PPP"})
        st.altair_chart(
            alt.Chart(ppp_q).mark_bar().encode(
                x=alt.X("Quarter:N"),
                y=alt.Y("PPP:Q"),
                tooltip=["Quarter","PPP"]
            ).properties(height=300, title="PPP by Quarter"),
            use_container_width=True
        )

        # PPP vs Opponent
        if f["Opponent"].notna().any():
            ppp_opp = f.groupby("Opponent")["Points"].mean().reset_index().rename(columns={"Points":"PPP"})
            st.altair_chart(
                alt.Chart(ppp_opp).mark_bar().encode(
                    x=alt.X("Opponent:N", sort="-y"),
                    y=alt.Y("PPP:Q"),
                    tooltip=["Opponent","PPP"]
                ).properties(height=300, title="PPP vs Opponent"),
                use_container_width=True
            )

        # 2nd Chance vs Normal
        f2 = f.assign(second=lambda d: d["2nd Chance?"].fillna("No"))
        ppp_2nd = f2.groupby("second")["Points"].mean().reset_index().rename(columns={"second":"2nd Chance?","Points":"PPP"})
        st.altair_chart(
            alt.Chart(ppp_2nd).mark_bar().encode(
                x=alt.X("2nd Chance?:N"),
                y=alt.Y("PPP:Q"),
                tooltip=["2nd Chance?","PPP"]
            ).properties(height=300, title="PPP: 2nd Chance vs Normal"),
            use_container_width=True
        )
