from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_think.app import build_graph
from mcp_client.mcp_manager import MCPServersManager

LOGGER = logging.getLogger(__name__)


def _decode_text_blocks(blocks: Any) -> Optional[str]:
    if hasattr(blocks, 'content'):
        blocks = getattr(blocks, 'content')
    if not isinstance(blocks, list):
        return None
    for block in blocks:
        text = getattr(block, 'text', None)
        if isinstance(text, str):
            return text
    return None

def _json_from_blocks(blocks: Any) -> Dict[str, Any]:
    raw = _decode_text_blocks(blocks)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        LOGGER.debug('Could not parse JSON from Telegram update payload: %s', raw)
        return {}


def _extract_message(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ('message', 'channel_post', 'edited_message', 'edited_channel_post'):
        msg = update.get(key)
        if msg:
            return msg
    return None



def _sender_label(msg: Dict[str, Any]) -> str:
    user = msg.get('from') or {}
    username = user.get('username')
    if username:
        return f'@{username}'
    first = user.get('first_name') or ''
    last = user.get('last_name') or ''
    label = ' '.join(part for part in (first, last) if part)
    return label.strip() or 'unknown user'


def _summarize_result(messages: Any) -> str:
    if not isinstance(messages, list):
        return ''
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            try:
                return str(msg.content)
            except Exception:  # pragma: no cover - defensive
                return ''
        if isinstance(msg, ToolMessage):  # include final tool observation
            try:
                return str(msg.content)
            except Exception:
                return ''
    return ''


async def _process_update(app, update: Dict[str, Any]) -> None:
    message = _extract_message(update)
    if not message:
        return

    if message.get('from', {}).get('is_bot'):
        return

    text = message.get('text') or message.get('caption')
    if not text:
        return

    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    if chat_id is None:
        return

    sender = _sender_label(message)
    prompt = (
        f'Telegram message from {sender} in chat {chat_id}: "{text}".\n'
        'Figure out the requested weather tasks. Call get_weather once per location before sending any Telegram reply.\n'
        'Send responses back using send_telegram with the same chat_id. If the request is unclear or out of scope, send a polite clarification.'
    )

    init_state = {
        'messages': [
            HumanMessage(content=prompt),
            HumanMessage(content=f'Use this Telegram chat_id: {chat_id}'),
        ],
        'weather_results': [],
        'loops': 0,
    }

    result = await app.ainvoke(init_state)
    summary = _summarize_result(result.get('messages'))
    if summary:
        LOGGER.info('Update %s handled. Agent summary: %s', update.get('update_id'), summary)
    else:
        LOGGER.info('Update %s handled.', update.get('update_id'))


async def run_telegram_listener(timeout: int = 20, idle_sleep: float = 1.0) -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')

    offset: Optional[int] = None
    LOGGER.info('Starting Telegram listener (timeout=%s, idle_sleep=%s)', timeout, idle_sleep)

    async with MCPServersManager('mcp_client/servers_config.json') as mcp_mgr:
        app = build_graph(mcp_mgr)

        while True:
            args: Dict[str, Any] = {'timeout': timeout}
            if offset is not None:
                args['offset'] = offset

            try:
                blocks = await mcp_mgr.call_tool('telegram', 'get_updates', args)
            except Exception as exc:
                LOGGER.exception('Failed to fetch Telegram updates: %s', exc)
                await asyncio.sleep(idle_sleep)
                continue

            payload = _json_from_blocks(blocks)
            updates = payload.get('result') or []
            if not isinstance(updates, list):
                updates = []

            if not payload.get('ok', True):
                LOGGER.warning('Telegram getUpdates returned error payload: %s', payload)
                await asyncio.sleep(idle_sleep)
                continue

            for update in updates:
                if not isinstance(update, dict):
                    continue

                update_id = update.get('update_id')
                if isinstance(update_id, int):
                    next_offset = update_id + 1
                    if offset is None or next_offset > offset:
                        offset = next_offset

                try:
                    await _process_update(app, update)
                except Exception as exc:  # pragma: no cover - keep loop alive
                    LOGGER.exception('Error while processing update %s: %s', update.get('update_id'), exc)

            if not updates:
                await asyncio.sleep(idle_sleep)


def main() -> None:
    parser = argparse.ArgumentParser(description='Telegram polling loop for Agent Think.')
    parser.add_argument('--timeout', type=int, default=20, help='Long polling timeout (seconds).')
    parser.add_argument('--idle-sleep', type=float, default=1.0, help='Delay when no updates are received.')
    args = parser.parse_args()

    try:
        asyncio.run(run_telegram_listener(timeout=args.timeout, idle_sleep=args.idle_sleep))
    except KeyboardInterrupt:
        LOGGER.info('Telegram listener stopped by user.')


if __name__ == '__main__':
    main()

