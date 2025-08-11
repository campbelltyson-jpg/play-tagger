# app.py — Play Tagger v7.1
import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

# ========= CONFIG =========
st.set_page_config(page_title="Play Tagger v7.1", layout="wide")

AUTO_DEC_SECONDS = 8  # auto-decrement game clock after logging

def logo_image_bytes():
    try:
        with open("Transition Defense.png", "rb") as f:
            return f.read()
    except Exception:
        return None

# ========= GOOGLE SHEETS (optional) =========
USE_SHEETS = False
gc = None
sh = None
_sheets_error = None

GAME_HEADERS = [
    "Timestamp","Plays","Credit Play","Call Type","Caller","Outcome","Points",
    "2nd Chance?","2nd Chance Outcome","Quarter","Opponent","Game Type"
]

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

def get_or_create_game_ws(game_name: str):
    ws_title = game_ws_title(game_name)
    ws_names = [ws.title for ws in sh.worksheets()]
    if ws_title not in ws_names:
        ws = sh.add_worksheet(ws_title, rows=6000, cols=len(GAME_HEADERS))
        ws.update("A1:L1", [GAME_HEADERS])
    else:
        ws = sh.worksheet(ws_title)
        header = ws.row_values(1)
        if header != GAME_HEADERS:
            ws.update("A1:L1", [GAME_HEADERS])
    return ws

def sheets_append_play(game_name: str, row: list):
    ws = get_or_create_game_ws(game_name)
    ws.append_row(row, value_input_option="USER_ENTERED")

def sheets_overwrite_game(game_name: str, df: pd.DataFrame):
    ws = get_or_create_game_ws(game_name)
    ws.resize(rows=1)  # keep header only
    if df.empty:
        ws.update("A1:L1", [GAME_HEADERS])
        return
    for col in GAME_HEADERS:
        if col not in df.columns:
            df[col] = ""
    df = df[GAME_HEADERS].fillna("")
    values = [GAME_HEADERS] + df.values.tolist()
    ws.update(f"A1:L{len(values)}", values)

def sheets_add_game(game_name: str, game_type: str, opponent: str):
    ws = sh.worksheet("Games")
    ws.append_row([game_name, game_type, opponent, datetime.now().isoformat(timespec="seconds")],
                  value_input_option="USER_ENTERED")
    get_or_create_game_ws(game_name)

def sheets_rename_game(old_name: str, new_name: str, new_type: str, new_opp: str, df_game: pd.DataFrame):
    """Copy-rename in Sheets: create new tab, write df, update Games row, delete old tab."""
    # Create/update new worksheet with data
    sheets_overwrite_game(new_name, df_game)

    # Update or insert Games row
    games_ws = sh.worksheet("Games")
    rows = games_ws.get_all_values()
    updated = False
    for i, row in enumerate(rows[1:], start=2):  # skip header
        if row and row[0] == old_name:
            games_ws.update(f"A{i}:C{i}", [[new_name, new_type, new_opp]])
            updated = True
            break
    if not updated:
        games_ws.append_row([new_name, new_type, new_opp, datetime.now().isoformat(timespec="seconds")],
                            value_input_option="USER_ENTERED")

    # Remove old worksheet (if exists)
    old_title = game_ws_title(old_name)
    try:
        sh.del_worksheet(sh.worksheet(old_title))
    except Exception:
        pass

# ========= DATA / CONSTANTS =========
PLAY_NAMES = [
    "Flow","Zoom","Shake","Broken Play","Random","Transition","Delay","Pistol",
    "7","Pitch","ATO","Open Sets","Elbow","Punch",
    "Spain","Roll","Step","Iverson","Gets","77","Rub","Slice","Rifle",
    "Triple Staggers","High","X","Flat 14","College","Mustang","Away"
]
CALL_TYPES_MASTER = ["Early Offense","Half Court","BLOB","SLOB","Zone"]
CALLERS = ["Coach","Player"]
QUARTERS = ["Q1","Q2","Q3","Q4","OT"]
QUARTER_TO_NUM = {"Q1":1,"Q2":2,"Q3":3,"Q4":4,"OT":5}

OUTCOMES_QB = [
    "Made 2","Missed 2","Made 3","Missed 3",
    "Foul (Made 1/2)","Foul (Made 2/2)","Foul (Missed Both)",
    "Turnover","Dead Ball","Timeout","Dead Ball Foul"
]
SC_OUTCOMES = ["Made 2","Missed 2","Made 3","Missed 3","Foul","Turnover","Reset/Other"]

def points_from_outcome(o: str) -> int:
    return 2 if o=="Made 2" else 3 if o=="Made 3" else 1 if o=="Foul (Made 1/2)" else 2 if o=="Foul (Made 2/2)" else 0

# ========= CHIP HELPERS =========
def chip_check_group(label, options, key, cols=4, default_selected=None):
    """Checkbox-chip grid (multi). Stores a set in st.session_state[key]. Returns sorted list."""
    st.markdown(f"**{label}**")
    if default_selected is None: default_selected = []
    st.session_state.setdefault(key, set(default_selected))
    selected = set(st.session_state[key])
    col_list = st.columns(cols)
    for i, opt in enumerate(options):
        with col_list[i % cols]:
            checked = st.checkbox(opt, value=(opt in selected), key=f"{key}__{opt}")
            if checked: selected.add(opt)
            else: selected.discard(opt)
    st.session_state[key] = selected
    return sorted(selected)

# ========= STATE =========
ss = st.session_state
ss.setdefault("plays_master", PLAY_NAMES.copy())
ss.setdefault("games", ["Default Game"])
ss.setdefault("game_meta", {})  # name -> {"quarter": "Q1", "opponent": "", "type": "Game"}
ss.setdefault("current_game", "Default Game")
ss.setdefault("game_data", {})  # name -> list of dict rows
ss.setdefault("roster", ["#1", "#2", "#3"])
ss.setdefault("game_clock_min", 12)
ss.setdefault("game_clock_sec", "00")
ss.setdefault("pending_action", None)
ss.setdefault("call_types", set(["Half Court"]))
ss.setdefault("second_chance", "No")
ss.setdefault("sc_outcomes", set())
ss.setdefault("credit_play", None)

# ========= CSS (unified pills + buttons, hides checkbox glyph) =========
st.markdown(
    """
<style>
:root {
  --chip-bg: #f6f7f9; --chip-fg: #111827; --chip-border: #cfd4dc;
  --chip-bg-active: #2563eb; --chip-fg-active: #ffffff; --chip-border-active: #1d4ed8; --chip-bg-hover: #eef2ff;
  --btn-bg: var(--chip-bg); --btn-fg: var(--chip-fg); --btn-border: var(--chip-border);
  --btn-bg-hover: var(--chip-bg-hover); --btn-bg-active: var(--chip-bg-active); --btn-fg-active: var(--chip-fg-active); --btn-border-active: var(--chip-border-active);
}
@media (prefers-color-scheme: dark) {
  :root {
    --chip-bg: #0f172a; --chip-fg: #e5e7eb; --chip-border: #334155;
    --chip-bg-active: #3b82f6; --chip-fg-active: #0b1220; --chip-border-active: #60a5fa; --chip-bg-hover: #1e293b;
    --btn-bg: var(--chip-bg); --btn-fg: var(--chip-fg); --btn-border: var(--chip-border);
    --btn-bg-hover: var(--chip-bg-hover); --btn-bg-active: var(--chip-bg-active); --btn-fg-active: var(--chip-fg-active); --btn-border-active: var(--chip-border-active);
  }
}
/* Chip base */
div[data-testid="stCheckbox"]{display:inline-block;margin:6px 8px 6px 0;}
div[data-testid="stCheckbox"] input[type="checkbox"]{position:absolute;opacity:0;pointer-events:none;width:0;height:0;}
div[data-testid="stCheckbox"] label{
  display:inline-flex;align-items:center;gap:.5rem;padding:8px 12px;border-radius:9999px;border:1px solid var(--chip-border);
  background:var(--chip-bg);color:var(--chip-fg);font-weight:600;cursor:pointer;user-select:none;
  transition:background .15s,color .15s,border-color .15s,box-shadow .15s,transform .02s;
}
/* hide any internal check glyphs Streamlit might render */
div[data-testid="stCheckbox"] svg{display:none !important;}
div[data-testid="stCheckbox"] label:hover{background:var(--chip-bg-hover);box-shadow:0 1px 2px rgba(0,0,0,.08);}
div[data-testid="stCheckbox"] label:active{transform:translateY(1px);}
div[data-testid="stCheckbox"]:has(input:checked) label{
  background:var(--chip-bg-active);color:var(--chip-fg-active);border-color:var(--chip-border-active);box-shadow:0 2px 6px rgba(37,99,235,.35);
}
/* Buttons like chips */
.stButton > button{
  border-radius:9999px !important;border:1px solid var(--btn-border) !important;background:var(--btn-bg) !important;color:var(--btn-fg) !important;
  padding:10px 14px !important;font-weight:700 !important;transition:background .15s,color .15s,border-color .15s,box-shadow .15s,transform .02s;
}
.stButton > button:hover{background:var(--btn-bg-hover) !important;box-shadow:0 1px 2px rgba(0,0,0,.08) !important;}
.stButton > button:active{transform:translateY(1px);}
/* primary-tinted buttons */
.stButton > button:has(span:contains("Confirm")), .stButton > button:has(span:contains("Add Entry")),
.stButton > button:has(span:contains("Made ")), .stButton > button:has(span:contains("Miss ")),
.stButton > button:has(span:contains("TO")), .stButton > button:has(span:contains("Timeout")), .stButton > button:has(span:contains("Dead Ball")), .stButton > button:has(span:contains("DB Foul")){
  background:var(--btn-bg-active) !important;color:var(--btn-fg-active) !important;border-color:var(--btn-border-active) !important;box-shadow:0 2px 6px rgba(37,99,235,.35) !important;
}
.quickbar-row .stButton > button{margin-bottom:6px;}
.stDataFrame{border-radius:10px;}
@media (max-width:480px){div[data-testid="stCheckbox"] label{padding:10px 14px;}.stButton > button{padding:12px 16px !important;}}
</style>
""",
    unsafe_allow_html=True
)

# ========= INIT SHEETS + HYDRATE =========
sheets_connected = init_sheets()
if sheets_connected:
    try:
        playbook_df = pd.DataFrame(sh.worksheet("Playbook").get_all_records())
        if not playbook_df.empty and "Play Name" in playbook_df:
            ss["plays_master"] = sorted(set(ss["plays_master"]) | set(playbook_df["Play Name"].dropna().tolist()))
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
ss["game_meta"].setdefault(ss["current_game"], {"quarter":"Q1","opponent":"","type":"Game"})

# ========= HEADER + LOGO + STATUS =========
c1, c2, c3 = st.columns([1,2,1])
with c2:
    _logo = logo_image_bytes()
    if _logo: st.image(_logo, use_container_width=True)
st.caption("✅ Connected to Google Sheets" if sheets_connected else "⚠️ Running locally (no Sheets sync)")
st.title("🏀 Play Call Tagging v7.1")

# ========= GAME MANAGER (Unified Create ↔ Current) =========
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
        ss["game_meta"].setdefault(ss["current_game"], {"quarter":"Q1","opponent":"","type":"Game"})

meta = ss["game_meta"].setdefault(ss["current_game"], {"quarter":"Q1","opponent":"","type":"Game"})

# Compact create row, hidden once a game is created this session
if "hide_create_row" not in ss: ss["hide_create_row"] = False
if not ss["hide_create_row"]:
    cg1, cg2, cg3, cg4 = st.columns([2,1.2,1.8,1])
    with cg1:
        new_name = st.text_input("Create New Game — Name")
    with cg2:
        new_type = st.selectbox("Type", ["Game","Scrimmage","Scout"], key="new_type")
    with cg3:
        new_opp = st.text_input("Opponent", key="new_opp")
    with cg4:
        if st.button("Create"):
            if new_name.strip():
                if new_name not in ss["games"]:
                    ss["games"].append(new_name)
                ss["game_meta"][new_name] = {"quarter":"Q1","opponent":new_opp,"type":new_type}
                ss["game_data"].setdefault(new_name, [])
                if sheets_connected:
                    sheets_add_game(new_name, new_type, new_opp)
                ss["current_game"] = new_name
                ss["hide_create_row"] = True
                st.success(f"Created game: {new_name}")
                st.rerun()
            else:
                st.warning("Enter a game name first.")

st.subheader(f"Current Game: {ss['current_game']}")
e1, e2, e3, e4 = st.columns([1,1,1,2])
with e1:
    meta["quarter"] = st.selectbox("Quarter", QUARTERS, index=QUARTERS.index(meta.get("quarter","Q1")))
with e2:
    meta["type"] = st.selectbox("Game Type", ["Game","Scrimmage","Scout"], index=["Game","Scrimmage","Scout"].index(meta.get("type","Game")))
with e3:
    meta["opponent"] = st.text_input("Opponent", value=meta.get("opponent",""))
with e4:
    with st.expander("Rename Game (copy-rename in Sheets)"):
        new_game_name = st.text_input("New Game Name", value=ss["current_game"])
        danger = st.checkbox("Also remove old sheet after copying (safe default: ON)", value=True)
        if st.button("Run Rename"):
            if new_game_name.strip() and new_game_name != ss["current_game"]:
                # Prepare current df
                df_current = pd.DataFrame(ss["game_data"].get(ss["current_game"], []))
                # Sheets copy-rename
                if sheets_connected:
                    try:
                        sheets_rename_game(ss["current_game"], new_game_name, meta.get("type","Game"), meta.get("opponent",""), df_current)
                    except Exception as e:
                        st.error(f"Sheets rename failed: {e}")
                # Local rename
                ss["game_data"][new_game_name] = ss["game_data"].pop(ss["current_game"], [])
                ss["game_meta"][new_game_name] = ss["game_meta"].pop(ss["current_game"])
                # Update list & selection
                if new_game_name not in ss["games"]:
                    ss["games"].append(new_game_name)
                if ss["current_game"] in ss["games"]:
                    ss["games"].remove(ss["current_game"])
                ss["current_game"] = new_game_name
                st.success(f"Renamed game to: {new_game_name}")
                st.rerun()
            else:
                st.warning("Enter a different new name.")

# ========= SIDEBAR — Playbook (add) =========
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

# ========= 1) GAME CLOCK — chips + nudges =========
st.markdown("**1) Game clock**")

def mmss_to_tuple(mmss: str):
    try:
        m, s = mmss.split(":"); return int(m), int(s)
    except Exception:
        return 12, 0

def tuple_to_mmss(m: int, s: int):
    s = max(0, min(59, s))
    m = max(0, min(12, m))
    return f"{m}:{s:02d}"

def add_seconds(m: int, s: int, delta: int):
    total = m*60 + s + delta
    total = max(0, min(12*60, total))
    return total//60, total%60

# Minute chips
mcols = st.columns(13)
for idx, m in enumerate(range(12, -1, -1)):
    with mcols[idx]:
        if st.button(f"{m}", key=f"m_{m}"):
            ss["game_clock_min"] = m

# Second chips
scols = st.columns(12)
for idx, s in enumerate(range(0, 60, 5)):
    with scols[idx]:
        if st.button(f"{s:02d}", key=f"s_{s}"):
            ss["game_clock_sec"] = f"{s:02d}"

# Nudge row
n1, n2, n3, n4, n5, n6 = st.columns(6)
with n1:
    if st.button("−10s"): 
        m, s = add_seconds(ss["game_clock_min"], int(ss["game_clock_sec"]), -10)
        ss["game_clock_min"], ss["game_clock_sec"] = m, f"{s:02d}"
with n2:
    if st.button("−5s"): 
        m, s = add_seconds(ss["game_clock_min"], int(ss["game_clock_sec"]), -5)
        ss["game_clock_min"], ss["game_clock_sec"] = m, f"{s:02d}"
with n3:
    if st.button("+5s"): 
        m, s = add_seconds(ss["game_clock_min"], int(ss["game_clock_sec"]), +5)
        ss["game_clock_min"], ss["game_clock_sec"] = m, f"{s:02d}"
with n4:
    if st.button("+10s"): 
        m, s = add_seconds(ss["game_clock_min"], int(ss["game_clock_sec"]), +10)
        ss["game_clock_min"], ss["game_clock_sec"] = m, f"{s:02d}"
with n5:
    if st.button(":30"):
        ss["game_clock_sec"] = "30"
with n6:
    if st.button(":00"):
        ss["game_clock_sec"] = "00"

game_clock = f"{ss['game_clock_min']}:{ss['game_clock_sec']}"

# ========= 2) PLAY NAMES + CREDIT PLAY =========
sel_plays = chip_check_group("2) Select Play Name(s)", ss["plays_master"], key="ms_plays", cols=4, default_selected=[])
sel_plays_sorted = sorted(sel_plays, key=str.lower)
if sel_plays_sorted:
    default_credit = sel_plays_sorted[0] if (ss.get("credit_play") not in sel_plays_sorted) else ss["credit_play"]
    ss["credit_play"] = st.selectbox("Credit Play (PPP attribution)", sel_plays_sorted, index=sel_plays_sorted.index(default_credit))

# ========= 3) CALL TYPE / CALLER / 2ND CHANCE =========
sel_call_types = chip_check_group("3) Call Type (multi)", CALL_TYPES_MASTER, key="ms_call_types", cols=4, default_selected=["Half Court"])
caller = st.radio("4) Who called it?", CALLERS, horizontal=True, index=0)
second_chance = st.radio("5) 2nd Chance?", ["No","Yes"], horizontal=True, index=0)
sel_sc_outcomes = []
if second_chance == "Yes":
    sel_sc_outcomes = chip_check_group("Second‑Chance Outcomes (multi)", SC_OUTCOMES, key="ms_sc_outcomes", cols=4, default_selected=[])

def join_pipe(items):
    if not items: return ""
    return " | ".join(items)

def build_row_from_ui(outcome_text: str):
    plays_str = join_pipe(sel_plays_sorted)
    call_types_str = join_pipe(sel_call_types or ["Half Court"])
    sc_str = join_pipe(sel_sc_outcomes) if second_chance == "Yes" else ""
    pts = points_from_outcome(outcome_text)
    return {
        "Timestamp": game_clock,
        "Plays": plays_str,
        "Credit Play": ss.get("credit_play") or (sel_plays_sorted[0] if sel_plays_sorted else ""),
        "Call Type": call_types_str,
        "Caller": caller,
        "Outcome": outcome_text,
        "Points": pts,
        "2nd Chance?": second_chance,
        "2nd Chance Outcome": sc_str,
        "Quarter": ss["game_meta"][ss["current_game"]].get("quarter","Q1"),
        "Opponent": ss["game_meta"][ss["current_game"]].get("opponent",""),
        "Game Type": ss["game_meta"][ss["current_game"]].get("type","Game"),
    }

def push_row(r: dict):
    ss["game_data"].setdefault(ss["current_game"], []).append(r)
    if sheets_connected:
        try:
            sheets_append_play(ss["current_game"], [
                r["Timestamp"], r["Plays"], r["Credit Play"], r["Call Type"], r["Caller"],
                r["Outcome"], r["Points"], r["2nd Chance?"], r["2nd Chance Outcome"],
                r["Quarter"], r["Opponent"], r["Game Type"]
            ])
        except Exception as e:
            st.error(f"Sheets append failed: {e}")

def auto_decrement_clock():
    m, s = add_seconds(ss["game_clock_min"], int(ss["game_clock_sec"]), -AUTO_DEC_SECONDS)
    ss["game_clock_min"], ss["game_clock_sec"] = m, f"{s:02d}"

# ========= QUICK BAR (Outcome-only) =========
st.markdown('<div class="quickbar-row">', unsafe_allow_html=True)
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
st.markdown('</div>', unsafe_allow_html=True)

if ss.get("pending_action"):
    with st.container(border=True):
        st.write(
            f"Pending: **{ss['pending_action']}** | Plays: **{', '.join(sel_plays_sorted) or '(none)'}** "
            f"| Credit: **{ss.get('credit_play') or '(pick one)'}** | Call Type(s): **{join_pipe(sel_call_types) or '(default Half Court)'}** "
            f"| 2nd Chance: **{second_chance}** {'| SC: '+join_pipe(sel_sc_outcomes) if (second_chance=='Yes' and sel_sc_outcomes) else ''} "
            f"| Clock: **{game_clock}** | Q: **{meta.get('quarter','Q1')}**"
        )
        c1, c2 = st.columns([1,1])
        with c1:
            if st.button("Confirm"):
                if not sel_plays_sorted:
                    st.warning("Select at least one play.")
                elif not ss.get("credit_play"):
                    st.warning("Pick a Credit Play for PPP attribution.")
                else:
                    row = build_row_from_ui(ss["pending_action"])
                    push_row(row)
                    # reset quick bits (keep call types sticky for speed)
                    ss["pending_action"] = None
                    ss["ms_plays"] = set()
                    auto_decrement_clock()
                    st.success("Possession logged.")
                    st.rerun()
        with c2:
            if st.button("Cancel"):
                ss["pending_action"] = None
                st.info("Quick action canceled.")

# ========= TABLE + EDIT/DELETE =========
df = pd.DataFrame(ss["game_data"].get(ss["current_game"], []))
st.subheader(f"Logged Plays — {ss['current_game']}")
if df.empty:
    st.info("No possessions yet.")
else:
    fcol = st.columns([2,1,1,1])
    with fcol[0]:
        q_filter = st.multiselect("Filter by Quarter", QUARTERS, default=QUARTERS)
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
        st.download_button("⬇️ Download CSV", data=csv, file_name=f"{ss['current_game'].replace(' ','_')}.csv", mime="text/csv", use_container_width=True)

# ========= LIVE DASHBOARD =========
st.divider()
st.subheader("📊 Live Dashboard")

# Auto-refresh controls
ar_col1, ar_col2, _ = st.columns([1,1,3])
with ar_col1:
    auto_refresh = st.toggle("Auto‑refresh", value=False)
with ar_col2:
    interval = st.selectbox("Interval (s)", [2,3,5,10], index=2, disabled=not auto_refresh)
if auto_refresh:
    st.autorefresh(interval=interval * 1000, key="live_refresh_key")

if df.empty:
    st.info("No data yet for visuals.")
else:
    vis = df.copy()
    vis["Count"] = 1
    outcome_map = {
        "Made 2":"Made 2","Missed 2":"Miss 2","Made 3":"Made 3","Missed 3":"Miss 3",
        "Foul (Made 1/2)":"Foul 1/2","Foul (Made 2/2)":"Foul 2/2","Foul (Missed Both)":"Foul 0/2",
        "Turnover":"TO","Dead Ball":"Dead","Timeout":"TOUT","Dead Ball Foul":"DB Foul"
    }
    vis["OutcomeShort"] = vis["Outcome"].map(outcome_map).fillna(vis["Outcome"])

    # Stacked outcomes by Call Type
    call_stack = (
        alt.Chart(vis)
        .mark_bar()
        .encode(
            x=alt.X("sum(Count):Q", title="Possessions"),
            y=alt.Y("Call Type:N", sort="-x", title="Call Type(s)"),
            color=alt.Color("OutcomeShort:N", title="Outcome"),
            tooltip=["Call Type","OutcomeShort","Count:Q"]
        )
        .properties(height=300, title="Outcomes by Call Type (stacked)")
    )

    # Cumulative PPP by possession order
    def mmss_to_seconds(s):
        try:
            m, sec = s.split(":"); return int(m)*60 + int(sec)
        except Exception:
            return 0
    orderer = vis.copy()
    orderer["ClockSec"] = orderer["Timestamp"].apply(mmss_to_seconds)
    orderer["Qnum"] = orderer["Quarter"].map(QUARTER_TO_NUM).fillna(99)
    orderer = orderer.sort_values(["Qnum","ClockSec"], ascending=[True,False]).reset_index(drop=True)
    orderer["CumPoss"] = range(1, len(orderer)+1)
    orderer["CumPts"] = orderer["Points"].cumsum()
    orderer["PPP"] = orderer["CumPts"] / orderer["CumPoss"]
    ppp_line = (
        alt.Chart(orderer)
        .mark_line(point=True)
        .encode(
            x=alt.X("CumPoss:Q", title="Possessions (game order)"),
            y=alt.Y("PPP:Q", title="Cumulative PPP"),
            tooltip=["CumPoss","PPP","Quarter","Timestamp","Plays","OutcomeShort"]
        )
        .properties(height=260, title="Cumulative PPP (live)")
    )

    # PPP Leaderboard (by Credit Play)
    cred = vis.copy()
    # attempts: 1 per row; credit goes only to 'Credit Play'
    grouped = cred.groupby("Credit Play", dropna=False).agg(
        Attempts=("Points","count"),
        Points=("Points","sum")
    ).reset_index().rename(columns={"Credit Play":"Play"})
    grouped["PPP"] = grouped["Points"] / grouped["Attempts"]
    grouped = grouped[grouped["Play"].fillna("") != ""]  # drop blank credit
    min_attempts = st.slider("Min attempts for leaderboard", 1, 10, 3)
    topN = st.slider("Top N rows", 5, 20, 10)
    board = grouped[grouped["Attempts"] >= min_attempts].sort_values(["PPP","Attempts"], ascending=[False,False]).head(topN)

    cA, cB = st.columns(2)
    with cA:
        st.altair_chart(call_stack, use_container_width=True)
        st.altair_chart(ppp_line, use_container_width=True)
    with cB:
        st.subheader("PPP Leaderboard (by Credit Play)")
        st.dataframe(board.reset_index(drop=True), use_container_width=True, height=360)

# ========= SHEETS — STATUS & POSTGAME =========
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
                        "TEST","Test Play | Pistol","Pistol","Half Court","Coach",
                        "Turnover",0,"No","", "Q1","Test Opp","Game"
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
                            r.get("Timestamp",""), r.get("Plays",""), r.get("Credit Play",""), r.get("Call Type",""), r.get("Caller",""),
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
