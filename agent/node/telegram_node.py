
from agent.state.agent_state import AgentState


async def send_telegram_node(state: AgentState, mcp_mgr) -> AgentState:
    args = {"text": state.get("message_text", "")}
    if chat := state.get("chat_id"):
        args["chat_id"] = chat

    tool_res = await mcp_mgr.call_tool("telegram", "send_message", args)
    state["telegram_result"] = tool_res
    return state