
from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # Inputs
    location: str
    units: str  # "metric" | "imperial"
    chat_id: str  # optional override per send

    # Working data
    weather_payload: dict
    message_text: str

    # Outputs
    telegram_result: Any