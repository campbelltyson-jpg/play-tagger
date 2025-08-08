import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

# ---------- Google Sheets helpers (optional) ----------
USE_SHEETS = False
gc = None
sh = None

def _init_sheets():
    """Initialize gspread client from Streamlit secrets; return (worksheet_map, playbook_df, games_df)."""
    global gc, sh, USE_SHEETS
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        secrets = st.secrets
        creds_info = secrets["gcp_service_account"]  # <-- set in Streamlit Secrets
        sheet_id = secrets["SHEET_ID"]

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        USE_SHEETS = True

        ws_names = [ws.title for ws in sh.worksheets()]

        # Ensure Playbook + Games sheets exist
        if "Playbook" not in ws_names:
            sh.add_worksheet("Playbook", rows=1000, cols=2)
            sh.worksheet("Playbook").update("A1:B1", [["Code","Play Name"]])

        if "Games" not in ws_names:
            sh.add_worksheet("Games", rows=1000, cols=2)
            sh.worksheet("Games").update("A1:B1", [["Game Name","Created At"]])

        playbook = pd.DataFrame(sh.worksheet("Playbook").get_all_records())
        games = pd.DataFrame(sh.worksheet("Games").get_all_records())
        return playbook, games

    except Exception as e:
        st.info("Running without Google Sheets sync. (Add Streamlit secrets to enable.)")
        return pd.DataFrame(), pd.DataFrame()

def _get_or_create_game_ws(game_name: str):
    """Return gspread worksheet for the game; create if missing."""
    ws_title = f"Game - {game_name}"
    ws_names = [ws.title for ws in sh.worksheets()]
    if ws_title not in ws_names:
        ws = sh.add_worksheet(ws_title, rows=5000, cols=20)
        ws.update("A1:G1", [[
            "Timestamp","Play Name","Call Type","Caller",
            "Outcome","Points","2nd Chance?"
        ]])
    return sh.worksheet(ws_title)

def _append_row_to_game(game_name: str, row: list):
    ws = _get_or_create_game_ws(game_name)
    ws.append_row(row, value_input_option="USER_ENTERED")

def _write_play_to_playbook(play_name: str, code: str = ""):
    ws = sh.worksheet("Playbook")
    ws.append_row([code, play_name], value_input_option="USER_ENTERED")

def _write_game_to_games(game_name: str):
    ws = sh.worksheet("Games")
    ws.append_row([game_name, datetime.now().isoformat(timespec="seconds")], value_input_option="USER_ENTERED")

# ---------- App State ----------
st.set_page_config(page_title="Basketball Play Tagger", layout="wide")
if "plays_master" not in st.session_state:
    # Default starter list; will be overridden by Playbook if Sheets enabled
    st.session_state.plays_master = ["Chin", "Horns Over", "Floppy", "Zipper", "Spain PnR"]
if "games" not in st.session_state:
    st.session_state.games = ["Scrimmage"]
if "game_data" not in st.session_state:
    st.session_state.game_data = {}  # key: game_name -> list[dict]

# Load Google Sheets if available
playbook_df, games_df = _init_sheets()
if not playbook_df.empty:
    # Use Playbook names (unique, drop blanks)
    sheet_plays = [p for p in playbook_df.get("Play Name", []).tolist() if p]
    if sheet_plays:
        st.session_state.plays_master = sorted(list(set(sheet_plays)))
if not games_df.empty:
    sheet_games = [g for g in games_df.get("Game Name", []).tolist() if g]
    if sheet_games:
        st.session_state.games = sorted(list(set(sheet_games)))

# ---------- Sidebar: Game + Playbook Management ----------
with st.sidebar:
    st.header("Game Manager")
    game = st.selectbox("Select Game", options=st.session_state.games)
    new_game = st.text_input("Create new game")
    if st.button("➕ Add Game"):
        if new_game.strip():
            if new_game not in st.session_state.games:
                st.session_state.games.append(new_game)
                st.session_state.games.sort()
                if USE_SHEETS:
                    _write_game_to_games(new_game)
                st.success(f"Game '{new_game}' created.")
            game = new_game
        else:
            st.warning("Enter a game name first.")

    st.divider()
    st.header("Playbook")
    with st.popover("➕ Add Play Call"):
        new_play = st.text_input("Play Name", key="new_play_name")
        short_code = st.text_input("Optional Code (for your reference)", key="new_play_code")
        if st.button("Add to Playbook", key="add_play_btn"):
            if new_play.strip():
                if new_play not in st.session_state.plays_master:
                    st.session_state.plays_master.append(new_play)
                    st.session_state.plays_master.sort()
                    if USE_SHEETS:
                        _write_play_to_playbook(new_play.strip(), short_code.strip())
                    st.success(f"Added play: {new_play}")
            else:
                st.warning("Enter a play name.")

# Ensure game_data container for selected game
st.session_state.game_data.setdefault(game, [])

st.title("🏀 Play Call Tagging (v2)")
st.caption("Preloaded plays, multi‑game tracking, optional Google Sheets sync, and built‑in PPP charts.")

# ---------- Tagging Form ----------
with st.form("tag_form", clear_on_submit=True):
    cols = st.columns([1,1,1,1,1,1,1])
    with cols[0]:
        use_now = st.checkbox("Now", value=True)
        ts = datetime.now().strftime("%H:%M:%S") if use_now else st.text_input("Timestamp", value="")
    with cols[1]:
        play_name = st.selectbox("Play Name", options=st.session_state.plays_master)
    with cols[2]:
        call_type = st.selectbox("Call Type", ["Early Offense","Halfcourt","BLOB","SLOB","Zone"])
    with cols[3]:
        caller = st.selectbox("Caller", ["Coach","Player"])
    with cols[4]:
        outcome = st.selectbox(
            "Outcome",
            ["Made 2","Missed 2","Made 3","Missed 3","Foul (Made 1/2)","Foul (Made 2/2)","Foul (Missed Both)","Turnover","Dead Ball"]
        )
    with cols[5]:
        second_chance = st.selectbox("2nd Chance?", ["No","Yes"])
    with cols[6]:
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
        "2nd Chance?": second_chance
    }
    st.session_state.game_data[game].append(entry)
    if USE_SHEETS:
        _append_row_to_game(game, [
            entry["Timestamp"], entry["Play Name"], entry["Call Type"], entry["Caller"],
            entry["Outcome"], entry["Points"], entry["2nd Chance?"]
        ])
    st.toast("Play logged.", icon="✅")

# ---------- Table + Export ----------
df = pd.DataFrame(st.session_state.game_data[game])
st.subheader(f"Logged Plays — {game}")
st.dataframe(df, use_container_width=True, height=320)

if not df.empty:
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download CSV", data=csv, file_name=f"{game.replace(' ','_')}_plays.csv", mime="text/csv")

# ---------- Quick Analytics ----------
if not df.empty:
    st.subheader("Quick Analytics")
    # Success definition: any non-zero points OR foul (even if 0 points?) -> your call. We'll use points>0.
    df["Success"] = df["Points"] > 0
    # PPP by Play Name (min 3 samples)
    ppp_by_play = df.groupby("Play Name")["Points"].mean().reset_index().rename(columns={"Points":"PPP"})
    ppp_by_play["Count"] = df.groupby("Play Name")["Points"].count().values
    top = ppp_by_play.sort_values("Count", ascending=False).head(10)

    chart1 = alt.Chart(top).mark_bar().encode(
        x=alt.X("PPP:Q"),
        y=alt.Y("Play Name:N", sort="-x"),
        tooltip=["Play Name","PPP","Count"]
    ).properties(height=300, title="PPP by Play (Top 10 by volume)")
    st.altair_chart(chart1, use_container_width=True)

    # PPP by Call Type
    ppp_type = df.groupby("Call Type")["Points"].mean().reset_index().rename(columns={"Points":"PPP"})
    chart2 = alt.Chart(ppp_type).mark_bar().encode(
        x=alt.X("Call Type:N", sort="-y"),
        y=alt.Y("PPP:Q"),
        tooltip=["Call Type","PPP"]
    ).properties(height=300, title="PPP by Call Type")
    st.altair_chart(chart2, use_container_width=True)

    # Caller effectiveness
    ppp_caller = df.groupby("Caller")["Points"].mean().reset_index().rename(columns={"Points":"PPP"})
    chart3 = alt.Chart(ppp_caller).mark_bar().encode(
        x=alt.X("Caller:N"),
        y=alt.Y("PPP:Q"),
        tooltip=["Caller","PPP"]
    ).properties(height=300, title="PPP by Caller")
    st.altair_chart(chart3, use_container_width=True)
