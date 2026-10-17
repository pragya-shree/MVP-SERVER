"""End-to-end integration tests using official MCP stdio client and local HTTP target server."""

import asyncio
import http.server
import json
from pathlib import Path
import sys
import threading
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.generator import generate_mcp_server, parse_openapi_file

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


class LocalAPITestHandler(http.server.BaseHTTPRequestHandler):
    """Local test HTTP server simulating API target endpoints."""

    def do_GET(self) -> None:
        if "/tasks/error-404" in self.path:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Task not found"}).encode("utf-8"))
        elif "/tasks/task-999" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({
                    "id": "task-999",
                    "title": "Fetched Task",
                    "status": "todo",
                    "priority": "medium",
                }).encode("utf-8")
            )
        elif "/tasks" in self.path:
            # Query param verification
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps([
                    {
                        "id": "1",
                        "title": "List Task",
                        "status": "todo",
                        "priority": "low",
                    }
                ]).encode("utf-8")
            )
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({
                "id": "created-101",
                "title": body.get("title", ""),
                "priority": body.get("priority", "medium"),
                "status": "todo",
            }).encode("utf-8")
        )

    def log_message(self, format: str, *args: object) -> None:
        """Suppress stdout log messages during test execution."""
        pass


@pytest.fixture(scope="module")
def local_http_server():
    """Start a real local HTTP server on an ephemeral port."""
    server = http.server.HTTPServer(("127.0.0.1", 0), LocalAPITestHandler)
    port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    yield f"http://127.0.0.1:{port}"

    server.shutdown()
    server.server_close()


@pytest.mark.asyncio
async def test_e2e_stdio_mcp_client_and_tool_invocations(tmp_path: Path, local_http_server: str) -> None:
    """Full E2E test launching generated server as stdio subprocess and invoking MCP tools."""
    spec_path = EXAMPLES_DIR / "task_management_api.yaml"
    api = parse_openapi_file(spec_path)

    # 1. Generate MCP server targeting our local HTTP server
    res = generate_mcp_server(
        api=api,
        output_dir=tmp_path,
        package_name="e2e_pkg",
        base_url=local_http_server,
    )
    server_script = str((res.output_dir / "server.py").resolve())

    # 2. Configure stdio client parameters
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_script],
        env={"TARGET_BASE_URL": local_http_server},
    )

    # 3. Connect via official MCP SDK stdio client
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # MCP Handshake / Initialize
            init_result = await session.initialize()
            assert init_result.server_info.name == "e2e_pkg"

            # 4. Discover tools
            tools_result = await session.list_tools()
            tool_names = {t.name for t in tools_result.tools}
            assert "list_tasks" in tool_names
            assert "get_task_by_id" in tool_names
            assert "create_task" in tool_names
            assert "delete_task" in tool_names
            assert "get_projects_by_project_id_tasks" in tool_names

            # 5. Invoke GET tool with query parameters
            get_query_res = await session.call_tool("list_tasks", {"status": "todo", "limit": 5})
            assert not get_query_res.is_error
            get_query_data = json.loads(get_query_res.content[0].text)
            assert get_query_data["status_code"] == 200
            assert get_query_data["data"][0]["title"] == "List Task"

            # 6. Invoke GET tool with path parameter
            get_path_res = await session.call_tool("get_task_by_id", {"task_id": "task-999"})
            assert not get_path_res.is_error
            get_path_data = json.loads(get_path_res.content[0].text)
            assert get_path_data["status_code"] == 200
            assert get_path_data["data"]["id"] == "task-999"
            assert get_path_data["data"]["title"] == "Fetched Task"

            # 7. Invoke POST tool with JSON request body
            post_res = await session.call_tool(
                "create_task",
                {"title": "E2E Live Task", "priority": "urgent"}
            )
            assert not post_res.is_error
            post_data = json.loads(post_res.content[0].text)
            assert post_data["status_code"] == 201
            assert post_data["data"]["id"] == "created-101"
            assert post_data["data"]["title"] == "E2E Live Task"
            assert post_data["data"]["priority"] == "urgent"

            # 8. Invoke tool triggering HTTP error (404)
            err_res = await session.call_tool("get_task_by_id", {"task_id": "error-404"})
            err_data = json.loads(err_res.content[0].text)
            assert err_data["error"] is True
            assert err_data["status_code"] == 404
            assert err_data["detail"]["error"] == "Task not found"


@pytest.mark.asyncio
async def test_e2e_read_only_stdio_client(tmp_path: Path, local_http_server: str) -> None:
    """Verify live read-only server via stdio client exposes ONLY GET tools."""
    spec_path = EXAMPLES_DIR / "task_management_api.yaml"
    api = parse_openapi_file(spec_path)

    # Generate in read-only mode
    res = generate_mcp_server(
        api=api,
        output_dir=tmp_path,
        package_name="e2e_ro_pkg",
        base_url=local_http_server,
        read_only=True,
    )
    server_script = str((res.output_dir / "server.py").resolve())

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_script],
        env={"TARGET_BASE_URL": local_http_server},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tool_names = {t.name for t in tools_result.tools}

            # Exactly the 3 GET operations
            assert tool_names == {"list_tasks", "get_task_by_id", "get_projects_by_project_id_tasks"}
            assert "create_task" not in tool_names
            assert "delete_task" not in tool_names
