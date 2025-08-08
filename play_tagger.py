# play-tagger
import streamlit as st
import pandas as pd
from datetime import datetime

# Initialize session state
if 'data' not in st.session_state:
    st.session_state.data = []

st.title("🏀 Basketball Play Call Tagging App (Prototype)")

st.markdown("Tag plays live during games or film sessions and export later.")

# Timestamp input
col1, col2 = st.columns([1, 2])
with col1:
    use_current_time = st.checkbox("Use current time?", value=True)
with col2:
    if use_current_time:
        timestamp = datetime.now().strftime("%H:%M:%S")
    else:
        timestamp = st.text_input("Enter timestamp (e.g. 12:35 Q1)", value="")

# Play info
play_name = st.text_input("Play Name (e.g. Chin, Floppy)")
call_type = st.selectbox("Call Type", ["Early Offense", "Halfcourt", "BLOB", "SLOB", "Zone"])
caller = st.selectbox("Who Called It?", ["Coach", "Player"])
outcome = st.selectbox(
    "Outcome", [
        "Made 2", "Missed 2", "Made 3", "Missed 3", 
        "Foul (Made 1/2)", "Foul (Made 2/2)", "Foul (Missed Both)",
        "Turnover", "Dead Ball"
    ]
)
second_chance = st.radio("2nd Chance?", ["No", "Yes"])

# Points logic
def get_points(outcome):
    if outcome == "Made 2":
        return 2
    elif outcome == "Made 3":
        return 3
    elif outcome == "Foul (Made 1/2)":
        return 1
    elif outcome == "Foul (Made 2/2)":
        return 2
    else:
        return 0

points = get_points(outcome)

# Submit button
if st.button("Add Entry"):
    entry = {
        "Timestamp": timestamp,
        "Play Name": play_name,
        "Call Type": call_type,
        "Caller": caller,
        "Outcome": outcome,
        "Points": points,
        "2nd Chance?": second_chance
    }
    st.session_state.data.append(entry)
    st.success("Play logged!")

# Display tagged plays
if st.session_state.data:
    df = pd.DataFrame(st.session_state.data)
    st.dataframe(df)

    # Download CSV
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("⬇️ Download CSV", data=csv, file_name="play_tags.csv", mime="text/csv")
streamlit
pandas
