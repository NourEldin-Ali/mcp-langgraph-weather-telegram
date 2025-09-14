import json
from typing import Any

from agent.state.agent_state import AgentState


async def get_weather_node(state: AgentState, mcp_mgr) -> AgentState:
        args = {"location": state["location"]}
        if units := state.get("units"):
            args["units"] = units

        tool_res = await mcp_mgr.call_tool("weather", "get_current_weather", args)
        first = _first_text_block(tool_res)
        payload = _safe_json(first)
        state["weather_payload"] = payload
        return state
    

def _first_text_block(tool_result: Any) -> str | dict:
    """
    Extract the first text content block from an MCP tool response.
    If it's JSON text, the caller may json.loads it.
    """
    if not tool_result:
        return ""
    # MCP result has `.content` which is a list[ContentBlock]
    content = getattr(tool_result, "content", None) or []
    texts = [getattr(c, "text", "") for c in content if getattr(c, "type", "") == "text"]
    return texts[0] if texts else ""


def _safe_json(val: str | dict) -> dict:
    """Parse JSON string to dict; if already a dict, return as-is; fallback to {'text': ...}."""
    if isinstance(val, dict):
        return val
    if not isinstance(val, str) or not val.strip():
        return {}
    try:
        return json.loads(val)
    except json.JSONDecodeError:
        return {"text": val}