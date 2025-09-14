import asyncio
import json
import os
import streamlit as st
from dotenv import load_dotenv

# Ensure project root is importable
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in os.sys.path:
    os.sys.path.insert(0, ROOT)

from agent.main import run_agent

load_dotenv()

st.set_page_config(page_title="Weather → Telegram Agent", page_icon="⛅", layout="centered")

st.title("⛅ Weather → Telegram Agent")
st.write("Enter a location and send a concise weather update to your Telegram chat using MCP + LangGraph.")

with st.sidebar:
    st.header("Settings")
    units = st.selectbox("Units", ["Default (.env)", "metric", "imperial"], index=0)
    show_state = st.checkbox("Show final state JSON", value=True)

location = st.text_input("Location", value="Paris, FR", help="City, optionally with country code (e.g., 'Paris, FR').")

run = st.button("Run Agent")

if run:
    if not location.strip():
        st.error("Please enter a location.")
    else:
        st.info("Running agent…")
        selected_units = None if units == "Default (.env)" else units
        try:
            result = asyncio.run(run_agent(location=location.strip(), units=selected_units))
            st.success("Done! Check Telegram.")
            st.code(result.get("message_text", ""), language="text")
            if show_state: st.json(result)
        except Exception as e:
            st.error(str(e))