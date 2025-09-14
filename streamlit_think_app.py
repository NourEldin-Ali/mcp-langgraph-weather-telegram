import asyncio
import os
from typing import Optional

import streamlit as st
from dotenv import load_dotenv

# Ensure project root is importable
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in os.sys.path:
    os.sys.path.insert(0, ROOT)

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from agent_think.app import build_graph
from mcp_client.mcp_manager import MCPServersManager


load_dotenv()

st.set_page_config(
    page_title="Agent Think · Weather → Telegram",
    page_icon="🧠",
    layout="centered",
)

st.title("🧠 Agent Think: Weather → Telegram")
st.write(
    "Free-form instructions where the agent decides which tools to call (ReAct-style).\n"
    "Examples: ‘Get weather for Berlin and Paris and send in one Telegram message’, or ‘Send separate messages’."
)

with st.sidebar:
    st.header("Settings")
    chat_override: Optional[str] = st.text_input(
        "Override Telegram chat_id (optional)", value=""
    ).strip() or None
    show_state = st.checkbox("Show final state JSON", value=False)

task = st.text_area(
    "Instruction",
    value=(
        "Get the weather for Paris and Berlin. Send a single concise Telegram message."
    ),
    help="Describe what you want. You can mention multiple cities and how to send messages.",
)

run = st.button("Run Agent Think")


async def run_think_agent(task_text: str, chat_id: Optional[str] = None) -> dict:
    """Run the Agent Think graph for a single instruction."""
    # Use the shared MCP servers config
    async with MCPServersManager("mcp_client/servers_config.json") as mcp_mgr:
        app = build_graph(mcp_mgr)

        init_state = {
            "messages": [HumanMessage(content=task_text)],
            "weather_results": [],
            "loops": 0,
        }
        # If a chat override is provided, let the instruction mention it implicitly; the tool itself
        # falls back to env if chat_id is None. We'll append a hint message if override is set.
        if chat_id:
            init_state["messages"].append(
                HumanMessage(content=f"Use this Telegram chat_id: {chat_id}")
            )

        final = await app.ainvoke(init_state)
        return final


def _extract_last_ai_text(messages) -> str:
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            try:
                return str(m.content)
            except Exception:
                return ""
    return ""


if run:
    if not task.strip():
        st.error("Please enter an instruction.")
    else:
        st.info("Running agent…")
        try:
            result = asyncio.run(run_think_agent(task.strip(), chat_override))
            st.success("Done! Check Telegram if a message was sent.")

            # Show a helpful preview: last AI message or observation
            msgs = result.get("messages", [])
            preview = _extract_last_ai_text(msgs) if msgs else ""
            if preview:
                st.subheader("Agent Output Preview")
                st.code(preview, language="text")

            if show_state:
                st.subheader("Final State")
                # Messages are not JSON-serializable; show counts and types, not full objects
                safe = dict(result)
                if "messages" in safe:
                    safe["messages"] = [type(m).__name__ for m in safe["messages"]]
                st.json(safe)
        except Exception as e:
            st.error(str(e))

