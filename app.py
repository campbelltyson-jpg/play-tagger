import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

# =======================
# Google Sheets (optional)
# =======================
USE_SHEETS = False
gc = None
sh = None

def init_sheets():
    """
    Init Sheets from Streamlit secrets.
    Expects:
      SHEET_ID
      [gcp_service_account] block
    """
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

        # ensure baseline tabs exist
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

        playbook = pd.DataFrame(sh.worksheet("Playbook").get_all_records())
        games = pd.DataFrame(sh.worksheet("Games").get_all_records())
        roster = pd.DataFrame(sh.worksheet("Roster").get_all_records())
        return playbook, games, roster
    except Exception:
        st.info("Running without Google Sheets sync. Add Streamlit secrets to enable cloud sync.")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def get_or_create_game_ws(game_name: str):
    ws_title = f"Game - {game_name}"
    ws_names = [ws.title for ws in sh.worksheets()]
    if ws_title not in ws_names:
        ws = sh.add_worksheet(ws_title, rows=5000, cols=30)
        ws.update("A1:K1", [[
            "Timestamp","Play Name","Call Type","Caller","Outcome","Points","2nd Chance?",
            "Quarter","Opponent","Player","Game Type"
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

# ===== helper to filter games by type (must exist BEFORE using it)
def _games_by_type(view: str, games, meta):
    if view == "All":
        return sorted(games)
    out = [g for g in games if meta.get(g, {}).get("type", "Game") == view]
    return sorted(out) if out else ["(none)"]

# =======================
# App config & state
# =======================
st.set_page_config(page_title="Play Tagger v3", layout="wide")

# load sheets (if available)
playbook_df, games_df, roster_df = init_sheets()

# session defaults
ss = st.session_state
ss.setdefault("plays_master", ["Chin","Horns Over","Floppy","Zipper","Spain PnR"])
ss.setdefault("games", ["Scrimmage"])
ss.setdefault("game_data", {})             # dict[game] -> list[dict]
ss.setdefault("game_meta", {})             # dict[game] -> {"type": "...", "opponent": "..."}
ss.setdefault("roster", ["#1","%Lead Guard","#5 Big"])  # editable

# hydrate from sheets
if not playbook_df.empty:
    merged = [p for p in playbook_df.get("Play Name", []).tolist() if p]
    if merged:
        ss["plays_master"] = sorted(set(merged))
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
    # Safe logo call: only shows if you later define logo_image_bytes()
    try:
        st.image(logo_image_bytes(), caption=None, use_column_width=True)  # noqa: F821
    except Exception:
        pass

# UI polish CSS (keep as one block if you want)
st.markdown("""
<style>
/* Larger touch targets */
.stSelectbox>div>div, .stTextInput>div>div>input, .stButton>button, .stRadio>div,
.stTextInput>div>div>input { font-size: 1.05rem; }
.stButton>button { padding: 0.6rem 0.9rem; border-radius: 10px; }
/* Dark tidy borders */
[data-baseweb="select"] div { background: transparent; }
.stDataFrame { border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; }
.stDownloadButton button { border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# ===== Game-type chips (filters the game dropdown) =====
type_chip = st.radio(
    "View games by type",
    ["All", "Game", "Scrimmage", "Scout"],
    horizontal=True,
)

# =======================
# Sidebar: Game/Roster/Playbook
# =======================
with st.sidebar:
    st.header("Game Manager")

    # Build filtered game list for the dropdown based on chip
    filtered_games = _games_by_type(type_chip, ss["games"], ss["game_meta"])
    game = st.selectbox("Select Game", options=filtered_games, index=0)

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

    st.divider()
    st.header("Playbook")
    with st.expander("Add Play Call"):
        np = st.text_input("Play Name")
        ncode = st.text_input("Short Code (optional)")
        nsys = st.text_input("System/Group (optional)")
        if st.button("Add Play"):
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

# ensure containers
ss["game_data"].setdefault(game, [])
ss["game_meta"].setdefault(game, {})
meta = ss["game_meta"][game]
meta.setdefault("type", meta.get("type", "Game"))
meta.setdefault("opponent", meta.get("opponent", ""))

# =======================
# Tagging form
# =======================
st.title("🏀 Play Call Tagging (v3)")

with st.form("tag_form", clear_on_submit=True):
    cols = st.columns([1,1,1,1,1,1,1,1])
    with cols[0]:
        use_now = st.checkbox("Now", value=True)
        ts = datetime.now().strftime("%H:%M:%S") if use_now else st.text_input("Timestamp", value="")
    with cols[1]:
        play_name = st.selectbox("Play Name", options=ss["plays_master"])
    with cols[2]:
        call_type = st.selectbox("Call Type", ["Early Offense","Halfcourt","BLOB","SLOB","Zone"])
    with cols[3]:
        caller = st.selectbox("Caller", ["Coach","Player"])
    with cols[4]:
        outcome = st.selectbox("Outcome", ["Made 2","Missed 2","Made 3","Missed 3","Foul (Made 1/2)","Foul (Made 2/2)","Foul (Missed Both)","Turnover","Dead Ball"])
    with cols[5]:
        second_chance = st.selectbox("2nd Chance?", ["No","Yes"])
    with cols[6]:
        quarter = st.selectbox("Quarter", ["Q1","Q2","Q3","Q4","OT"])
    with cols[7]:
        player = st.selectbox("Player (opt.)", ["—"] + ss["roster"])

    sub_cols = st.columns([2,2,1])
    with sub_cols[0]:
        meta["opponent"] = st.text_input("Opponent (saved per game)", value=meta.get("opponent",""))
    with sub_cols[1]:
        meta["type"] = st.selectbox("Game Type (saved per game)", ["Game","Scrimmage","Scout"], index=["Game","Scrimmage","Scout"].index(meta.get("type","Game")))
    with sub_cols[2]:
        submitted = st.form_submit_button("Add Entry", use_container_width=True)

def points_from_outcome(o: str) -> int:
    return 2 if o=="Made 2" else 3 if o=="Made 3" else 1 if o=="Foul (Made 1/2)" else 2 if o=="Foul (Made 2/2)" else 0

if submitted:
    entry = {
        "Timestamp": ts,
        "Play Name": play_name,
        "Call Type": call_type,
        "Caller": caller,
        "Outcome": outcome,
        "Points": points_from_outcome(outcome),
        "2nd Chance?": second_chance,
        "Quarter": quarter,
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
    st.toast("Play logged.", icon="✅")

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

    # filters
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
        top = ppp_by_play.sort_values("Count", ascending=False).head(10)
        chart1 = alt.Chart(top).mark_bar().encode(
            x=alt.X("PPP:Q"),
            y=alt.Y("Play Name:N", sort="-x"),
            tooltip=["Play Name","PPP","Count"]
        ).properties(height=300, title="PPP by Play (Top 10 by volume)")
        st.altair_chart(chart1, use_container_width=True)

        # PPP by Call Type
        ppp_type = f.groupby("Call Type")["Points"].mean().reset_index().rename(columns={"Points":"PPP"})
        chart2 = alt.Chart(ppp_type).mark_bar().encode(
            x=alt.X("Call Type:N", sort="-y"),
            y=alt.Y("PPP:Q"),
            tooltip=["Call Type","PPP"]
        ).properties(height=300, title="PPP by Call Type")
        st.altair_chart(chart2, use_container_width=True)

        # PPP by Quarter
        ppp_q = f.groupby("Quarter")["Points"].mean().reset_index().rename(columns={"Points":"PPP"})
        chart3 = alt.Chart(ppp_q).mark_bar().encode(
            x=alt.X("Quarter:N"),
            y=alt.Y("PPP:Q"),
            tooltip=["Quarter","PPP"]
        ).properties(height=300, title="PPP by Quarter")
        st.altair_chart(chart3, use_container_width=True)

        # PPP vs Opponent (last N seen)
        if f["Opponent"].notna().any():
            ppp_opp = f.groupby("Opponent")["Points"].mean().reset_index().rename(columns={"Points":"PPP"})
            chart4 = alt.Chart(ppp_opp).mark_bar().encode(
                x=alt.X("Opponent:N", sort="-y"),
                y=alt.Y("PPP:Q"),
                tooltip=["Opponent","PPP"]
            ).properties(height=300, title="PPP vs Opponent")
            st.altair_chart(chart4, use_container_width=True)

        # 2nd Chance vs Normal
        f2 = f.assign(second=lambda d: d["2nd Chance?"].fillna("No"))
        ppp_2nd = f2.groupby("second")["Points"].mean().reset_index().rename(columns={"second":"2nd Chance?","Points":"PPP"})
        chart5 = alt.Chart(ppp_2nd).mark_bar().encode(
            x=alt.X("2nd Chance?:N"),
            y=alt.Y("PPP:Q"),
            tooltip=["2nd Chance?","PPP"]
        ).properties(height=300, title="PPP: 2nd Chance vs Normal")
        st.altair_chart(chart5, use_container_width=True)
