# app.py — Play Tagger v7.0.1 (full)
import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

# =======================
# CONFIG
# =======================
st.set_page_config(page_title="Play Tagger v7.0.1", layout="wide")

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
_sheets_error = None

def init_sheets():
    """Initialize Sheets using secrets. Creates core tabs if missing."""
    global USE_SHEETS, gc, sh, _sheets_error
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
    except Exception as e:
        _sheets_error = str(e)
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
        ws.update("A1:K1", [GAME_HEADERS])
    else:
        ws = sh.worksheet(ws_title)
        header = ws.row_values(1)
        if header != GAME_HEADERS:
            ws.update("A1:K1", [GAME_HEADERS])
    return ws

def sheets_append_play(game_name: str, row: list):
    ws = get_or_create_game_ws(game_name)
    ws.append_row(row, value_input_option="USER_ENTERED")

def sheets_overwrite_game(game_name: str, df: pd.DataFrame):
    ws = get_or_create_game_ws(game_name)
    ws.resize(rows=1)  # keep header only
    if df.empty:
        ws.update("A1:K1", [GAME_HEADERS])
        return
    # ensure column order
    for col in GAME_HEADERS:
        if col not in df.columns:
            df[col] = ""
    df = df[GAME_HEADERS].fillna("")
    values = [GAME_HEADERS] + df.values.tolist()
    ws.update(f"A1:K{len(values)}", values)

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
    "Turnover","Dead Ball","Timeout","Dead Ball Foul"
]
SECOND_CHANCE_OUTCOMES = ["Made 2","Missed 2","Made 3","Missed 3","Foul","Turnover","Reset/Other"]

def points_from_outcome(o: str) -> int:
    return 2 if o=="Made 2" else 3 if o=="Made 3" else 1 if o=="Foul (Made 1/2)" else 2 if o=="Foul (Made 2/2)" else 0

# =======================
# CHIP HELPERS
# =======================
def chip_check_group(label, options, key, cols=4, default_selected=None):
    """Checkbox-chip grid (multi). Stores a set in st.session_state[key]."""
    st.markdown(f"**{label}**")
    if default_selected is None:
        default_selected = []
    st.session_state.setdefault(key, set(default_selected))
    selected = set(st.session_state[key])
    col_list = st.columns(cols)
    for i, opt in enumerate(options):
        with col_list[i % cols]:
            checked = st.checkbox(opt, value=(opt in selected), key=f"{key}__{opt}")
            if checked:
                selected.add(opt)
            else:
                selected.discard(opt)
    st.session_state[key] = selected
    return sorted(selected)

# =======================
# STATE
# =======================
ss = st.session_state
ss.setdefault("plays_master", PLAY_NAMES.copy())
ss.setdefault("games", ["Default Game"])
ss.setdefault("game_meta", {})  # name -> {"quarter": "Q1", "opponent": "", "type": "Game"}
ss.setdefault("current_game", "Default Game")
ss.setdefault("game_data", {})  # name -> list of dict rows
ss.setdefault("roster", ["#1", "#2", "#3"])
ss.setdefault("selected_plays", set())
ss.setdefault("game_clock_min", 12)
ss.setdefault("game_clock_sec", "59")
ss.setdefault("pending_action", None)

# =======================
# CSS
# =======================
st.markdown(
    "<style>"
    ".stButton > button { border-radius: 999px; padding: 0.8rem 1.1rem; font-size: 1.05rem; }"
    ".stDataFrame { border-radius: 10px; }"
    ".quickbar button { margin-bottom: 6px; }"
    "</style>",
    unsafe_allow_html=True
)

# =======================
# INIT SHEETS + HYDRATE
# =======================
sheets_connected = init_sheets()
if sheets_connected:
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
                    if r.get("Type"):
                        meta["type"] = r["Type"]
                    if r.get("Opponent"):
                        meta["opponent"] = r["Opponent"]
            ss["games"] = sorted(set(ss["games"]))
    except Exception:
        pass

ss["game_data"].setdefault(ss["current_game"], [])
ss["game_meta"].setdefault(ss["current_game"], {"quarter": "Q1", "opponent": "", "type": "Game"})

# =======================
# HEADER + LOGO + SHEETS STATUS
# =======================
c1, c2, c3 = st.columns([1,2,1])
with c2:
    _logo = logo_image_bytes()
    if _logo:
        st.image(_logo, use_container_width=True)

status = "✅ Connected to Google Sheets" if sheets_connected else "⚠️ Running locally (no Sheets sync)"
st.caption(status)

st.title("🏀 Play Call Tagging v7.0.1")

# =======================
# GAME MANAGER (TOP BAR)
# =======================
gm1, gm2, gm3, gm4 = st.columns([2,2,2,2])
with gm1:
    current_game = st.selectbox(
        "Current Game",
        options=ss["games"],
        index=ss["games"].index(ss["current_game"]) if ss["current_game"] in ss["games"] else 0
    )
    if current_game != ss["current_game"]:
        ss["current_game"] = current_game
        ss["game_data"].setdefault(ss["current_game"], [])
        ss["game_meta"].setdefault(ss["current_game"], {"quarter": "Q1", "opponent": "", "type": "Game"})

with gm2:
    meta = ss["game_meta"].setdefault(ss["current_game"], {"quarter": "Q1", "opponent": "", "type": "Game"})
    meta["quarter"] = st.selectbox(
        "Quarter (preset)", ["Q1","Q2","Q3","Q4","OT"],
        index=["Q1","Q2","Q3","Q4","OT"].index(meta.get("quarter","Q1"))
    )

with gm3:
    meta["opponent"] = st.text_input("Opponent (saved per game)", value=meta.get("opponent",""))

with gm4:
    meta["type"] = st.selectbox(
        "Game Type", ["Game","Scrimmage","Scout"],
        index=["Game","Scrimmage","Scout"].index(meta.get("type","Game"))
    )

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
                if sheets_connected:
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
                if sheets_connected:
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
        if sheets_connected:
            ws = sh.worksheet("Roster")
            ws.clear()
            ws.update("A1:A1", [["Player"]])
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
# 3–6) Call Type / Caller / 2nd Chance / Outcomes (multi)
# =======================
sel_call_types = chip_check_group("3) Call Type (multi)", CALL_TYPES, key="ms_call_types", cols=4, default_selected=[CALL_TYPES[0]])
caller = st.radio("4) Who called it?", CALLERS, horizontal=True, index=0)
second_chance = st.radio("5) 2nd Chance?", ["No","Yes"], horizontal=True, index=0)
sc_outcome = None
if second_chance == "Yes":
    sc_outcome = st.radio("Second‑Chance Outcome", SECOND_CHANCE_OUTCOMES, horizontal=False, index=0)
sel_outcomes = chip_check_group("6) Outcome (multi)", OUTCOMES, key="ms_outcomes", cols=4, default_selected=["Made 2","Made 3"])

meta = ss["game_meta"][ss["current_game"]]
quarter = meta.get("quarter", "Q1")
opponent = meta.get("opponent", "")
game_type = meta.get("type", "Game")

def _row_dict(play, ts, outc, sc_flag, sc_detail, call_type_val):
    return {
        "Timestamp": ts,
        "Play Name": play,
        "Call Type": call_type_val,
        "Caller": caller,
        "Outcome": outc,
        "Points": points_from_outcome(outc),
        "2nd Chance?": sc_flag,
        "2nd Chance Outcome": (sc_detail or ""),
        "Quarter": quarter,
        "Opponent": opponent,
        "Game Type": game_type
    }

def _push_to_sheets_row(r):
    if sheets_connected:
        sheets_append_play(ss["current_game"], [
            r["Timestamp"], r["Play Name"], r["Call Type"], r["Caller"],
            r["Outcome"], r["Points"], r["2nd Chance?"], r["2nd Chance Outcome"],
            r["Quarter"], r["Opponent"], r["Game Type"]
        ])

# =======================
# QUICK BAR (with Confirm) — uses multi Call Types
# =======================
st.markdown("**Quick Bar**")
q1, q2, q3, q4, q5, q6 = st.columns(6)
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

if ss.get("pending_action"):
    with st.container(border=True):
        st.write(
            f"Pending: **{ss['pending_action']}** | Plays: **{', '.join(sorted(ss['selected_plays'])) or '(none)'}** "
            f"| Call Types: **{', '.join(sel_call_types) or '(default)'}** | Clock: **{game_clock}** | Q: **{quarter}**"
        )
        if second_chance == "Yes":
            st.write(f"2nd‑Chance Outcome: **{sc_outcome or '(select)'}**")
        c1, c2 = st.columns([1,1])
        with c1:
            if st.button("Confirm"):
                if not ss["selected_plays"]:
                    st.warning("Select at least one play.")
                else:
                    rows = []
                    call_types_iter = sel_call_types or [CALL_TYPES[0]]
                    for play in sorted(ss["selected_plays"], key=str.lower):
                        for ct in call_types_iter:
                            r = _row_dict(play, game_clock, ss["pending_action"], second_chance, sc_outcome, ct)
                            rows.append(r)
                    ss["game_data"].setdefault(ss["current_game"], []).extend(rows)
                    for r in rows:
                        _push_to_sheets_row(r)
                    st.success(f"Logged {len(rows)} entr{'y' if len(rows)==1 else 'ies'} via Quick Bar.")
                    ss["selected_plays"].clear()
                    ss["pending_action"] = None
                    st.rerun()
        with c2:
            if st.button("Cancel"):
                ss["pending_action"] = None
                st.info("Quick action canceled.")

# =======================
# STANDARD ADD ENTRY (multi × multi)
# =======================
if st.button("✅ Add Entry", use_container_width=True):
    if not ss["selected_plays"]:
        st.warning("Select at least one play.")
    else:
        rows = []
        call_types_iter = sel_call_types or [CALL_TYPES[0]]
        outcomes_iter = sel_outcomes or ["Made 2"]
        for play in sorted(ss["selected_plays"], key=str.lower):
            for ct in call_types_iter:
                for oc in outcomes_iter:
                    r = _row_dict(play, game_clock, oc, second_chance, sc_outcome, ct)
                    rows.append(r)
        ss["game_data"].setdefault(ss["current_game"], []).extend(rows)
        for r in rows:
            _push_to_sheets_row(r)
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
    fcol = st.columns([2,1,1,1])
    with fcol[0]:
        q_filter = st.multiselect("Filter by Quarter", ["Q1","Q2","Q3","Q4","OT"],
                                  default=["Q1","Q2","Q3","Q4","OT"])
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
            updated = edited.drop(columns=["Select"]).set_index("Row").sort_index()
            master = df.copy()
            for row_idx, row_vals in updated.iterrows():
                master.iloc[row_idx] = row_vals[master.columns]
            ss["game_data"][ss["current_game"]] = master.to_dict(orient="records")
            if sheets_connected:
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
                if sheets_connected:
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

# =======================
# LIVE DASHBOARD
# =======================
st.divider()
st.subheader("📊 Live Dashboard")

ar_col1, ar_col2, _ = st.columns([1,1,3])
with ar_col1:
    auto_refresh = st.toggle("Auto‑refresh", value=False, help="Updates every few seconds")
with ar_col2:
    interval = st.selectbox("Interval (s)", [2,3,5,10], index=2, disabled=not auto_refresh)

if auto_refresh:
    st.autorefresh(interval=interval * 1000, key="live_refresh_key")

if df.empty:
    st.info("No data yet for visuals.")
else:
    vis = df.copy()

    outcome_map = {
        "Made 2":"Made 2", "Missed 2":"Miss 2",
        "Made 3":"Made 3", "Missed 3":"Miss 3",
        "Foul (Made 1/2)":"Foul 1/2", "Foul (Made 2/2)":"Foul 2/2", "Foul (Missed Both)":"Foul 0/2",
        "Turnover":"TO", "Dead Ball":"Dead", "Timeout":"TOUT", "Dead Ball Foul":"DB Foul"
    }
    vis["OutcomeShort"] = vis["Outcome"].map(outcome_map).fillna(vis["Outcome"])
    vis["Count"] = 1

    call_stack = (
        alt.Chart(vis)
        .mark_bar()
        .encode(
            x=alt.X("sum(Count):Q", title="Possessions"),
            y=alt.Y("Call Type:N", sort="-x", title="Call Type"),
            color=alt.Color("OutcomeShort:N", title="Outcome"),
            tooltip=["Call Type","OutcomeShort","Count:Q"]
        )
        .properties(height=300, title="Outcomes by Call Type (stacked)")
    )

    topN = st.slider("Top N Plays (by volume)", 5, 20, 10)
    top_plays = (
        vis.groupby("Play Name")["Count"].count().sort_values(ascending=False).head(topN).index.tolist()
    )
    vis_top = vis[vis["Play Name"].isin(top_plays)]
    play_stack = (
        alt.Chart(vis_top)
        .mark_bar()
        .encode(
            x=alt.X("sum(Count):Q", title="Possessions"),
            y=alt.Y("Play Name:N", sort="-x", title="Play Name"),
            color=alt.Color("OutcomeShort:N", title="Outcome"),
            tooltip=["Play Name","OutcomeShort","Count:Q"]
        )
        .properties(height=300, title=f"Outcomes by Play (Top {topN})")
    )

    def mmss_to_seconds(s):
        try:
            m, sec = s.split(":")
            return int(m) * 60 + int(sec)
        except Exception:
            return 0
    orderer = vis.copy()
    orderer["ClockSec"] = orderer["Timestamp"].apply(mmss_to_seconds)
    q_order = {"Q1":1, "Q2":2, "Q3":3, "Q4":4, "OT":5}
    orderer["Qnum"] = orderer["Quarter"].map(q_order).fillna(99)
    orderer = orderer.sort_values(["Qnum", "ClockSec"], ascending=[True, False]).reset_index(drop=True)
    orderer["CumPoss"] = range(1, len(orderer) + 1)
    orderer["CumPts"] = orderer["Points"].cumsum()
    orderer["PPP"] = orderer["CumPts"] / orderer["CumPoss"]

    ppp_line = (
        alt.Chart(orderer)
        .mark_line(point=True)
        .encode(
            x=alt.X("CumPoss:Q", title="Possessions (game order)"),
            y=alt.Y("PPP:Q", title="Cumulative PPP"),
            tooltip=["CumPoss","PPP","Quarter","Timestamp","Play Name","OutcomeShort"]
        )
        .properties(height=260, title="Cumulative PPP (live)")
    )

    cA, cB = st.columns(2)
    with cA:
        st.altair_chart(call_stack, use_container_width=True)
        st.altair_chart(ppp_line, use_container_width=True)
    with cB:
        st.altair_chart(play_stack, use_container_width=True)

# =======================
# GOOGLE SHEETS — STATUS, TEST & POSTGAME UPLOAD (simplified)
# =======================
st.divider()
with st.expander("🧰 Google Sheets — Status & Postgame Upload"):
    if sheets_connected:
        st.success("✅ Connected to Google Sheets.")
        t1, t2, t3 = st.columns([1,1,2])
        with t1:
            if st.button("🔎 List Worksheets"):
                names = [ws.title for ws in sh.worksheets()]
                st.write(names)
        with t2:
            if st.button("🧪 Test Write (current game)"):
                try:
                    sheets_append_play(ss["current_game"], [
                        "TEST", "Test Play", "Half Court", "Coach",
                        "Turnover", 0, "No", "", "Q1", "Test Opp", "Game"
                    ])
                    st.success("Wrote a test row to the game worksheet.")
                except Exception as e:
                    st.error(f"Test write failed: {e}")
        with t3:
            st.caption("If you don't see new tabs, share the Sheet with your service account email.")

        st.markdown("**Postgame CSV → Google Sheet**")
        up = st.file_uploader("Upload a CSV exported from this app", type=["csv"])
        pgcols = st.columns([2,1])
        with pgcols[0]:
            target_game = st.text_input("Game name to write into (creates if missing)", value=ss["current_game"])
        with pgcols[1]:
            do_overwrite = st.checkbox("Overwrite game tab (recommended)", value=True)
        if up is not None and st.button("⬆️ Push CSV to Google Sheet"):
            try:
                df_up = pd.read_csv(up)
                if do_overwrite:
                    sheets_overwrite_game(target_game, df_up)
                else:
                    for r in df_up.fillna("").to_dict(orient="records"):
                        sheets_append_play(target_game, [
                            r.get("Timestamp",""), r.get("Play Name",""), r.get("Call Type",""), r.get("Caller",""),
                            r.get("Outcome",""), r.get("Points",0), r.get("2nd Chance?",""), r.get("2nd Chance Outcome",""),
                            r.get("Quarter",""), r.get("Opponent",""), r.get("Game Type","")
                        ])
                st.success(f"Uploaded {len(df_up)} rows into '{target_game}'.")
            except Exception as e:
                st.error(f"Upload failed: {e}")
    else:
        st.warning("⚠️ Not connected to Google Sheets.")
        if _sheets_error:
            st.code(_sheets_error, language="text")
        st.caption("Tip: Add SHEET_ID and gcp_service_account JSON in Streamlit → Settings → Secrets, then redeploy.")
