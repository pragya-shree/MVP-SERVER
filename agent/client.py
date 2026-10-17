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
        self._in_process_mode = False
        self._ops_metadata: dict[str, Any] = {}

    @property
    def is_connected(self) -> bool:
        """Return True if an active MCP session is established."""
        return self._connected and (self._session is not None or self._in_process_mode)

    def _load_in_process_tools(self) -> None:
        """Extract tool definitions and operation metadata for in-process execution."""
        self._ops_metadata = {}
        self._tools = {}

        # 1. Try reading OPERATIONS_METADATA directly from server_script
        if self.server_script.exists():
            try:
                content = self.server_script.read_text(encoding="utf-8")
                match = re.search(
                    r'OPERATIONS_METADATA:\s*dict\[str,\s*Any\]\s*=\s*json\.loads\(r"""(.*?)"""\)',
                    content,
                    re.DOTALL,
                )
                if match:
                    self._ops_metadata = json.loads(match.group(1))
            except Exception:
                pass

        # 2. Try reading from metadata.json in storage directory
        if not self._ops_metadata:
            for candidate in (
                self.server_script.parent / "metadata.json",
                self.server_script.parent.parent / "metadata.json",
            ):
                if candidate.exists():
                    try:
                        meta = json.loads(candidate.read_text(encoding="utf-8"))
                        for t in meta.get("tools", []):
                            name = t.get("name")
                            if name:
                                self._ops_metadata[name] = {
                                    "tool_name": name,
                                    "method": t.get("method", "GET"),
                                    "path": t.get("path", "/"),
                                    "description": t.get("description", ""),
                                    "input_schema": t.get("input_schema", {}),
                                    "path_params": [
                                        k
                                        for k, v in t.get("input_schema", {}).get("properties", {}).items()
                                        if f"{{{k}}}" in t.get("path", "")
                                    ],
                                    "query_params": [],
                                    "header_params": [],
                                    "body_properties": [],
                                    "has_body": t.get("method", "GET").upper() in ("POST", "PUT", "PATCH"),
                                }
                    except Exception:
                        pass
                    if self._ops_metadata:
                        break

        # 3. Fallback for demo_task_mcp
        if not self._ops_metadata and ("demo" in str(self.server_script).lower()):
            try:
                from demo_api.app import app as demo_app
                from backend.generator.parser import parse_openapi
                from backend.generator.generator import build_operation_input_schema, build_tool_description
                api_model = parse_openapi(demo_app.openapi())
                for op in api_model.operations:
                    body_props = []
                    if op.request_body and op.request_body.schema_ and op.request_body.schema_.get("type") == "object":
                        body_props = list(op.request_body.schema_.get("properties", {}).keys())

                    self._ops_metadata[op.tool_name] = {
                        "tool_name": op.tool_name,
                        "operation_id": op.operation_id,
                        "method": op.method.upper(),
                        "path": op.path,
                        "summary": op.summary,
                        "description": build_tool_description(op),
                        "path_params": [p.name for p in op.path_parameters],
                        "query_params": [p.name for p in op.query_parameters],
                        "header_params": [p.name for p in op.header_parameters],
                        "body_properties": body_props,
                        "has_body": bool(op.request_body),
                        "body_required": bool(op.request_body.required) if op.request_body else False,
                        "security": op.security,
                        "input_schema": build_operation_input_schema(op),
                    }
            except Exception:
                pass

        for tool_name, op_meta in self._ops_metadata.items():
            self._tools[tool_name] = MCPToolDefinition(
                name=tool_name,
                description=op_meta.get("description", ""),
                input_schema=op_meta.get("input_schema", {}),
                title=op_meta.get("summary") or tool_name,
            )

    async def connect(self) -> None:
        """Launch stdio subprocess or fallback cleanly to in-process execution on serverless runtimes."""
        if self.is_connected:
            return

        is_serverless = bool(
            os.getenv("VERCEL") == "1"
            or os.getenv("VERCEL_ENV")
            or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        )

        if not self.server_script.exists():
            if is_serverless and ("demo" in str(self.server_script).lower()):
                self._load_in_process_tools()
                if self._tools:
                    self._in_process_mode = True
                    self._connected = True
                    return
            raise MCPConnectionError(f"Server script not found: {self.server_script}")

        if is_serverless:
            self._load_in_process_tools()
            self._in_process_mode = True
            self._connected = True
            return

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
        """Cleanly close MCP session and terminate child subprocess or in-process session."""
        self._connected = False
        self._session = None
        self._tools.clear()
        self._in_process_mode = False
        self._ops_metadata.clear()
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

        if self._in_process_mode:
            if not self._tools or force_refresh:
                self._load_in_process_tools()
            return list(self._tools.values())

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

        # In-process execution handling
        if self._in_process_mode:
            if not self._tools:
                await self.list_tools()

            if tool_name not in self._tools:
                raise MCPToolNotFoundError(
                    f"Tool '{tool_name}' is not exposed by MCP server. Available: {list(self._tools.keys())}"
                )

            op_meta = self._ops_metadata.get(tool_name)
            if not op_meta:
                raise MCPToolNotFoundError(f"Operation metadata for tool '{tool_name}' not found.")

            from backend.generator.executor import InProcessConfig, execute_tool_in_process

            config = InProcessConfig.from_env(self.env)
            call_args = dict(arguments or {})

            res = await execute_tool_in_process(op_meta, call_args, config)

            is_error = bool(res.get("error", False))
            status_code = res.get("status_code")
            raw_data = res

            content_text = json.dumps(raw_data) if isinstance(raw_data, (dict, list)) else str(raw_data)
            return MCPToolResult(
                tool_name=tool_name,
                is_error=is_error,
                content=content_text,
                raw_data=raw_data,
                status_code=status_code,
            )

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

