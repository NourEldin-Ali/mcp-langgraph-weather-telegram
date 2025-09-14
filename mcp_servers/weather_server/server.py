from typing import Any, Dict

import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.shared._httpx_utils import create_mcp_http_client
from starlette.requests import Request

async def geocode(location: str) -> Dict[str, Any]:
    """
    Robust geocoding for inputs like "Paris", "Paris, FR", or "Paris ,  fr ".
    - Tries Open-Meteo geocoder with optional country_code filter
    - Picks the highest population match (or the first if no population field)
    """
    q = (location or "").strip()
    if not q:
        raise ValueError("Location is empty")

    # Parse "City, CC" (last token treated as country code if 2-3 chars)
    name = q
    country_code: str | None = None
    if "," in q:
        parts = [p.strip() for p in q.split(",") if p.strip()]
        if len(parts) >= 2:
            name = parts[0]
            tail = parts[-1].upper()
            if 2 <= len(tail) <= 3:
                country_code = tail

    params = {"name": name, "count": 5, "language": "en"}
    if country_code:
        params["country_code"] = country_code

    async with create_mcp_http_client(headers={"User-Agent": "MCP Weather Server"}) as client:
        r = await client.get("https://geocoding-api.open-meteo.com/v1/search", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

    results = data.get("results") or []

    # If we asked for a country_code but API ignored it, filter manually
    if country_code:
        filtered = [x for x in results if (x.get("country_code") or "").upper() == country_code]
        if filtered:
            results = filtered

    if not results:
        # Fallback: retry without country filter if we started with one
        if country_code:
            retry_params = dict(params)
            retry_params.pop("country_code", None)
            async with create_mcp_http_client(headers={"User-Agent": "MCP Weather Server"}) as client:
                r2 = await client.get("https://geocoding-api.open-meteo.com/v1/search", params=retry_params, timeout=30)
                r2.raise_for_status()
                data2 = r2.json()
                results = data2.get("results") or []

    if not results:
        raise ValueError(f"Could not geocode location: {location}")

    # Prefer the most populous result when available
    results.sort(key=lambda x: x.get("population", 0) or 0, reverse=True)
    res = results[0]
    return {
        "lat": res["latitude"],
        "lon": res["longitude"],
        "name": res["name"],
        "country": res.get("country_code"),
    }


async def current_weather(lat: float, lon: float, units: str) -> Dict[str, Any]:
    temp_unit = "celsius" if units == "metric" else "fahrenheit"
    wind_unit = "kmh" if units == "metric" else "mph"
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code",
        "wind_speed_unit": wind_unit,
        "temperature_unit": temp_unit,
        "timezone": "auto",
    }
    async with create_mcp_http_client(headers={"User-Agent": "MCP Weather Server"}) as client:
        r = await client.get(url, params=params, timeout=30)
        r.raise_for_status()
        cur = r.json().get("current", {})
        return {
            "temperature": cur.get("temperature_2m"),
            "apparent_temperature": cur.get("apparent_temperature"),
            "humidity": cur.get("relative_humidity_2m"),
            "wind_speed": cur.get("wind_speed_10m"),
            "weather_code": cur.get("weather_code"),
            "time": cur.get("time"),
            "units": {
                "temperature": "°C" if units == "metric" else "°F",
                "wind_speed": "km/h" if units == "metric" else "mph",
                "humidity": "%",
            },
        }


@click.command()
@click.option("--port", default=8011, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    import os

    DEFAULT_UNITS = (os.getenv("DEFAULT_WEATHER_UNITS") or "metric").lower()
    app = Server("weather-mcp-server")

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        if name != "get_current_weather":
            raise ValueError(f"Unknown tool: {name}")

        if "location" not in arguments:
            raise ValueError("Missing required argument 'location'")

        location = arguments["location"]
        units = (arguments.get("units") or DEFAULT_UNITS).lower()
        geo = await geocode(location)
        wx = await current_weather(geo["lat"], geo["lon"], units)

        payload = {
            "query_location": location,
            "resolved_location": f'{geo["name"]}, {geo["country"]}',
            "weather": wx,
        }
        return [types.TextContent(type="text", text=payload if isinstance(payload, str) else json_dumps(payload))]

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="get_current_weather",
                title="Open-Meteo current weather",
                description="Get current weather for a free-text location (via Open-Meteo geocoding + forecast).",
                inputSchema={
                    "type": "object",
                    "required": ["location"],
                    "properties": {
                        "location": {"type": "string", "description": "Free-text place (e.g., 'Paris, FR')"},
                        "units": {"type": "string", "enum": ["metric", "imperial"], "description": "Units for temperature/wind"},
                    },
                },
            )
        ]

    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request: Request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:  # type: ignore
                await app.run(streams[0], streams[1], app.create_initialization_options())
            return Response()

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        import uvicorn

        uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as streams:
                await app.run(streams[0], streams[1], app.create_initialization_options())

        anyio.run(arun)

    return 0


# Small helper to JSON-encode without importing the whole stdlib in the tool body
def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
