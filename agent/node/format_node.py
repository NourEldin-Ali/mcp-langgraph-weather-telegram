import re

from agent.state.agent_state import AgentState


async def format_message_node(state: AgentState, llm) -> AgentState:
        wx = state.get("weather_payload", {})
        loc = wx.get("resolved_location") or state.get("location", "")
        w = wx.get("weather", {})

        sys = (
            "You write concise weather summaries for Telegram.\n"
            "Output ONLY the final message (no analysis, no tags). "
            "Use at most two short lines with • bullets. Be friendly and clear."
        )
        usr = (
            f"Location: {loc}\n"
            f"Temperature: {w.get('temperature')}{w.get('units', {}).get('temperature', '')}\n"
            f"Feels Like: {w.get('apparent_temperature')}{w.get('units', {}).get('temperature', '')}\n"
            f"Humidity: {w.get('humidity')}{w.get('units', {}).get('humidity', '')}\n"
            f"Wind: {w.get('wind_speed')} {w.get('units', {}).get('wind_speed', '')}\n"
            f"Time: {w.get('time')}"
        )

        # Prefer async; fallback to sync if provider lacks ainvoke
        try:
            resp = await llm.ainvoke(
                [{"role": "system", "content": sys}, {"role": "user", "content": usr}]
            )
            text = resp.content
        except AttributeError:
            text = llm.invoke(
                [{"role": "system", "content": sys}, {"role": "user", "content": usr}]
            ).content

        clean = _strip_think_blocks(str(text))
        state["message_text"] = _format_to_two_bullets(clean)
        return state


def _strip_think_blocks(text: str) -> str:
    """Remove any <think>...</think> blocks and tidy whitespace."""
    if not isinstance(text, str):
        return ""
    cleaned = re.sub(r"(?is)<\s*think\s*>.*?<\s*/\s*think\s*>", "", text)
    # normalize trailing spaces before newlines
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip()


def _format_to_two_bullets(text: str) -> str:
    """
    Ensure output is at most two short lines and each starts with a bullet.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 2:
        lines = lines[:2]
    lines = [ln if ln.lstrip().startswith("•") else f"• {ln}" for ln in lines]
    return "\n".join(lines)