"""Official MCP stdio client wrapper for connecting to generated MCP servers."""

import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import sys
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.exceptions import (
    MCPClientError,
    MCPConnectionError,
    MCPTimeoutError,
    MCPToolExecutionError,
    MCPToolNotFoundError,
)
from agent.models import MCPToolDefinition, MCPToolResult


class MCPClient:
    """Async MCP client managing a stdio subprocess connection to an MCP server."""

    def __init__(
        self,
        server_script: str | Path,
        command: str = sys.executable,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str | Path] = None,
        timeout: float = 30.0,
    ) -> None:
        self.server_script = Path(server_script).resolve()
        self.command = command
        self.args = args or [str(self.server_script)]
        self.env = env
        self.cwd = str(cwd) if cwd else None
        self.timeout = timeout

        self._exit_stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        self._tools: dict[str, MCPToolDefinition] = {}
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Return True if an active MCP session is established."""
        return self._connected and self._session is not None

    async def connect(self) -> None:
        """Launch stdio subprocess and complete MCP initialization handshake."""
        if self.is_connected:
            return

        if not self.server_script.exists():
            raise MCPConnectionError(f"Server script not found: {self.server_script}")

        # Prepare environment variables, inheriting current PATH and system variables
        merged_env = dict(os.environ)
        if self.env:
            merged_env.update(self.env)

        # Force unbuffered Python stdout/stderr for reliable stdio piping
        merged_env["PYTHONUNBUFFERED"] = "1"

        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=merged_env,
            cwd=self.cwd,
        )

        self._exit_stack = AsyncExitStack()
        try:
            read_stream, write_stream = await asyncio.wait_for(
                self._exit_stack.enter_async_context(stdio_client(params)),
                timeout=self.timeout,
            )
            session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await asyncio.wait_for(session.initialize(), timeout=self.timeout)
            self._session = session
            self._connected = True
        except asyncio.TimeoutError as exc:
            await self.close()
            raise MCPTimeoutError(
                f"Timed out connecting to MCP server after {self.timeout}s"
            ) from exc
        except Exception as exc:
            await self.close()
            raise MCPConnectionError(f"Failed to connect to MCP server: {exc}") from exc

    async def close(self) -> None:
        """Cleanly close MCP session and terminate child subprocess."""
        self._connected = False
        self._session = None
        self._tools.clear()
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
            finally:
                self._exit_stack = None

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def list_tools(self, force_refresh: bool = False) -> list[MCPToolDefinition]:
        """Discover tools exposed by the MCP server."""
        if not self.is_connected:
            await self.connect()

        assert self._session is not None

        if self._tools and not force_refresh:
            return list(self._tools.values())

        try:
            tools_response = await asyncio.wait_for(
                self._session.list_tools(),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise MCPTimeoutError(f"Timed out listing tools after {self.timeout}s") from exc
        except Exception as exc:
            raise MCPClientError(f"Failed to list tools from MCP server: {exc}") from exc

        self._tools = {}
        for tool in tools_response.tools:
            # MCP SDK returns tool with name, description, and input_schema
            schema = getattr(tool, "input_schema", getattr(tool, "inputSchema", {}))
            tool_def = MCPToolDefinition(
                name=tool.name,
                description=tool.description or "",
                input_schema=schema or {},
                title=getattr(tool, "title", None),
            )
            self._tools[tool.name] = tool_def

        return list(self._tools.values())

    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> MCPToolResult:
        """Invoke a tool on the MCP server with validated arguments."""
        if not self.is_connected:
            await self.connect()

        assert self._session is not None

        # Verify tool is known
        if not self._tools:
            await self.list_tools()

        if tool_name not in self._tools:
            raise MCPToolNotFoundError(
                f"Tool '{tool_name}' is not exposed by MCP server. Available: {list(self._tools.keys())}"
            )

        call_args = arguments or {}

        try:
            res = await asyncio.wait_for(
                self._session.call_tool(tool_name, call_args),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise MCPTimeoutError(
                f"Timed out executing tool '{tool_name}' after {self.timeout}s"
            ) from exc
        except Exception as exc:
            raise MCPToolExecutionError(
                f"Protocol error executing tool '{tool_name}': {exc}"
            ) from exc

        # Extract content text from tool result
        content_text = ""
        if res.content:
            content_text = "\n".join(
                getattr(c, "text", str(c)) for c in res.content
            )

        # Parse JSON if possible to extract status code and structured response
        raw_data = None
        status_code = None
        is_error = bool(res.is_error)

        try:
            parsed = json.loads(content_text)
            raw_data = parsed
            if isinstance(parsed, dict):
                status_code = parsed.get("status_code")
                if parsed.get("error") is True:
                    is_error = True
        except Exception:
            raw_data = content_text

        return MCPToolResult(
            tool_name=tool_name,
            is_error=is_error,
            content=content_text,
            raw_data=raw_data,
            status_code=status_code,
        )
