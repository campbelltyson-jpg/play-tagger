# app.py — Play Tagger v8.0.3
# Fixes:
# - Chip unselected font forced to black
# - Stronger persistence: always rehydrate from Sheets, keep ?game= in URL, fallback to latest game
# - Smaller iPad-friendly clock chips (scoped)
# - Everything else from v8.0.2 retained

import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

# ========= CONFIG =========
st.set_page_config(page_title="Play Tagger v8.0.3", layout="wide")
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
            sh.add_worksheet("Playbook", rows=2000, cols=3)
            sh.worksheet("Playbook").update("A1:C1", [["Code","Play Name","System"]])
        if "Games" not in ws_names:
            sh.add_worksheet("Games", rows=3000, cols=4)
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

@st.cache_data(ttl=5, show_spinner=False)
def list_games_df() -> pd.DataFrame:
    if not sheets_connected:
        return pd.DataFrame()
    try:
        return pd.DataFrame(sh.worksheet("Games").get_all_records())
    except Exception:
        return pd.DataFrame()

# ========= DATA / CONSTANTS =========
CALL_TYPES_MASTER = ["Early Offense","Half Court","BLOB","SLOB","Zone"]
CALLERS = ["Coach","Player"]
QUARTERS = ["Q1","Q2","Q3","Q4","OT"]
QUARTER_TO_NUM = {"Q1":1,"Q2":2,"Q3":3,"Q4":4,"OT":5}

SC_OUTCOMES = ["Made 2","Missed 2","Made 3","Missed 3","Foul","Turnover","Reset/Other"]

def points_from_outcome(o: str) -> int:
    return 2 if o=="Made 2" else 3 if o=="Made 3" else 1 if o=="Foul (Made 1/2)" else 2 if o=="Foul (Made 2/2)" else 0
def is_success(outcome: str) -> bool:
    return outcome in ["Made 2","Made 3","Foul (Made 1/2)","Foul (Made 2/2)"]

# ---- Your Play Categories ----
USER_PLAY_CATEGORIES = {
    "2 Man Game": [
        "7","Shake","Rub","Roll","Flat","Pitch","15 Step","14 Step","51 Step"
    ],
    "3 Man Game": [
        "77","Delay","Pistol","Away","Slice","Elbow","Stack","Gets"
    ],
    "Pace & Space": [
        "Transition","Flow","Pistol","Zoom","Random","Broken Play","Punch"
    ],
    "Specials": [
        "Open Sets","ATO","College","Mustang","1","Zip Quick","High","X"
    ],
}
UNCATEGORIZED = "Uncategorized"

# ========= CHIP HELPERS =========
def chip_check_group(label, options, key, cols=4, default_selected=None, small=False):
    if label:
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
# Build master list from categories
MASTER_PLAYS = sorted({p for lst in USER_PLAY_CATEGORIES.values() for p in lst})
ss.setdefault("plays_master", MASTER_PLAYS.copy())
ss.setdefault("play_categories", USER_PLAY_CATEGORIES.copy())

ss.setdefault("games", ["Default Game"])
ss.setdefault("game_meta", {})  # name -> {"quarter": "Q1","opponent":"","type":"Game"}
ss.setdefault("current_game", "Default Game")
ss.setdefault("game_data", {})  # name -> list of dict rows
ss.setdefault("roster", ["#1","#2","#3"])
ss.setdefault("game_clock_min", 12)
ss.setdefault("game_clock_sec", "00")
ss.setdefault("pending_action", None)
ss.setdefault("second_chance", "No")
ss.setdefault("sc_outcomes", set())
ss.setdefault("credit_play", None)
ss.setdefault("sheet_rev", 0)
ss.setdefault("hide_create_row", False)
ss.setdefault("compact_mode", True)

# ========= CSS (high-contrast chips; sticky bars; compact; iPad clock) =========
st.markdown(
    """
<style>
:root{
  --chip-gray:#e5e7eb; --chip-gray-fg:#111111;  /* forced black for legibility */
  --chip-gray-border:#cfd4dc; --chip-gray-hover:#f3f4f6;
  --chip-red:#ef4444; --chip-red-fg:#ffffff; --chip-red-border:#dc2626;
  --btn-bg:var(--chip-gray); --btn-fg:var(--chip-gray-fg); --btn-border:var(--chip-gray-border);
  --btn-bg-hover:var(--chip-gray-hover); --btn-bg-active:var(--chip-red); --btn-fg-active:var(--chip-red-fg); --btn-border-active:var(--chip-red-border);
}
@media (prefers-color-scheme: dark){
  :root{
    --chip-gray:#1f2937; --chip-gray-fg:#111111; /* still force black per request */
    --chip-gray-border:#374151; --chip-gray-hover:#111827;
  }
}
/* Checkbox chips */
div[data-testid="stCheckbox"]{display:inline-block;margin:4px 6px 4px 0;}
div[data-testid="stCheckbox"] input[type="checkbox"]{position:absolute;opacity:0;pointer-events:none;width:0;height:0;}
div[data-testid="stCheckbox"] label{
  display:inline-flex;align-items:center;gap:.5rem;padding:8px 12px;border-radius:9999px;border:1px solid var(--chip-gray-border);
  background:var(--chip-gray);color:#111111 !important;font-weight:700;cursor:pointer;user-select:none;
  transition:background .15s,color .15s,border-color .15s,box-shadow .15s,transform .02s;
}
div[data-testid="stCheckbox"] svg{display:none !important;}
div[data-testid="stCheckbox"] label:hover{background:var(--chip-gray-hover);}
div[data-testid="stCheckbox"] label:active{transform:translateY(1px);}
div[data-testid="stCheckbox"]:has(input:checked) label{
  background:var(--chip-red);color:var(--chip-red-fg) !important;border-color:var(--chip-red-border);box-shadow:0 2px 6px rgba(239,68,68,.35);
}
/* Buttons as chips (global default) */
.stButton > button{
  border-radius:9999px !important;border:1px solid var(--btn-border) !important;background:var(--btn-bg) !important;color:var(--btn-fg) !important;
  padding:8px 12px !important;font-weight:800 !important;transition:background .15s,color .15s,border-color .15s,box-shadow .15s,transform .02s;margin-bottom:6px;
}
.stButton > button:hover{background:var(--btn-bg-hover) !important;}
.stButton > button:active{transform:translateY(1px);}
.stButton > button.confirm-primary{
  background:var(--btn-bg-active) !important;color:var(--btn-fg-active) !important;border-color:var(--btn-border-active) !important;box-shadow:0 2px 6px rgba(239,68,68,.35) !important;
}
/* Sticky bars */
.top-sticky{position:sticky; top:0; z-index:60; padding:8px 6px; background:rgba(255,255,255,0.90); backdrop-filter: blur(6px); border-bottom:1px solid rgba(0,0,0,.06); }
@media (prefers-color-scheme: dark){ .top-sticky{ background:rgba(17,24,39,0.90); border-bottom:1px solid rgba(255,255,255,.06);} }
.bottom-sticky{position:sticky; bottom:0; z-index:60; padding:8px 6px; background:rgba(255,255,255,0.92); backdrop-filter: blur(6px); border-top:1px solid rgba(0,0,0,.06);}
@media (prefers-color-scheme: dark){ .bottom-sticky{ background:rgba(17,24,39,0.92); border-top:1px solid rgba(255,255,255,.06);} }
/* Compact spacing */
.compact .block-container{ padding-top:10px !important; padding-bottom:56px !important;}
/* iPad/iPhone — smaller clock chips (scoped under .clock) */
.clock .stButton > button{
  padding:4px 8px !important;
  font-size:0.90rem !important;
  min-width:44px !important;
}
.clock .stColumns{ margin-bottom:4px !important; }
</style>
""",
    unsafe_allow_html=True
)

# ========= INIT SHEETS + HYDRATE =========
sheets_connected = init_sheets()

# Load Playbook (merge categories if present)
if sheets_connected:
    try:
        playbook_ws = sh.worksheet("Playbook")
        playbook_df = pd.DataFrame(playbook_ws.get_all_records())
        if not playbook_df.empty:
            if "Play Name" in playbook_df:
                names = playbook_df["Play Name"].dropna().astype(str).str.strip().tolist()
                if names:
                    ss["plays_master"] = sorted(set(ss["plays_master"]) | set(names))
            if "System" in playbook_df:
                cat = {}
                for _, r in playbook_df.iterrows():
                    nm = str(r.get("Play Name","")).strip()
                    sys = str(r.get("System","")).strip() or UNCATEGORIZED
                    if nm:
                        cat.setdefault(sys, []).append(nm)
                if cat:
                    ss["play_categories"] = {k: sorted(set(v)) for k,v in cat.items()}
    except Exception:
        pass

# Load Games index/meta
games_df_cache = pd.DataFrame()
if sheets_connected:
    games_df_cache = list_games_df()
    if not games_df_cache.empty:
        for r in games_df_cache.to_dict("records"):
            name = r.get("Game Name")
            if name and name not in ss["games"]:
                ss["games"].append(name)
            if name:
                meta = ss["game_meta"].setdefault(name, {})
                if r.get("Type"): meta["type"] = r["Type"]
                if r.get("Opponent"): meta["opponent"] = r["Opponent"]
        ss["games"] = sorted(set(ss["games"]))

# ========= HEADER / LOGO =========
hdr1, hdr2, hdr3 = st.columns([1,3,2])
with hdr2:
    _logo = logo_image_bytes()
    if _logo: st.image(_logo, use_column_width=True)
st.caption("✅ Google Sheets Live Sync" if sheets_connected else "⚠️ Local mode — use Postgame Upload")

# ========= HELPERS: NEXT QUARTER / UNDO =========
QUARTERS = ["Q1","Q2","Q3","Q4","OT"]
def next_quarter(q):
    try:
        idx = QUARTERS.index(q)
    except ValueError:
        idx = 0
    return QUARTERS[min(idx+1, len(QUARTERS)-1)]

def undo_last_possession():
    """Remove last possession of current game (local + Sheets)."""
    rows = ss["game_data"].get(ss["current_game"], [])
    if not rows:
        st.warning("No possessions to undo.")
        return
    rows.pop()
    ss["game_data"][ss["current_game"]] = rows
    if sheets_connected:
        try:
            df_now = pd.DataFrame(rows)
            sheets_overwrite_game(ss["current_game"], df_now)
            ss["sheet_rev"] += 1
            read_game_from_sheets.clear()
            st.success("Undid last possession (synced).")
        except Exception as e:
            st.error(f"Undo sync failed: {e}")
    else:
        st.success("Undid last possession (local).")

# ========= DETERMINE CURRENT GAME (URL -> fallback to latest) =========
_qp = _get_qp()
qp_game = None
if "game" in _qp:
    v = _qp["game"]; qp_game = v[0] if isinstance(v, list) else v

# Fallback to most recently created game if no param
def most_recent_game_name():
    if games_df_cache.empty: return None
    try:
        gdf = games_df_cache.copy()
        gdf["Created At"] = pd.to_datetime(gdf["Created At"], errors="coerce")
        gdf = gdf.sort_values("Created At")
        return gdf["Game Name"].iloc[-1] if not gdf.empty else None
    except Exception:
        return None

if qp_game and qp_game in ss["games"]:
    ss["current_game"] = qp_game
elif sheets_connected:
    mr = most_recent_game_name()
    if mr:
        ss["current_game"] = mr
else:
    if ss["current_game"] not in ss["games"]:
        ss["current_game"] = ss["games"][0]

_set_qp(game=ss["current_game"])

# ALWAYS rehydrate game rows from Sheets (stronger persistence)
if sheets_connected:
    try:
        df_h = read_game_from_sheets(ss["current_game"], ss["sheet_rev"])
        ss["game_data"][ss["current_game"]] = df_h.to_dict("records") if not df_h.empty else ss.get("game_data", {}).get(ss["current_game"], [])
    except Exception:
        pass

# ========= STICKY GAME CONTROLS (Top) =========
st.markdown('<div class="top-sticky">', unsafe_allow_html=True)
gc1, gc2, gc3, gc4, gc5, gc6 = st.columns([2,1,2,1,1,1])
with gc1:
    current_game = st.selectbox("Current Game", options=ss["games"], index=ss["games"].index(ss["current_game"]) if ss["current_game"] in ss["games"] else 0)
    if current_game != ss["current_game"]:
        ss["current_game"] = current_game
        _set_qp(game=ss["current_game"])
        if sheets_connected:
            df_h = read_game_from_sheets(ss["current_game"], ss["sheet_rev"])
            ss["game_data"][ss["current_game"]] = df_h.to_dict("records") if not df_h.empty else []
        ss["game_meta"].setdefault(ss["current_game"], {"quarter":"Q1","opponent":"","type":"Game"})
with gc2:
    meta = ss["game_meta"].setdefault(ss["current_game"], {"quarter":"Q1","opponent":"","type":"Game"})
    meta["quarter"] = st.selectbox("Quarter", QUARTERS, index=QUARTERS.index(meta.get("quarter","Q1")))
with gc3:
    meta["opponent"] = st.text_input("Opponent", value=meta.get("opponent",""))
with gc4:
    meta["type"] = st.selectbox("Type", ["Game","Scrimmage","Scout"], index=["Game","Scrimmage","Scout"].index(meta.get("type","Game")))
with gc5:
    if st.button("Next Quarter"):
        meta["quarter"] = next_quarter(meta.get("quarter","Q1"))
        st.toast(f"Quarter → {meta['quarter']}", icon="⏭️")
with gc6:
    ss["compact_mode"] = st.toggle("Compact", value=ss["compact_mode"], help="Smaller padding & reserves space for bottom quick bar")
st.markdown('</div>', unsafe_allow_html=True)

# Quick create row (appears only until you create one new game)
if not ss["hide_create_row"]:
    cg1, cg2, cg3, cg4 = st.columns([2,1.2,1.8,0.8])
    with cg1:
        new_name = st.text_input("Create New Game — Name")
    with cg2:
        new_type = st.selectbox("Type", ["Game","Scrimmage","Scout"], key="new_type_inline")
    with cg3:
        new_opp = st.text_input("Opponent", key="new_opp_inline")
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

# ========= LAYOUT: 3-panel tagging =========
L, C, R = st.columns([1.2, 2.1, 1.7])

# ----- LEFT: Clock + Caller + 2nd Chance -----
with L:
    st.subheader("⏱ Clock")
    def add_seconds(m: int, s: int, delta: int):
        total = m*60 + s + delta; total = max(0, min(12*60, total)); return total//60, total%60

    st.markdown('<div class="clock">', unsafe_allow_html=True)  # SCOPE for smaller buttons

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

    st.markdown('</div>', unsafe_allow_html=True)  # end .clock scope

    # highlight current minute/second buttons (visual aid)
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
        sel_sc_outcomes = chip_check_group("Second-Chance Outcomes", SC_OUTCOMES, key="ms_sc_outcomes", cols=3, small=True)

# ----- CENTER: Plays (categories + search + +Add) -----
with C:
    st.subheader("📖 Plays (Categorized)")
    search = st.text_input("Search Plays", value="", placeholder="Type to filter plays...")

    selected_all = set(st.session_state.get("ms_plays", set()))
    for cat_name, plays in ss["play_categories"].items():
        show_list = [p for p in plays if (search.lower() in p.lower())] if search else plays
        if not show_list: continue
        expanded_default = cat_name in ("Pace & Space", "2 Man Game")  # open by default
        with st.expander(f"{cat_name} ({len(show_list)})", expanded=expanded_default):
            subset = chip_check_group("", show_list, key=f"ms_plays_cat_{cat_name}", cols=4, default_selected=[], small=True)
            selected_all.update(subset)
    st.session_state["ms_plays"] = set(selected_all)
    sel_plays_sorted = sorted(selected_all, key=str.lower)

    # Inline +Add Play (with category)
    try:
        with st.popover("➕ Add Play"):
            np = st.text_input("Play Name")
            cat_choice = st.selectbox("Category", list(ss["play_categories"].keys()) + [UNCATEGORIZED], index=0)
            if st.button("Add"):
                if np.strip():
                    nm = np.strip()
                    if nm not in ss["plays_master"]:
                        ss["plays_master"].append(nm); ss["plays_master"].sort()
                    ss["play_categories"].setdefault(cat_choice, [])
                    if nm not in ss["play_categories"][cat_choice]:
                        ss["play_categories"][cat_choice].append(nm); ss["play_categories"][cat_choice] = sorted(set(ss["play_categories"][cat_choice]))
                    if sheets_connected:
                        sh.worksheet("Playbook").append_row(["", nm, cat_choice], value_input_option="USER_ENTERED")
                    st.success(f"Added play: {nm} → {cat_choice}"); st.rerun()
                else:
                    st.warning("Enter a play name.")
    except Exception:
        with st.expander("➕ Add Play"):
            np = st.text_input("Play Name")
            cat_choice = st.selectbox("Category", list(ss["play_categories"].keys()) + [UNCATEGORIZED], index=0)
            if st.button("Add"):
                if np.strip():
                    nm = np.strip()
                    if nm not in ss["plays_master"]:
                        ss["plays_master"].append(nm); ss["plays_master"].sort()
                    ss["play_categories"].setdefault(cat_choice, [])
                    if nm not in ss["play_categories"][cat_choice]:
                        ss["play_categories"][cat_choice].append(nm); ss["play_categories"][cat_choice] = sorted(set(ss["play_categories"][cat_choice]))
                    if sheets_connected:
                        sh.worksheet("Playbook").append_row(["", nm, cat_choice], value_input_option="USER_ENTERED")
                    st.success(f"Added play: {nm} → {cat_choice}"); st.rerun()
                else:
                    st.warning("Enter a play name.")

    # Credit Play picker
    if sel_plays_sorted:
        default_credit = sel_plays_sorted[0] if (ss.get("credit_play") not in sel_plays_sorted) else ss["credit_play"]
        ss["credit_play"] = st.selectbox("Credit Play (PPP attribution)", sel_plays_sorted, index=sel_plays_sorted.index(default_credit))

# ----- RIGHT: Call Types -----
with R:
    st.subheader("🗂 Call Types")
    sel_call_types = chip_check_group("", CALL_TYPES_MASTER, key="ms_call_types", cols=3, small=True)
    if not sel_call_types:
        sel_call_types = ["Half Court"]

# ===== Build & Push Row =====
def join_pipe(items): return " | ".join(items) if items else ""

def build_row_from_ui(outcome_text: str):
    plays_str = join_pipe(sel_plays_sorted)
    call_types_str = join_pipe(sel_call_types or ["Half Court"])
    sc_str = join_pipe(sel_sc_outcomes) if second_chance == "Yes" else ""
    pts = points_from_outcome(outcome_text)
    return {
        "Timestamp": f"{ss['game_clock_min']}:{ss['game_clock_sec']}",
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

# ========= STICKY QUICK BAR (Bottom) =========
st.markdown('<div class="bottom-sticky">', unsafe_allow_html=True)
qb1, qb2, qb3, qb4 = st.columns(4)
with qb1:
    if st.button("Made 2"): ss["pending_action"] = "Made 2"
    if st.button("Miss 2"): ss["pending_action"] = "Missed 2"
with qb2:
    if st.button("Made 3"): ss["pending_action"] = "Made 3"
    if st.button("Miss 3"): ss["pending_action"] = "Missed 3"
with qb3:
    if st.button("Foul 1/2"): ss["pending_action"] = "Foul (Made 1/2)"
    if st.button("Foul 2/2"): ss["pending_action"] = "Foul (Made 2/2)"
with qb4:
    if st.button("TO"): ss["pending_action"] = "Turnover"
    if st.button("Dead Ball"): ss["pending_action"] = "Dead Ball"
    if st.button("Timeout"): ss["pending_action"] = "Timeout"
    if st.button("DB Foul"): ss["pending_action"] = "Dead Ball Foul"
    if st.button("↩︎ Undo Last"):  # one-tap undo
        undo_last_possession()
st.markdown('</div>', unsafe_allow_html=True)

# Pending banner + Confirm
if ss.get("pending_action"):
    with st.container(border=True):
        st.write(
            f"Pending: **{ss['pending_action']}** | Clock **{ss['game_clock_min']}:{ss['game_clock_sec']}** | Q **{meta.get('quarter','Q1')}** "
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

# ========= LIVE DASHBOARD + RECENT =========
df = pd.DataFrame(ss["game_data"].get(ss["current_game"], []))
st.subheader("📊 Live: Play Metrics & Recent Possessions")
DL, DR = st.columns([1.2, 1.0])

with DL:
    if df.empty:
        st.info("No data yet for visuals.")
    else:
        vis = df.copy()
        vis["Success"] = vis["Success"].fillna("").astype(str)
        def _success_to_bool(s): return str(s).strip().lower() == "yes"

        # CREDIT PLAY basis
    cred = json.loads(st.secrets["gcp_service_account"], strict=False)

