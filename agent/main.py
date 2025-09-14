import os
import asyncio
from dotenv import load_dotenv
from mcp_client.mcp_manager import MCPServersManager
from agent.graph import build_graph

async def run_agent(location: str, units: str | None = None) -> dict:
    load_dotenv()
    units = units or os.getenv("DEFAULT_WEATHER_UNITS", "metric")

    # Use the shared MCP servers config
    async with MCPServersManager("mcp_client/servers_config.json") as mcp_mgr:
        app = build_graph(mcp_mgr)
        init = {
            "location": location,
            "units": units,
        }
        final = await app.ainvoke(init)
        return final

if __name__ == "__main__":
    out = asyncio.run(run_agent("Paris, FR"))
    print(out)
