import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import streamlit.components.v1 as components
import gspread

# --- CONSTANTS & CONFIGURATION ---
# The URL for the publicly shared Google Sheets spreadsheet
SHEETS_URL = st.secrets["SHEETS_URL"]

# Master lists for UI dropdowns/multiselects
CALLERS = ["John", "Paul", "George", "Ringo", "Other"]
QUARTERS = ["Q1", "Q2", "Q3", "Q4", "OT", "2OT", "3OT", "4OT"]
SC_OUTCOMES = [
    "Made 2", "Missed 2", "Made 3", "Missed 3", "Foul (Made 1/2)", "Foul (Made 2/2)",
    "Turnover", "Dead Ball", "Timeout", "Dead Ball Foul", "Blocked", "Free Throw"
]
AUTO_DEC_SECONDS = 30 # seconds to auto-decrement the clock on a successful possession

GAME_HEADERS = [
    "Timestamp", "Plays", "Credit Play", "Call Type", "Caller", "Outcome", "Points",
    "2nd Chance?", "2nd Chance Outcome", "Quarter", "Opponent", "Game Type", "Success"
]

# --- HELPER FUNCTIONS ---
def is_success(outcome: str):
    """Checks if an outcome is a 'successful' play."""
    if not isinstance(outcome, str): return False
    return outcome in ["Made 2", "Made 3", "Foul (Made 1/2)", "Foul (Made 2/2)", "Free Throw"]

def points_from_outcome(outcome: str):
    """Returns the points scored for a given outcome."""
    if not isinstance(outcome, str): return 0
    if outcome == "Made 2": return 2
    if outcome == "Made 3": return 3
    if outcome == "Foul (Made 1/2)": return 1
    if outcome == "Foul (Made 2/2)": return 2
    return 0

def get_ss(key, default):
    """Returns a value from session_state, or sets a default if it doesn't exist."""
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]

# --- GOOGLE SHEETS INTERACTION ---
@st.cache_resource(ttl=3600)
def get_gspread_client():
    """Initializes and returns a gspread client."""
    try:
        # Load credentials from st.secrets
        gs_client = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        return gs_client
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {e}")
        return None

gs_client = get_gspread_client()
sheets_connected = gs_client is not None

def sheets_append_play(game_name, row_data):
    """Appends a new row to a specific worksheet."""
    try:
        sh = gs_client.open_by_url(SHEETS_URL)
        worksheet = sh.worksheet(game_name)
        worksheet.append_row(row_data)
        return True
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Worksheet '{game_name}' not found. Please create it manually.")
        return False
    except Exception as e:
        st.error(f"Error appending row to Google Sheets: {e}")
        return False

def sheets_overwrite_game(game_name, df: pd.DataFrame):
    """Overwrites an entire game's worksheet with a new DataFrame."""
    try:
        sh = gs_client.open_by_url(SHEETS_URL)
        worksheet = sh.worksheet(game_name)
        worksheet.clear()
        worksheet.append_row(list(df.columns))
        worksheet.append_rows(df.astype(str).values.tolist())
        return True
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Worksheet '{game_name}' not found. Please create it manually.")
        return False
    except Exception as e:
        st.error(f"Error overwriting sheet: {e}")
        return False

@st.cache_data(ttl=300)
def read_game_from_sheets(game_name):
    """Reads a specific worksheet into a DataFrame."""
    if not sheets_connected:
        return pd.DataFrame()
    try:
        sh = gs_client.open_by_url(SHEETS_URL)
        worksheet = sh.worksheet(game_name)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        # Type casting for specific columns
        if not df.empty:
            df['Points'] = pd.to_numeric(df['Points'], errors='coerce').fillna(0).astype(int)
        return df
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error reading from Google Sheets: {e}")
        return pd.DataFrame()

# --- SESSION STATE MANAGEMENT ---
ss = st.session_state

get_ss("game_meta", {})
get_ss("current_game", None)
get_ss("game_data", {})
get_ss("pending_action", None)
get_ss("ms_plays", set()) # Multiselect play tags
get_ss("plays_master", set()) # All unique plays from all games
get_ss("game_clock_min", 24)
get_ss("game_clock_sec", "00")

# --- APP LAYOUT ---
st.set_page_config(layout="wide", page_title="Basketball Data Logger", initial_sidebar_state="expanded")
st.markdown("""
<style>
.bottom-sticky {
    position: sticky;
    bottom: 0;
    background-color: #f0f2f6; /* Adjust color to match your theme */
    padding: 10px 0;
    border-top: 1px solid #e6e6e6;
    z-index: 1000;
}
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.title("Settings")

    if sheets_connected:
        try:
            sh = gs_client.open_by_url(SHEETS_URL)
            worksheets = [ws.title for ws in sh.worksheets()]
            existing_games = [ws for ws in worksheets if ws != "master_config"]
        except Exception:
            existing_games = []
    else:
        existing_games = []

    st.subheader("Load/Create Game")
    
    # Load game from existing sheets
    selected_game = st.selectbox("Select Existing Game:", existing_games, index=None)
    
    # New game creation input
    new_game_name = st.text_input("Or Start New Game Name:")
    new_game_opp = st.text_input("New Game Opponent:", "")
    new_game_type = st.selectbox("New Game Type:", ["Game", "Scrimmage", "Scout"])

    if st.button("Load/Create Game"):
        if selected_game:
            ss["current_game"] = selected_game
            ss["game_meta"][selected_game] = {"opponent": "N/A", "type": "Game"} # Dummy metadata for existing games
            st.success(f"Game '{selected_game}' loaded.")
        elif new_game_name:
            if sheets_connected:
                # Check if worksheet already exists
                if new_game_name not in existing_games:
                    try:
                        sh = gs_client.open_by_url(SHEETS_URL)
                        worksheet = sh.add_worksheet(title=new_game_name, rows="1", cols="1")
                        worksheet.append_row(GAME_HEADERS)
                        st.success(f"New worksheet '{new_game_name}' created!")
                    except Exception as e:
                        st.error(f"Failed to create new sheet: {e}")
                        ss["current_game"] = None
                        st.stop()
                else:
                    st.warning(f"Worksheet '{new_game_name}' already exists. Loading it instead.")
            ss["current_game"] = new_game_name
            ss["game_meta"][new_game_name] = {"opponent": new_game_opp, "type": new_game_type}
            st.success(f"Game '{new_game_name}' loaded.")
        else:
            st.warning("Please select an existing game or enter a new game name.")
            st.stop()
    
    if ss["current_game"]:
        st.subheader("Game Clock")
        
        # Quarter selection
        current_quarter = ss["game_meta"][ss["current_game"]].get("quarter", "Q1")
        ss["game_meta"][ss["current_game"]]["quarter"] = st.selectbox(
            "Quarter:", QUARTERS, index=QUARTERS.index(current_quarter)
        )
        
        # Clock control
        c1, c2 = st.columns([1,1])
        with c1:
            ss["game_clock_min"] = st.number_input("Minutes:", min_value=0, max_value=60, value=ss["game_clock_min"])
        with c2:
            ss["game_clock_sec"] = st.number_input("Seconds:", min_value=0, max_value=59, value=int(ss["game_clock_sec"]), format="%02d")
        
        if st.button("Reset Clock"):
            ss["game_clock_min"], ss["game_clock_sec"] = 24, "00"
            
        st.subheader("Tagging")
        ss["plays_master"] = set(read_game_from_sheets.clear() or read_game_from_sheets(ss["current_game"])["Plays"].str.split(" | ").explode().str.strip().dropna().unique())
        
        ss["ms_plays"] = st.multiselect(
            "Tag Plays:",
            options=sorted(list(ss["plays_master"])),
            default=list(ss["ms_plays"])
        )
        new_play = st.text_input("New Play Tag:", "").strip()
        
        if new_play and st.button("Add Play Tag"):
            if new_play not in ss["plays_master"]:
                ss["plays_master"].add(new_play)
                st.success(f"'{new_play}' added!")
                st.experimental_rerun()
            else:
                st.warning(f"'{new_play}' already exists.")
        
        # Display selected plays in sorted order
        sel_plays_sorted = sorted(list(ss["ms_plays"]))
        
        # Credit Play selection for PPP
        ss["credit_play"] = st.selectbox(
            "Credit Play (for PPP):",
            options=[""] + sel_plays_sorted
        )

# --- MAIN APP ---
if not ss["current_game"]:
    st.info("Please select or create a game in the sidebar to begin.")
else:
    st.title(f"🏀 Live Game: {ss['current_game']}")
    
    # Reload data from sheets on app start for rehydration
    if ss["current_game"] not in ss["game_data"]:
        with st.spinner(f"Loading game data for '{ss['current_game']}'..."):
            df_rehydrated = read_game_from_sheets(ss["current_game"])
            ss["game_data"][ss["current_game"]] = df_rehydrated.to_dict("records")
            
    st.header("Possession Logger")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        caller = st.selectbox("Caller:", CALLERS)
    with col2:
        sel_call_types = st.multiselect("Call Type:", ["Half Court", "ATO", "BLOB", "SLOB", "Press Break"], default=["Half Court"])
    with col3:
        second_chance = st.selectbox("2nd Chance?:", ["No", "Yes"])
        if second_chance == "Yes":
            sel_sc_outcomes = st.multiselect("2nd Chance Outcome(s):", SC_OUTCOMES)
        else:
            sel_sc_outcomes = []
    
    # ===== Build & Push Row =====
    def build_row_from_ui(outcome_text: str):
        def join_pipe(items): return " | ".join(items) if items else ""
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
                # rehydrate to confirm sync
                read_game_from_sheets.clear()
                df_h = read_game_from_sheets(ss["current_game"])
                if not df_h.empty:
                    ss["game_data"][ss["current_game"]] = df_h.to_dict("records")
            except Exception as e:
                st.error(f"Sheets append failed: {e}")
    
    def auto_decrement_clock():
        m = ss["game_clock_min"]; s = int(ss["game_clock_sec"])
        total = max(0, m*60 + s - AUTO_DEC_SECONDS)
        ss["game_clock_min"], ss["game_clock_sec"] = total//60, f"{total%60:02d}"
    
    # ===== Sticky Bottom Quick Bar =====
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
        if st.button("↩︎ Undo Last"):
            rows = ss["game_data"].get(ss["current_game"], [])
            if rows:
                rows.pop()
                ss["game_data"][ss["current_game"]] = rows
                if sheets_connected:
                    try:
                        sheets_overwrite_game(ss["current_game"], pd.DataFrame(rows))
                        read_game_from_sheets.clear()
                        st.success("Undid last possession (synced).")
                    except Exception as e:
                        st.error(f"Undo sync failed: {e}")
            else:
                st.warning("No possessions to undo.")
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Callback function to handle form submission
    def on_confirm_callback():
        if not sel_plays_sorted:
            st.error("Select at least one play.")
            return
        if not ss.get("credit_play"):
            st.error("Pick a Credit Play for PPP attribution.")
            return
        
        row = build_row_from_ui(ss["pending_action"])
        push_row(row)
        ss["pending_action"] = None
        ss["ms_plays"] = set() # clear selection for next possession
        auto_decrement_clock()
        st.success("Possession logged and synced!")
    
    # Pending banner + Confirm (now using a form)
    if ss.get("pending_action"):
        with st.form("pending_form", border=True):
            st.write(
                f"Pending: **{ss['pending_action']}** | Clock **{ss['game_clock_min']}:{ss['game_clock_sec']}** | Q **{ss['game_meta'][ss['current_game']].get('quarter','Q1')}** "
                f"| Plays: **{', '.join(sel_plays_sorted) or '(none)'}** → Credit **{ss.get('credit_play') or '(pick)'}** "
                f"| Call Type(s): **{ ' | '.join(sel_call_types) }** | 2nd: **{second_chance}**"
                + (f" (**{' | '.join(sel_sc_outcomes)}**)" if (second_chance=='Yes' and sel_sc_outcomes) else "")
            )
            c1, c2 = st.columns(2)
            with c1:
                st.form_submit_button("Confirm", type="primary", on_click=on_confirm_callback)
            with c2:
                if st.form_submit_button("Cancel"):
                    ss["pending_action"] = None
                    st.info("Quick action canceled.")
                    st.rerun()
    
    # ===== Live Dashboard + Recent Possessions =====
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
            cred = vis[(vis["Credit Play"].notna()) & (vis["Credit Play"].astype(str) != "")]
            grp_credit = pd.DataFrame()
            if not cred.empty:
                grp_credit = cred.groupby("Credit Play", dropna=False).agg(
                    Attempts=("Points", "count"),
                    Points=("Points", "sum"),
                    Successes=("Success", lambda s: sum(_success_to_bool(x) for x in s))
                ).reset_index()
                grp_credit["PPP"] = grp_credit["Points"] / grp_credit["Attempts"]
                grp_credit["Success%"] = grp_credit["Successes"] / grp_credit["Attempts"]
                grp_credit = grp_credit.sort_values("PPP", ascending=False).round(2)
                st.markdown("##### Performance: Credit Play (PPP)")
                st.dataframe(
                    grp_credit[["Credit Play","Attempts","Points","PPP","Success%"]],
                    use_container_width=True,
                    hide_index=True
                )
                
                # PPP Chart
                ppp_chart = alt.Chart(grp_credit).mark_bar().encode(
                    x=alt.X("Credit Play", sort="-y", title=None),
                    y=alt.Y("PPP", title="Points Per Possession"),
                    tooltip=["Credit Play", "PPP", "Attempts", "Success%"]
                ).properties(
                    title="PPP by Play",
                    height=300
                )
                st.altair_chart(ppp_chart, use_container_width=True)
    
            # ALL TAGGED PLAYS basis
            vis_exploded = vis.assign(Plays=vis['Plays'].str.split('| ')).explode('Plays').copy()
            vis_exploded["Plays"] = vis_exploded["Plays"].str.strip()
            vis_exploded = vis_exploded[vis_exploded["Plays"] != ""]
            
            grp_all = pd.DataFrame()
            if not vis_exploded.empty:
                grp_all = vis_exploded.groupby("Plays", dropna=False).agg(
                    Frequency=("Timestamp", "count"),
                    Successes=("Success", lambda s: sum(_success_to_bool(x) for x in s))
                ).reset_index()
                total_plays = grp_all["Frequency"].sum()
                grp_all["Frequency%"] = grp_all["Frequency"] / total_plays
                grp_all["Success%"] = grp_all["Successes"] / grp_all["Frequency"]
                grp_all = grp_all.sort_values("Frequency", ascending=False).round(2)
                
                st.markdown("##### Frequency: All Tagged Plays")
                st.dataframe(
                    grp_all[["Plays","Frequency","Frequency%","Success%"]],
                    use_container_width=True,
                    hide_index=True
                )
    
    with DR:
        if not df.empty:
            # Frequency Chart
            freq_chart = alt.Chart(grp_all).mark_bar().encode(
                x=alt.X("Plays", sort="-y", title=None),
                y=alt.Y("Frequency", title="Frequency"),
                tooltip=["Plays", "Frequency", "Frequency%"]
            ).properties(
                title="Frequency of Plays",
                height=300
            )
            st.altair_chart(freq_chart, use_container_width=True)
            
            # Success Rate Chart
            success_chart = alt.Chart(grp_all).mark_bar().encode(
                x=alt.X("Plays", sort="-y", title=None),
                y=alt.Y("Success%", title="Success Rate", axis=alt.Axis(format=".0%")),
                tooltip=["Plays", "Success%", "Frequency"]
            ).properties(
                title="Success Rate by Play",
                height=300
            )
            st.altair_chart(success_chart, use_container_width=True)
    
    # ----- EDIT/DELETE Plays Section -----
    st.markdown("### 📝 Edit & Delete Plays")
    if df.empty:
        st.info("No plays to edit or delete.")
    else:
        # Add a unique index to each row for tracking changes
        df_editor = df.reset_index().rename(columns={"index": "id"})
        df_editor["id"] = df_editor.index
        
        # Use st.data_editor for editable table
        st.markdown("#### Edit Possessions")
        edited_df = st.data_editor(
            df_editor,
            column_order=GAME_HEADERS,
            column_config={
                "Timestamp": st.column_config.TextColumn(
                    "Timestamp (HH:MM:SS)", help="Game clock timestamp"
                ),
                "Plays": st.column_config.TextColumn(
                    "Plays", help="Multiple plays separated by | "
                ),
                "Credit Play": st.column_config.SelectboxColumn(
                    "Credit Play", options=ss["plays_master"]
                ),
                "Call Type": st.column_config.TextColumn("Call Type"),
                "Caller": st.column_config.SelectboxColumn("Caller", options=CALLERS),
                "Outcome": st.column_config.SelectboxColumn("Outcome", options=SC_OUTCOMES),
                "Points": st.column_config.NumberColumn("Points", help="Points scored"),
                "2nd Chance?": st.column_config.SelectboxColumn("2nd Chance?", options=["Yes", "No"]),
                "2nd Chance Outcome": st.column_config.TextColumn("2nd Chance Outcome"),
                "Quarter": st.column_config.SelectboxColumn("Quarter", options=QUARTERS),
                "Opponent": st.column_config.TextColumn("Opponent"),
                "Game Type": st.column_config.SelectboxColumn("Game Type", options=["Game", "Scrimmage", "Scout"]),
                "Success": st.column_config.SelectboxColumn("Success", options=["Yes", "No"]),
            },
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="data_editor_table"
        )
    
        # Convert edited data back to dictionary list
        edited_rows = edited_df.to_dict("records")
        
        # Check for changes and offer to sync
        if edited_rows != ss["game_data"].get(ss["current_game"], []):
            if st.button("Sync Changes", key="sync_button"):
                # Update local session state with the new data
                ss["game_data"][ss["current_game"]] = edited_rows
                
                # Overwrite the sheet with the new DataFrame
                if sheets_connected:
                    try:
                        sheets_overwrite_game(ss["current_game"], pd.DataFrame(edited_rows))
                        read_game_from_sheets.clear()
                        st.success("Changes synced to Google Sheets!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to sync changes: {e}")
                else:
                    st.info("Changes saved locally, but not synced to Google Sheets (local mode).")
                    st.rerun()
    
        # Deletion logic
        st.markdown("#### Delete Possessions")
        rows_to_delete = st.multiselect("Select rows to delete", options=df.index.tolist(), format_func=lambda x: f"Row {x+1}: {df.iloc[x]['Timestamp']} | {df.iloc[x]['Plays']}", key="delete_selector")
        
        if rows_to_delete:
            if st.button("Delete Selected Possessions", key="delete_button"):
                # Get the indices to keep
                indices_to_keep = [i for i in range(len(df)) if i not in rows_to_delete]
                updated_data = [df.iloc[i].to_dict() for i in indices_to_keep]
                
                # Update local state
                ss["game_data"][ss["current_game"]] = updated_data
                
                # Overwrite the sheet
                if sheets_connected:
                    try:
                        sheets_overwrite_game(ss["current_game"], pd.DataFrame(updated_data))
                        read_game_from_sheets.clear()
                        st.success(f"Successfully deleted {len(rows_to_delete)} rows and synced to Google Sheets!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to delete rows: {e}")
                else:
                    st.info("Deletions saved locally, but not synced to Google Sheets (local mode).")
                    st.rerun()
