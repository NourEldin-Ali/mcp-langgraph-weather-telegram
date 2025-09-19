from collections.abc import Sequence
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
        raise ValueError('TELEGRAM_BOT_TOKEN is not set')

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: Dict[str, Any] = {
        'chat_id': chat_id,
        'text': text,
        'disable_notification': disable_notification,
    }

    async with create_mcp_http_client(headers={'User-Agent': 'MCP Telegram Server'}) as client:
        resp = await client.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return [types.TextContent(type='text', text=data if isinstance(data, str) else resp.text)]


async def telegram_get_updates(
    bot_token: str,
    offset: int | None = None,
    timeout: int = 0,
    allowed_updates: Sequence[str] | None = None,
) -> list[types.ContentBlock]:
    if not bot_token:
        raise ValueError('TELEGRAM_BOT_TOKEN is not set')

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    payload: Dict[str, Any] = {}
    if offset is not None:
        payload['offset'] = offset
    if timeout:
        payload['timeout'] = timeout
    if allowed_updates:
        payload['allowed_updates'] = list(allowed_updates)

    request_timeout = max(timeout + 5, 30)
    async with create_mcp_http_client(headers={'User-Agent': 'MCP Telegram Server'}) as client:
        resp = await client.post(url, json=payload, timeout=request_timeout)
        resp.raise_for_status()
        return [types.TextContent(type='text', text=resp.text)]


@click.command()
@click.option('--port', default=8010, help='Port to listen on for SSE')
@click.option(
    '--transport',
    type=click.Choice(['stdio', 'sse']),
    default='stdio',
    help='Transport type',
)
def main(port: int, transport: str) -> int:
    import os

    app = Server('telegram-mcp-server')
    BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    DEFAULT_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        if name == 'send_message':
            if 'text' not in arguments:
                raise ValueError("Missing required argument 'text'")

            text: str = arguments['text']
            chat_id = arguments.get('chat_id', DEFAULT_CHAT_ID)
            if not chat_id:
                raise ValueError('chat_id missing (and TELEGRAM_CHAT_ID is not set)')

            disable_notification = bool(arguments.get('disable_notification', False))
            return await telegram_send_message(
                bot_token=BOT_TOKEN or '',
                text=text,
                chat_id=chat_id,
                disable_notification=disable_notification,
            )

        if name == 'get_updates':
            offset_raw = arguments.get('offset')
            offset: int | None = None
            if offset_raw is not None:
                try:
                    offset = int(offset_raw)
                except (TypeError, ValueError) as exc:
                    raise ValueError('offset must be an integer') from exc

            timeout_raw = arguments.get('timeout', 0)
            try:
                timeout = int(timeout_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError('timeout must be an integer') from exc

            allowed_updates_arg = arguments.get('allowed_updates')
            allowed_updates_seq: Sequence[str] | None = None
            if allowed_updates_arg is not None:
                if isinstance(allowed_updates_arg, str):
                    raise ValueError('allowed_updates must be a sequence of strings')
                if not isinstance(allowed_updates_arg, Sequence):
                    raise ValueError('allowed_updates must be a sequence of strings')
                allowed_updates_seq = list(allowed_updates_arg)
                if not all(isinstance(item, str) for item in allowed_updates_seq):
                    raise ValueError('allowed_updates entries must be strings')

            return await telegram_get_updates(
                bot_token=BOT_TOKEN or '',
                offset=offset,
                timeout=timeout,
                allowed_updates=allowed_updates_seq,
            )

        raise ValueError(f'Unknown tool: {name}')

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name='send_message',
                title='Telegram: Send Message',
                description='Send a text message via Telegram Bot API using a bot token',
                inputSchema={
                    'type': 'object',
                    'required': ['text'],
                    'properties': {
                        'text': {'type': 'string', 'description': 'Message text'},
                        'chat_id': {
                            'type': ['string', 'number'],
                            'description': 'Target chat ID (user/group/channel). Falls back to TELEGRAM_CHAT_ID if omitted.',
                        },
                        'disable_notification': {
                            'type': 'boolean',
                            'description': 'Send silently (no sound) if true',
                        },
                    },
                },
            ),
            types.Tool(
                name='get_updates',
                title='Telegram: Fetch Updates',
                description='Fetch incoming updates (messages) via Telegram long polling.',
                inputSchema={
                    'type': 'object',
                    'properties': {
                        'offset': {
                            'type': ['integer', 'string'],
                            'description': 'Return updates with ID >= offset (pass last_update_id + 1).',
                        },
                        'timeout': {
                            'type': ['integer', 'string'],
                            'description': 'Long polling wait time in seconds (default 0).',
                        },
                        'allowed_updates': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': 'Restrict to specific update types (see Telegram Bot API).',
                        },
                    },
                },
            ),
        ]

    if transport == 'sse':
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Mount, Route

        sse = SseServerTransport('/messages/')

        async def handle_sse(request: Request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:  # type: ignore
                await app.run(streams[0], streams[1], app.create_initialization_options())
            return Response()

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route('/sse', endpoint=handle_sse, methods=['GET']),
                Mount('/messages/', app=sse.handle_post_message),
            ],
        )

        import uvicorn

        uvicorn.run(starlette_app, host='127.0.0.1', port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as streams:
                await app.run(streams[0], streams[1], app.create_initialization_options())

        anyio.run(arun)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
