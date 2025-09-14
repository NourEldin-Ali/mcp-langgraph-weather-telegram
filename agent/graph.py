from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from config.llm import make_llm
from agent.node.format_node import format_message_node
from agent.node.telegram_node import send_telegram_node
from agent.node.weather_node import get_weather_node
from agent.state.agent_state import AgentState

# ---------------------------
# Graph builder
# ---------------------------

def build_graph(mcp_mgr):
    """
    Build an async LangGraph that:
      1) calls weather:get_current_weather
      2) formats a concise Telegram message via LLM
      3) calls telegram:send_message
    `mcp_mgr` must expose: await mcp_mgr.call_tool(server, tool, args)
    """
    llm = make_llm()
    
    workflow = StateGraph(AgentState)
    
   # Async wrappers so LangGraph can detect/await them
    async def node_get_weather(state: AgentState) -> AgentState:
        return await get_weather_node(state, mcp_mgr)

    async def node_format_message(state: AgentState) -> AgentState:
        return await format_message_node(state, llm)

    async def node_send_telegram(state: AgentState) -> AgentState:
        return await send_telegram_node(state, mcp_mgr)

    workflow.add_node("get_weather", node_get_weather)
    workflow.add_node("format_message", node_format_message)
    workflow.add_node("send_telegram", node_send_telegram)

    workflow.add_edge(START, "get_weather")
    workflow.add_edge("get_weather", "format_message")
    workflow.add_edge("format_message", "send_telegram")
    workflow.add_edge("send_telegram", END)

    return workflow.compile()
