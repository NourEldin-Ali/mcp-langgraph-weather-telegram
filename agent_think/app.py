# app_multi_weather_telegram.py
from __future__ import annotations

import os
import json
import asyncio
from typing import TypedDict, List, Mapping, Sequence, Any, Optional

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    BaseMessage,
)
from langchain_core.tools import tool
from dotenv import load_dotenv

from config.llm import make_llm
from mcp_client.mcp_manager import MCPServersManager


# ---------- JSON coercion helper ----------
def to_jsonable(x: Any) -> Any:
    """Turn arbitrary tool results into JSON-safe structures."""
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    if isinstance(x, Mapping):
        return {str(k): to_jsonable(v) for k, v in x.items()}
    if isinstance(x, Sequence) and not isinstance(x, (str, bytes, bytearray)):
        return [to_jsonable(v) for v in x]
    if hasattr(x, "model_dump") and callable(x.model_dump):
        try:
            return to_jsonable(x.model_dump())
        except Exception:
            pass
    if hasattr(x, "dict") and callable(x.dict):
        try:
            return to_jsonable(x.dict())
        except Exception:
            pass
    if hasattr(x, "to_dict") and callable(x.to_dict):
        try:
            return to_jsonable(x.to_dict())
        except Exception:
            pass
    if hasattr(x, "json") and callable(x.json):
        try:
            return json.loads(x.json())
        except Exception:
            pass
    return {"repr": repr(x)}  # last resort


# ─────────────────────────────────────────────────────────────────────────────
# Graph state
# ─────────────────────────────────────────────────────────────────────────────
class ThinkState(TypedDict):
    messages: List[BaseMessage]
    weather_results: List[dict]     # accumulated weather payloads
    loops: int                      # guard against runaway tool loops


# ─────────────────────────────────────────────────────────────────────────────
# Build graph
# ─────────────────────────────────────────────────────────────────────────────
def build_graph(mcp_mgr: MCPServersManager):
    # ─────────────────────────────────────────────────────────────────────────
    # Tools (async) backed by MCP
    # ─────────────────────────────────────────────────────────────────────────
    @tool
    async def get_weather(location: str) -> dict:
        """Get current weather for a location (city)."""
        args = {"location": location}
        res = await mcp_mgr.call_tool("weather", "get_current_weather", args)
        return to_jsonable(res)

    @tool
    async def send_telegram(chat_id: Optional[str], text: str) -> dict:
        """Send a Telegram message to a chat id (can be None; falls back to env)."""
        load_dotenv()
        args = {
            "text": text,
            "chat_id": chat_id or os.getenv("TELEGRAM_CHAT_ID"),
        }
        res = await mcp_mgr.call_tool("telegram", "send_message", args)
        return to_jsonable(res)

    lc_tools = [get_weather, send_telegram]

    # ─────────────────────────────────────────────────────────────────────────
    # LLM bound to tools
    # ─────────────────────────────────────────────────────────────────────────
    llm = make_llm()
    llm_bound = llm.bind_tools(lc_tools)

    SYSTEM = (
        "You are an assistant with two tools: get_weather(location) and send_telegram(chat_id, text).\n"
        "\n"
        "Planning rules:\n"
        "1) If the user asks for multiple locations, call get_weather ONCE PER LOCATION.\n"
        "2) Accumulate results. Do NOT call send_telegram until you have ALL requested locations.\n"
        "3) If the user says 'send in one message', combine all results into a single concise message and call send_telegram ONCE.\n"
        "4) If they say 'separately' (or one-per-city), call send_telegram once PER CITY with that city's line.\n"
        "5) If not specified, DEFAULT to a single combined message.\n"
        "6) After any tool result, produce a short, clear user-facing summary (no raw JSON unless asked).\n"
        "7) Do NOT re-call a tool that already succeeded unless the user changed their request.\n"
        "\n"
        "Formatting guidance:\n"
        "- Weather line format: '{location}: {temp_c}°C, {condition}'.\n"
        "- If any field is missing, write '?' for it.\n"
        "- Telegram confirmation: mention chat_id (it can be None) and a short preview of text.\n"
    )

    MAX_TOOL_LOOPS = 8  # allow multiple get_weather calls before sending

    # ─────────────────────────────────────────────────────────────────────────
    # Nodes
    # ─────────────────────────────────────────────────────────────────────────
    async def llm_node(state: ThinkState) -> ThinkState:
        msgs = [SystemMessage(content=SYSTEM)] + state["messages"]
        ai = await llm_bound.ainvoke(msgs)
        state["messages"].append(ai)
        return state

    async def tools_node(state: ThinkState) -> ThinkState:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or not getattr(last, "tool_calls", None):
            return state

        for tc in last.tool_calls:
            name = tc["name"]
            args = tc.get("args") or {}

            # execute
            try:
                if name == get_weather.name:
                    raw = await get_weather.ainvoke(args)
                elif name == send_telegram.name:
                    raw = await send_telegram.ainvoke(args)
                else:
                    raw = {"error": f"Unknown tool '{name}'"}
            except Exception as e:
                raw = {"error": f"{name} failed: {e}"}

            result = to_jsonable(raw)

            # accumulate deterministic state for weather
            if name == get_weather.name and isinstance(result, dict):
                # normalize a small shape the LLM can rely on
                location = result.get("location") or args.get("location") or "Unknown"
                temp_c = result.get("temp_c")
                condition = result.get("condition")
                state["weather_results"].append(
                    {"location": location, "temp_c": temp_c, "condition": condition, "raw": result}
                )

            # emit ToolMessage (so the LLM can 'observe' results)
            state["messages"].append(
                ToolMessage(tool_call_id=tc["id"], content=json.dumps(result), name=name)
            )

        state["loops"] = state.get("loops", 0) + 1
        return state

    # Optional: deterministic readable observation injected after each tool msg
    def  pretty_observation(state: ThinkState) -> ThinkState:
        last = state["messages"][-1]
        if isinstance(last, ToolMessage):
            try:
                data = json.loads(last.content)
            except Exception:
                return state

            text = None
            if last.name == get_weather.name:
                loc = data.get("location", "Unknown")
                temp = data.get("temp_c", "?")
                cond = data.get("condition", "?")
                text = f"Observation: {loc}: {temp}°C, {cond}."
            elif last.name == send_telegram.name and data.get("ok"):
                cid = data.get("chat_id", "?")
                preview = (data.get("text", "")[:60] + "…") if len(data.get("text", "")) > 60 else data.get("text", "")
                mid = data.get("message_id", "?")
                text = f"Observation: Telegram sent to chat {cid} (msg id {mid}): “{preview}”."

            if text:
                state["messages"].append(AIMessage(content=text))
        return state

    # ─────────────────────────────────────────────────────────────────────────
    # Routers (allow multi-tool loop, then END)
    # ─────────────────────────────────────────────────────────────────────────
    def route_after_llm(state: ThinkState):
        last = state["messages"][-1]
        has_tools = isinstance(last, AIMessage) and getattr(last, "tool_calls", None)
        if has_tools and state.get("loops", 0) < MAX_TOOL_LOOPS:
            return "tools"
        return END  # when no tool_calls (or loop budget exhausted), finish

    # compile
    g = StateGraph(ThinkState)
    g.add_node("llm", llm_node)
    g.add_node("tools", tools_node)
    g.add_node("pretty", pretty_observation)

    g.add_edge(START, "llm")
    g.add_conditional_edges("llm", route_after_llm, {"tools": "tools", END: END})
    g.add_edge("tools", "pretty")
    g.add_edge("pretty", "llm")
    return g.compile()


# ─────────────────────────────────────────────────────────────────────────────
# Demo
# ─────────────────────────────────────────────────────────────────────────────
async def demo():
    # use your servers config path
    async with MCPServersManager("mcp_client/servers_config.json") as mcp_mgr:
        app = build_graph(mcp_mgr)

        # # 1) Single city → get weather then (by default) send one message
        # s1 = await app.ainvoke({
        #     "messages": [HumanMessage(content="Get the weather in Paris and send it to my Telegram.")],
        #     "weather_results": [],
        #     "loops": 0
        # })
        # print("\n--- Single city (one message) ---")
        # for m in s1["messages"]:
        #     if isinstance(m, (AIMessage, ToolMessage)):
        #         print(type(m).__name__, m.__dict__.get("name", ""), ":", getattr(m, "content", "")[:240])

        # # 2) Multiple cities → one combined telegram
        # s2 = await app.ainvoke({
        #     "messages": [HumanMessage(content="Get weather for Berlin, Rome, and London. Send in one Telegram message.")],
        #     "weather_results": [],
        #     "loops": 0
        # })
        # print("\n--- Multi-city (combined) ---")
        # for m in s2["messages"]:
        #     if isinstance(m, (AIMessage, ToolMessage)):
        #         print(type(m).__name__, m.__dict__.get("name", ""), ":", getattr(m, "content", "")[:240])

        # # # 3) Multiple cities → separate messages
        # s3 = await app.ainvoke({
        #     "messages": [HumanMessage(content="Get weather for Madrid and Barcelona and send separate Telegram messages for each.")],
        #     "weather_results": [],
        #     "loops": 0
        # })
        # print("\n--- Multi-city (separate) ---")
        # for m in s3["messages"]:
        #     if isinstance(m, (AIMessage, ToolMessage)):
        #         print(type(m).__name__, m.__dict__.get("name", ""), ":", getattr(m, "content", "")[:240])
        
        # 4) Multiple cities without sending resuts  
        s4 = await app.ainvoke({
            "messages": [HumanMessage(content="Get weather for Madrid and Beirut, and show me the results of all.")],
            "weather_results": [],
            "loops": 0
        })
        print("\n--- Multi-city (separate) ---")
        for m in s4["messages"]:
            if isinstance(m, (AIMessage, ToolMessage)):
                print(type(m).__name__, m.__dict__.get("name", ""), ":", getattr(m, "content", "")[:240])


if __name__ == "__main__":
    asyncio.run(demo())
