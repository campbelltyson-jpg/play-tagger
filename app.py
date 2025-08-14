# app.py — Play Tagger v8 (faster layout, +Add Play persistence, Frequency%/Success%/PPP per Play, sticky quick bar)
import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

# ========= CONFIG =========
st.set_page_config(page_title="Play Tagger v8", layout="wide")
AUTO_DEC_SECONDS = 8  # auto-decrement after Confirm

def logo_image_bytes():
    try:
        with open("Transition Defense.png", "rb") as f:
            return f.read()
    except Exception:
        return None

# --- Query param helpers ---
def _get_qp():
    try:
        return dict(st.query_params)
    except Exception:
        return st.experimental_get_query_params()

def _set_qp(**kwargs):
    try:
        st.query_params.update(kwargs)
    except Exception:
        st.experimental_set_query_params(**kwargs)

# ========= GOOGLE SHEETS (optional) =========
USE_SHEETS = False
gc = None
sh = None
_sheets_error = None

GAME_HEADERS = [
    "Timestamp","Plays","Credit Play","Call Type","Caller","Outcome","Points",
    "2nd Chance?","2nd Chance Outcome","Quarter","Opponent","Game Type","Success"
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
        ws.update("A1:M1", [GAME_HEADERS])
    else:
        ws = sh.worksheet(ws_title)
        header = ws.row_values(1)
        if header != GAME_HEADERS:
            ws.update("A1:M1", [GAME_HEADERS])
    return ws

def sheets_append_play(game_name: str, row: list):
    ws = get_or_create_game_ws(game_name)
    ws.append_row(row, value_input_option="USER_ENTERED")

def sheets_overwrite_game(game_name: str, df: pd.DataFrame):
    ws = get_or_create_game_ws(game_name)
    ws.resize(rows=1)
    if df.empty:
        ws.update("A1:M1", [GAME_HEADERS]); return
    for col in GAME_HEADERS:
        if col not in df.columns:
            df[col] = ""
    df = df[GAME_HEADERS].fillna("")
    values = [GAME_HEADERS] + df.values.tolist()
    ws.update(f"A1:M{len(values)}", values)

def sheets_add_game(game_name: str, game_type: str, opponent: str):
    ws = sh.worksheet("Games")
    ws.append_row([game_name, game_type, opponent, datetime.now().isoformat(timespec="seconds")],
                  value_input_option="USER_ENTERED")
    get_or_create_game_ws(game_name)

def sheets_rename_game(old_name: str, new_name: str, new_type: str, new_opp: str, df_game: pd.DataFrame):
    sheets_overwrite_game(new_name, df_game)
    games_ws = sh.worksheet("Games")
    rows = games_ws.get_all_values()
    updated = False
    for i, row in enumerate(rows[1:], start=2):
        if row and row[0] == old_name:
            games_ws.update(f"A{i}:C{i}", [[new_name, new_type, new_opp]])
            updated = True
            break
    if not updated:
        games_ws.append_row([new_name, new_type, new_opp, datetime.now().isoformat(timespec="seconds")],
                            value_input_option="USER_ENTERED")
    old_title = game_ws_title(old_name)
    try:
        sh.del_worksheet(sh.worksheet(old_title))
    except Exception:
        pass

# ---- Cached single-game reader (re-hydrate) ----
@st.cache_data(ttl=5, show_spinner=False)
def read_game_from_sheets(game_name: str, _bust: int = 0) -> pd.DataFrame:
    if not sheets_connected:
        return pd.DataFrame()
    ws = get_or_create_game_ws(game_name)
    rows = ws.get_all_records()
    return pd.DataFrame(rows)

# ========= DATA / CONSTANTS =========
PLAY_NAMES = [
    "Flow","Zoom","Shake","Broken Play","Random","Transition","Delay","Pistol",
    "Chin Quick - Spain","Flex - Rifle","Pitch","ATO","Open Sets","Elbow","Punch",
    "Spain","Roll","Step","Iverson","Flare - Quick","Line 1","Rub","Slice","Rifle",
    "Triple Staggers","High","X","Flat 14","College","Mustang"
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

def is_success(outcome: str) -> bool:
    return outcome in ["Made 2","Made 3","Foul (Made 1/2)","Foul (Made 2/2)"]

# ========= CHIP HELPERS =========
def chip_check_group(label, options, key, cols=4, default_selected=None, small=False):
    st.markdown(f"**{label}**")
    if default_selected is None: default_selected = []
    st.session_state.setdefault(key, set(default_selected))
    selected = set(st.session_state[key])
    col_list = st.columns(cols)
    pad = "6px 10px" if small else "8px 12px"
    st.markdown(f"<style>div[data-key^='{key}__'] label{{padding:{pad} !important;}}</style>", unsafe_allow_html=True)
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
ss.setdefault("game_meta", {})  # name -> {"quarter": "Q1","opponent":"","type":"Game"}
ss.setdefault("current_game", "Default Game")
ss.setdefault("game_data", {})  # name -> list of dict rows
ss.setdefault("roster", ["#1","#2","#3"])
ss.setdefault("game_clock_min", 12)
ss.setdefault("game_clock_sec", "00")
ss.setdefault("pending_action", None)
ss.setdefault("call_types", set(["Half Court"]))
ss.setdefault("second_chance", "No")
ss.setdefault("sc_outcomes", set())
ss.setdefault("credit_play", None)
ss.setdefault("sheet_rev", 0)
ss.setdefault("hide_create_row", False)
ss.setdefault("compact_mode", True)  # NEW default compact

# ========= CSS (gray→red chips, sticky quick bar, compact mode) =========
st.markdown(
    """
<style>
/* ===== Gray default / Red active ===== */
:root{
  --chip-gray:#e5e7eb; --chip-gray-fg:#111827; --chip-gray-border:#cfd4dc; --chip-gray-hover:#f3f4f6;
  --chip-red:#ef4444; --chip-red-fg:#ffffff; --chip-red-border:#dc2626;
  --btn-bg:var(--chip-gray); --btn-fg:var(--chip-gray-fg); --btn-border:var(--chip-gray-border);
  --btn-bg-hover:var(--chip-gray-hover); --btn-bg-active:var(--chip-red); --btn-fg-active:var(--chip-red-fg); --btn-border-active:var(--chip-red-border);
}
@media (prefers-color-scheme: dark){
  :root{ --chip-gray:#1f2937; --chip-gray-fg:#e5e7eb; --chip-gray-border:#374151; --chip-gray-hover:#111827; }
}
/* Chips */
div[data-testid="stCheckbox"]{display:inline-block;margin:4px 6px 4px 0;}
div[data-testid="stCheckbox"] input[type="checkbox"]{position:absolute;opacity:0;pointer-events:none;width:0;height:0;}
div[data-testid="stCheckbox"] label{
  display:inline-flex;align-items:center;gap:.5rem;padding:8px 12px;border-radius:9999px;border:1px solid var(--chip-gray-border);
  background:var(--chip-gray);color:var(--chip-gray-fg);font-weight:700;cursor:pointer;user-select:none;transition:background .15s,color .15s,border-color .15s,box-shadow .15s,transform .02s;
}
div[data-testid="stCheckbox"] svg{display:none !important;}
div[data-testid="stCheckbox"] label:hover{background:var(--chip-gray-hover);}
div[data-testid="stCheckbox"] label:active{transform:translateY(1px);}
div[data-testid="stCheckbox"]:has(input:checked) label{ background:var(--chip-red);color:var(--chip-red-fg);border-color:var(--chip-red-border);box-shadow:0 2px 6px rgba(239,68,68,.35); }

/* Buttons styled as chips */
.stButton > button{
  border-radius:9999px !important;border:1px solid var(--btn-border) !important;background:var(--btn-bg) !important;color:var(--btn-fg) !important;
  padding:8px 12px !important;font-weight:800 !important;transition:background .15s,color .15s,border-color .15s,box-shadow .15s,transform .02s; margin-bottom:6px;
}
.stButton > button:hover{background:var(--btn-bg-hover) !important;}
.stButton > button:active{transform:translateY(1px);}
.stButton > button.confirm-primary{ background:var(--btn-bg-active) !important;color:var(--btn-fg-active) !important;border-color:var(--btn-border-active) !important; box-shadow:0 2px 6px rgba(239,68,68,.35) !important; }

/* Sticky Quick Bar (top) */
.quickbar-sticky{ position:sticky; top:0; z-index:50; padding:8px 6px; background:rgba(255,255,255,0.85); backdrop-filter: blur(6px); border-bottom:1px solid rgba(0,0,0,.06);}
@media (prefers-color-scheme: dark){ .quickbar-sticky{ background:rgba(17,24,39,0.85); border-bottom:1px solid rgba(255,255,255,.06);} }

/* Compact mode spacing */
.compact .block-container{ padding-top:10px !important; }
</style>
""",
    unsafe_allow_html=True
)
if ss["compact_mode"]:
    st.markdown('<style>.block-container{padding-top:10px !important; padding-bottom:0 !important;}</style>', unsafe_allow_html=True)

# ========= INIT SHEETS + HYDRATE LISTS =========
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

# ========= HEADER =========
hdr1, hdr2, hdr3 = st.columns([1,3,2])
with hdr2:
    _logo = logo_image_bytes()
    if _logo: st.image(_logo, use_column_width=True)
st.caption("✅ Google Sheets Live Sync" if sheets_connected else "⚠️ Local mode — use Postgame Upload")
st.title("🏀 Play Call Tagger — v8")

# ========= URL -> current game =========
ss["game_data"].setdefault(ss["current_game"], [])
ss["game_meta"].setdefault(ss["current_game"], {"quarter":"Q1","opponent":"","type":"Game"})
_qp = _get_qp()
qp_game = None
if "game" in _qp:
    v = _qp["game"]; qp_game = v[0] if isinstance(v, list) else v
if qp_game and qp_game in ss["games"]:
    ss["current_game"] = qp_game
else:
    if ss["current_game"] not in ss["games"]:
        ss["current_game"] = ss["games"][0]
_set_qp(game=ss["current_game"])

# ========= GAME MANAGER (row) =========
g1, g2, g3, g4, g5 = st.columns([2,1.2,1.8,1,1])
with g1:
    current_game = st.selectbox("Current Game", options=ss["games"], index=ss["games"].index(ss["current_game"]) if ss["current_game"] in ss["games"] else 0)
    if current_game != ss["current_game"]:
        ss["current_game"] = current_game
        _set_qp(game=ss["current_game"])
        if sheets_connected:
            df_h = read_game_from_sheets(ss["current_game"], ss["sheet_rev"])
            ss["game_data"][ss["current_game"]] = df_h.to_dict("records") if not df_h.empty else []
        ss["game_meta"].setdefault(ss["current_game"], {"quarter":"Q1","opponent":"","type":"Game"})
with g2:
    meta = ss["game_meta"].setdefault(ss["current_game"], {"quarter":"Q1","opponent":"","type":"Game"})
    meta["quarter"] = st.selectbox("Quarter", QUARTERS, index=QUARTERS.index(meta.get("quarter","Q1")))
with g3:
    meta["opponent"] = st.text_input("Opponent", value=meta.get("opponent",""))
with g4:
    meta["type"] = st.selectbox("Game Type", ["Game","Scrimmage","Scout"], index=["Game","Scrimmage","Scout"].index(meta.get("type","Game")))
with g5:
    ss["compact_mode"] = st.toggle("Compact", value=ss["compact_mode"], help="Smaller padding & chips")

# Create row (compact, disappears after creation)
if not ss["hide_create_row"]:
    cg1, cg2, cg3, cg4 = st.columns([2,1.2,1.8,0.8])
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
                _set_qp(game=ss["current_game"])
                if sheets_connected:
                    df_h = read_game_from_sheets(ss["current_game"], ss["sheet_rev"])
                    ss["game_data"][ss["current_game"]] = df_h.to_dict("records") if not df_h.empty else []
                st.success(f"Created game: {new_name}")
                st.rerun()
            else:
                st.warning("Enter a game name first.")

# ========= LAYOUT: 3‑panel tagging (less scrolling) =========
L, C, R = st.columns([1.2, 2.0, 1.5])

# ----- LEFT: Clock + Caller + 2nd Chance -----
with L:
    st.subheader("⏱ Clock")
    def add_seconds(m: int, s: int, delta: int):
        total = m*60 + s + delta; total = max(0, min(12*60, total)); return total//60, total%60
    # minute chips
    mcols = st.columns(13)
    for idx, m in enumerate(range(12, -1, -1)):
        with mcols[idx]:
            if st.button(f"{m}", key=f"m_{m}"): ss["game_clock_min"] = m
    # second chips
    scols = st.columns(12)
    for idx, s in enumerate(range(0, 60, 5)):
        with scols[idx]:
            if st.button(f"{s:02d}", key=f"s_{s}"): ss["game_clock_sec"] = f"{s:02d}"
    # nudges
    n1, n2, n3, n4, n5, n6 = st.columns(6)
    with n1:
        if st.button("−10s"): m, s = add_seconds(ss["game_clock_min"], int(ss["game_clock_sec"]), -10); ss["game_clock_min"], ss["game_clock_sec"] = m, f"{s:02d}"
    with n2:
        if st.button("−5s"): m, s = add_seconds(ss["game_clock_min"], int(ss["game_clock_sec"]), -5); ss["game_clock_min"], ss["game_clock_sec"] = m, f"{s:02d}"
    with n3:
        if st.button("+5s"): m, s = add_seconds(ss["game_clock_min"], int(ss["game_clock_sec"]), +5); ss["game_clock_min"], ss["game_clock_sec"] = m, f"{s:02d}"
    with n4:
        if st.button("+10s"): m, s = add_seconds(ss["game_clock_min"], int(ss["game_clock_sec"]), +10); ss["game_clock_min"], ss["game_clock_sec"] = m, f"{s:02d}"
    with n5:
        if st.button(":30"): ss["game_clock_sec"] = "30"
    with n6:
        if st.button(":00"): ss["game_clock_sec"] = "00"

    game_clock = f"{ss['game_clock_min']}:{ss['game_clock_sec']}"
    # highlight current minute/second buttons
    st.markdown(f"""
    <style>
    .stButton > button:has(span:contains("{ss['game_clock_min']}")) {{
      background: var(--btn-bg-active) !important; color: var(--btn-fg-active) !important; border-color: var(--btn-border-active) !important;
    }}
    .stButton > button:has(span:contains("{int(ss['game_clock_sec']):02d}")) {{
      background: var(--btn-bg-active) !important; color: var(--btn-fg-active) !important; border-color: var(--btn-border-active) !important;
    }}
    </style>
    """, unsafe_allow_html=True)

    st.subheader("👤 Caller")
    caller = st.radio("Who called it?", ["Coach","Player"], horizontal=True, index=0)

    st.subheader("🔁 2nd Chance")
    second_chance = st.radio("2nd Chance?", ["No","Yes"], horizontal=True, index=0)
    sel_sc_outcomes = []
    if second_chance == "Yes":
        sel_sc_outcomes = chip_check_group("Second‑Chance Outcomes", ["Made 2","Missed 2","Made 3","Missed 3","Foul","Turnover","Reset/Other"],
                                           key="ms_sc_outcomes", cols=3, small=True)

# ----- CENTER: Plays (with +Add) -----
with C:
    st.subheader("📖 Plays")
    # compact chips
    sel_plays = chip_check_group("Select Play Name(s)", ss["plays_master"], key="ms_plays", cols=4, small=True)
    sel_plays_sorted = sorted(sel_plays, key=str.lower)

    # Inline +Add Play popover (falls back to expander if not available)
    try:
        with st.popover("➕ Add Play"):
            np = st.text_input("Play Name")
            if st.button("Add"):
                if np.strip():
                    if np not in ss["plays_master"]:
                        ss["plays_master"].append(np); ss["plays_master"].sort()
                        if sheets_connected:
                            sh.worksheet("Playbook").append_row(["", np, ""], value_input_option="USER_ENTERED")
                    st.success(f"Added play: {np}"); st.rerun()
                else:
                    st.warning("Enter a play name.")
    except Exception:
        with st.expander("➕ Add Play"):
            np = st.text_input("Play Name")
            if st.button("Add"):
                if np.strip():
                    if np not in ss["plays_master"]:
                        ss["plays_master"].append(np); ss["plays_master"].sort()
                        if sheets_connected:
                            sh.worksheet("Playbook").append_row(["", np, ""], value_input_option="USER_ENTERED")
                    st.success(f"Added play: {np}"); st.rerun()
                else:
                    st.warning("Enter a play name.")

    if sel_plays_sorted:
        default_credit = sel_plays_sorted[0] if (ss.get("credit_play") not in sel_plays_sorted) else ss["credit_play"]
        ss["credit_play"] = st.selectbox("Credit Play (PPP attribution)", sel_plays_sorted, index=sel_plays_sorted.index(default_credit))

# ----- RIGHT: Call Types + Quick Bar (sticky) -----
with R:
    st.subheader("🗂 Call Types")
    sel_call_types = chip_check_group("Select Call Type(s)", CALL_TYPES_MASTER, key="ms_call_types", cols=3, small=True)
    if not sel_call_types:
        sel_call_types = ["Half Court"]

    # STICKY QUICK BAR
    st.markdown('<div class="quickbar-sticky">', unsafe_allow_html=True)
    qb1, qb2, qb3 = st.columns(3)
    with qb1:
        if st.button("Made 2"): ss["pending_action"] = "Made 2"
        if st.button("Miss 2"): ss["pending_action"] = "Missed 2"
        if st.button("TO"): ss["pending_action"] = "Turnover"
    with qb2:
        if st.button("Made 3"): ss["pending_action"] = "Made 3"
        if st.button("Miss 3"): ss["pending_action"] = "Missed 3"
        if st.button("Timeout"): ss["pending_action"] = "Timeout"
    with qb3:
        if st.button("Foul 1/2"): ss["pending_action"] = "Foul (Made 1/2)"
        if st.button("Foul 2/2"): ss["pending_action"] = "Foul (Made 2/2)"
        if st.button("Dead Ball"): ss["pending_action"] = "Dead Ball"
        if st.button("DB Foul"): ss["pending_action"] = "Dead Ball Foul"
    st.markdown('</div>', unsafe_allow_html=True)

# ===== Build & Push Row =====
def join_pipe(items): return " | ".join(items) if items else ""

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
        "Success": "Yes" if is_success(outcome_text) else "No",
    }

def push_row(r: dict):
    ss["game_data"].setdefault(ss["current_game"], []).append(r)
    if sheets_connected:
        try:
            sheets_append_play(ss["current_game"], [
                r["Timestamp"], r["Plays"], r["Credit Play"], r["Call Type"], r["Caller"],
                r["Outcome"], r["Points"], r["2nd Chance?"], r["2nd Chance Outcome"],
                r["Quarter"], r["Opponent"], r["Game Type"], r["Success"]
            ])
            ss["sheet_rev"] += 1
            read_game_from_sheets.clear()
            df_h = read_game_from_sheets(ss["current_game"], ss["sheet_rev"])
            ss["game_data"][ss["current_game"]] = df_h.to_dict("records") if not df_h.empty else []
        except Exception as e:
            st.error(f"Sheets append failed: {e}")

def auto_decrement_clock():
    m = ss["game_clock_min"]; s = int(ss["game_clock_sec"])
    total = max(0, m*60 + s - AUTO_DEC_SECONDS); ss["game_clock_min"], ss["game_clock_sec"] = total//60, f"{total%60:02d}"

# Pending banner + Confirm
if ss.get("pending_action"):
    with st.container(border=True):
        st.write(
            f"Pending: **{ss['pending_action']}** | Clock **{game_clock}** | Q **{meta.get('quarter','Q1')}** "
            f"| Plays: **{', '.join(sel_plays_sorted) or '(none)'}** → Credit **{ss.get('credit_play') or '(pick)'}** "
            f"| Call Type(s): **{join_pipe(sel_call_types)}** | 2nd: **{second_chance}**"
            + (f" (**{join_pipe(sel_sc_outcomes)}**)" if (second_chance=='Yes' and sel_sc_outcomes) else "")
        )
        c1, c2 = st.columns([1,1])
        with c1:
            if st.button("Confirm", key="confirm_btn"):
                if not sel_plays_sorted:
                    st.warning("Select at least one play.")
                elif not ss.get("credit_play"):
                    st.warning("Pick a Credit Play for PPP attribution.")
                else:
                    row = build_row_from_ui(ss["pending_action"]); push_row(row)
                    ss["pending_action"] = None; ss["ms_plays"] = set(); auto_decrement_clock()
                    st.success("Possession logged."); st.rerun()
        with c2:
            if st.button("Cancel", key="cancel_btn"):
                ss["pending_action"] = None; st.info("Quick action canceled.")

# ========= Ensure hydration =========
if sheets_connected and not ss["game_data"].get(ss["current_game"]):
    df_h = read_game_from_sheets(ss["current_game"], ss["sheet_rev"])
    if not df_h.empty: ss["game_data"][ss["current_game"]] = df_h.to_dict("records")

# ========= TABLE (edit/delete/export) =========
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
                ss["sheet_rev"] += 1; read_game_from_sheets.clear()
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
                    ss["sheet_rev"] += 1; read_game_from_sheets.clear()
                st.success(f"Deleted {len(to_drop)} row(s).")
    with cexport:
        csv = df.to_csv(index=False).encode()
        st.download_button("⬇️ Download CSV", data=csv, file_name=f"{ss['current_game'].replace(' ','_')}.csv", mime="text/csv", use_container_width=True)

# ========= LIVE DASHBOARD (Frequency %, Success %, PPP) =========
st.divider()
st.subheader("📊 Live Dashboard")

if df.empty:
    st.info("No data yet for visuals.")
else:
    vis = df.copy()
    vis = vis[vis["Credit Play"].notna() & (vis["Credit Play"] != "")]
    if vis.empty:
        st.info("No credited plays yet.")
    else:
        # per-play aggregates using Credit Play
        grp = vis.groupby("Credit Play", dropna=False).agg(
            Attempts=("Points","count"),
            Points=("Points","sum"),
            Successes=("Success", lambda s: (s=="Yes").sum())
        ).reset_index().rename(columns={"Credit Play":"Play"})
        total_poss = grp["Attempts"].sum() if len(grp)>0 else 1
        grp["PPP"] = grp["Points"] / grp["Attempts"]
        grp["Freq%"] = 100.0 * grp["Attempts"] / total_poss
        grp["Success%"] = 100.0 * grp["Successes"] / grp["Attempts"]
        grp = grp.sort_values(["PPP","Attempts"], ascending=[False,False])

        # controls
        cA, cB, cC = st.columns([1,1,1])
        with cA: min_attempts = st.slider("Min Attempts", 1, 15, 3)
        with cB: topN = st.slider("Top N", 5, 20, 10)
        with cC: show_table = st.toggle("Show Table", value=True)

        board = grp[grp["Attempts"] >= min_attempts].head(topN)

        # Chart: bar by PPP with labels of Freq% and Success%
        chart_ppp = (
            alt.Chart(board)
            .mark_bar()
            .encode(
                x=alt.X("PPP:Q"),
                y=alt.Y("Play:N", sort="-x"),
                tooltip=["Play","Attempts","PPP","Freq%","Success%"]
            )
            .properties(height=320, title="PPP by Play (filtered)")
        )
        st.altair_chart(chart_ppp, use_container_width=True)

        # Secondary chart: Frequency % (stacked not needed—single series)
        chart_freq = (
            alt.Chart(board)
            .mark_bar()
            .encode(
                x=alt.X("Freq%:Q", title="Frequency % of All Possessions"),
                y=alt.Y("Play:N", sort="-x"),
                tooltip=["Play","Freq%","Attempts"]
            )
            .properties(height=280, title="Frequency % by Play")
        )
        st.altair_chart(chart_freq, use_container_width=True)

        # Success % table (optional)
        if show_table:
            st.subheader("Per‑Play Metrics")
            tbl = board[["Play","Attempts","Points","PPP","Freq%","Success%"]].reset_index(drop=True)
            st.dataframe(tbl, use_container_width=True, height=360)

# ========= SIDEBAR: Playbook Manager (persist forever) =========
with st.sidebar:
    st.header("Playbook Manager")
    # Quick add (dup to center popover)
    np2 = st.text_input("New Play")
    if st.button("➕ Add Play"):
        if np2.strip():
            if np2 not in ss["plays_master"]:
                ss["plays_master"].append(np2); ss["plays_master"].sort()
                if sheets_connected:
                    sh.worksheet("Playbook").append_row(["", np2, ""], value_input_option="USER_ENTERED")
            st.success(f"Added play: {np2}"); st.experimental_rerun()
        else:
            st.warning("Enter a play name.")
    # Editable list with delete
    if st.checkbox("Edit/Delete Plays"):
        pb_df = pd.DataFrame({"Play Name": ss["plays_master"]})
        ed = st.data_editor(pb_df, hide_index=True, use_container_width=True, height=240)
        if st.button("💾 Save Playbook"):
            names = [n for n in ed["Play Name"].dropna().astype(str).str.strip().tolist() if n]
            ss["plays_master"] = sorted(set(names))
            if sheets_connected:
                ws = sh.worksheet("Playbook")
                ws.clear(); ws.update("A1:C1", [["Code","Play Name","System"]])
                if ss["plays_master"]:
                    ws.update(f"B2:B{len(ss['plays_master'])+1}", [[n] for n in ss["plays_master"]])
            st.success("Playbook saved.")
    st.divider()
    with st.expander("Rename Game (copy-rename in Sheets)"):
        new_game_name = st.text_input("New Game Name", value=ss["current_game"])
        if st.button("Run Rename"):
            if new_game_name.strip() and new_game_name != ss["current_game"]:
                df_current = pd.DataFrame(ss["game_data"].get(ss["current_game"], []))
                if sheets_connected:
                    try:
                        sheets_rename_game(ss["current_game"], new_game_name, ss["game_meta"][ss["current_game"]].get("type","Game"), ss["game_meta"][ss["current_game"]].get("opponent",""), df_current)
                    except Exception as e:
                        st.error(f"Sheets rename failed: {e}")
                ss["game_data"][new_game_name] = ss["game_data"].pop(ss["current_game"], [])
                ss["game_meta"][new_game_name] = ss["game_meta"].pop(ss["current_game"])
                if new_game_name not in ss["games"]:
                    ss["games"].append(new_game_name)
                if ss["current_game"] in ss["games"]:
                    ss["games"].remove(ss["current_game"])
                ss["current_game"] = new_game_name
                _set_qp(game=ss["current_game"])
                st.success(f"Renamed game to: {new_game_name}")
                st.rerun()

# ========= SHEETS — Status & Postgame =========
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
                        "Turnover",0,"No","", "Q1","Test Opp","Game","No"
                    ])
                    ss["sheet_rev"] += 1; read_game_from_sheets.clear()
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
                            r.get("Quarter",""), r.get("Opponent",""), r.get("Game Type",""), r.get("Success","")
                        ])
                ss["sheet_rev"] += 1; read_game_from_sheets.clear()
                st.success(f"Uploaded {len(df_up)} rows into '{target_game}'.")
            except Exception as e:
                st.error(f"Upload failed: {e}")
    else:
        st.warning("⚠️ Not connected to Google Sheets.")
        if _sheets_error:
            st.code(_sheets_error, language="text")
        st.caption("Tip: Add SHEET_ID and gcp_service_account JSON in Streamlit → Settings → Secrets, then redeploy.")