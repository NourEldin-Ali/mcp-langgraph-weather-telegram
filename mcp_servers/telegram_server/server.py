from typing import Any, Dict

import anyio
import click
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.shared._httpx_utils import create_mcp_http_client
from starlette.requests import Request


async def telegram_send_message(
    bot_token: str,
    text: str,
    chat_id: str | int,
    disable_notification: bool = False,
) -> list[types.ContentBlock]:
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_notification": disable_notification,
    }

    # Use the SDK's httpx client helper (sends logs to stderr; avoids polluting stdout)
    async with create_mcp_http_client(headers={"User-Agent": "MCP Telegram Server"}) as client:
        resp = await client.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return [types.TextContent(type="text", text=data if isinstance(data, str) else resp.text)]


@click.command()
@click.option("--port", default=8010, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    import os

    app = Server("telegram-mcp-server")
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    DEFAULT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        if name != "send_message":
            raise ValueError(f"Unknown tool: {name}")

        if "text" not in arguments:
            raise ValueError("Missing required argument 'text'")

        text: str = arguments["text"]
        chat_id = arguments.get("chat_id", DEFAULT_CHAT_ID)
        if not chat_id:
            raise ValueError("chat_id missing (and TELEGRAM_CHAT_ID is not set)")

        disable_notification = bool(arguments.get("disable_notification", False))
        return await telegram_send_message(
            bot_token=BOT_TOKEN or "",
            text=text,
            chat_id=chat_id,
            disable_notification=disable_notification,
        )

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="send_message",
                title="Telegram: Send Message",
                description="Send a text message via Telegram Bot API using a bot token",
                inputSchema={
                    "type": "object",
                    "required": ["text"],
                    "properties": {
                        "text": {"type": "string", "description": "Message text"},
                        "chat_id": {
                            "type": ["string", "number"],
                            "description": "Target chat ID (user/group/channel). Falls back to TELEGRAM_CHAT_ID if omitted.",
                        },
                        "disable_notification": {
                            "type": "boolean",
                            "description": "Send silently (no sound) if true",
                        },
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
            # NOTE: use _send as documented in the SDK; logs go to stderr.
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
        # stdio transport; recommended for local processes (per MCP docs)
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as streams:
                await app.run(streams[0], streams[1], app.create_initialization_options())

        anyio.run(arun)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
