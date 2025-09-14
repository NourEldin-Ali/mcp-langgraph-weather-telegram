import os, json, sys
from contextlib import AsyncExitStack
from typing import Any, Dict, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

class MCPServersManager:
    def __init__(self, servers_config_path: str = "servers_config.json"):
        self.config_path = servers_config_path
        self.stack: Optional[AsyncExitStack] = None
        self.sessions: dict[str, ClientSession] = {}

    def _load_config(self) -> dict[str, Any]:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _resolve_env(self, env_spec: Dict[str, Any] | None) -> Dict[str, str] | None:
        if not env_spec:
            return None
        # ensure .env is loaded so expandvars can find values
        load_dotenv()
        resolved: Dict[str, str] = {}
        for k, v in env_spec.items():
            s = str(v) if not isinstance(v, str) else v
            # Expand ${VAR} using process env
            s = os.path.expandvars(s)
            resolved[k] = s
        # Merge with current environment
        return {**os.environ, **resolved}

    async def __aenter__(self) -> "MCPServersManager":
        cfg = self._load_config()
        debug = os.getenv("AGENT_THINK_DEBUG")
        if debug:
            try:
                print(f"[mcp] Loading servers from {self.config_path}")
                print(f"[mcp] Server entries: {list((cfg.get('mcpServers') or {}).keys())}")
            except Exception:
                pass
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()

        for name, scfg in cfg.get("mcpServers", {}).items():
            command = scfg["command"]
            # Prefer current interpreter to ensure dependencies are available
            if command in ("python", "python3", "py"):
                command = sys.executable or command
            args = scfg.get("args", [])
            env = self._resolve_env(scfg.get("env")) or {}
            # Ensure reliable stdio behavior
            env.setdefault("PYTHONUNBUFFERED", "1")
            env.setdefault("PYTHONIOENCODING", "utf-8")

            params = StdioServerParameters(command=command, args=args, env=env)
            try:
                read, write = await self.stack.enter_async_context(stdio_client(params))
                session = await self.stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self.sessions[name] = session
                if debug:
                    try:
                        print(f"[mcp] Initialized '{name}' via {command} {' '.join(args)}")
                    except Exception:
                        pass
            except Exception as e:
                if debug:
                    try:
                        print(f"[mcp] Failed to init '{name}': {e}")
                    except Exception:
                        pass
        return self

    async def __aexit__(self, et, ev, tb):
        if self.stack:
            await self.stack.aclose()
        self.sessions.clear()

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        session = self.sessions.get(server_name)
        if not session:
            raise RuntimeError(f"MCP server '{server_name}' is not initialized")
        return await session.call_tool(tool_name, arguments)
