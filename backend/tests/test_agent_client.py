"""Tests for agent/client.py using official MCP stdio client and live HTTP server."""

import asyncio
from pathlib import Path
import pytest
import uvicorn
import threading
import time

from agent.client import MCPClient
from agent.exceptions import MCPConnectionError, MCPToolNotFoundError
from backend.generator import generate_mcp_server, parse_openapi
from demo_api.app import app
from demo_api.repository import repository


@pytest.fixture(scope="module")
def live_demo_server():
    """Start the Demo API on an ephemeral local port."""
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to bind and start
    while not server.started:
        time.sleep(0.05)

    # Get bound port
    port = server.servers[0].sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    yield url

    server.should_exit = True
    thread.join(timeout=3.0)


@pytest.fixture(scope="module")
def generated_server_script(tmp_path_factory: pytest.TempPathFactory, live_demo_server: str) -> Path:
    """Generate an MCP server package targeting the live demo server."""
    out_dir = tmp_path_factory.mktemp("client_test_mcp")
    spec = app.openapi()
    api = parse_openapi(spec)
    result = generate_mcp_server(
        api=api,
        output_dir=out_dir,
        package_name="client_test_mcp",
        base_url=live_demo_server,
        overwrite=True,
    )
    return result.output_dir / "server.py"


@pytest.fixture(autouse=True)
def reset_db_state():
    """Reset repository before each test."""
    repository.reset()
    yield
    repository.reset()


@pytest.mark.asyncio
async def test_mcp_client_lifecycle_and_discovery(
    generated_server_script: Path, live_demo_server: str
) -> None:
    """Verify MCPClient connects, discovers all tools, and closes cleanly."""
    client = MCPClient(
        server_script=generated_server_script,
        env={"TARGET_BASE_URL": live_demo_server},
    )

    assert not client.is_connected
    await client.connect()
    assert client.is_connected

    tools = await client.list_tools()
    tool_names = {t.name for t in tools}
    assert "list_tasks" in tool_names
    assert "create_task" in tool_names
    assert "get_task_by_id" in tool_names
    assert "update_task" in tool_names
    assert "delete_task" in tool_names
    assert "get_task_summary" in tool_names

    # Check input_schema preserved
    create_tool = next(t for t in tools if t.name == "create_task")
    assert "title" in create_tool.input_schema.get("properties", {})

    await client.close()
    assert not client.is_connected


@pytest.mark.asyncio
async def test_mcp_client_tool_calls(
    generated_server_script: Path, live_demo_server: str
) -> None:
    """Verify invoking GET, POST, PATCH, and DELETE tools through MCPClient."""
    async with MCPClient(
        server_script=generated_server_script,
        env={"TARGET_BASE_URL": live_demo_server},
    ) as client:
        # 1. GET with query filter
        res = await client.call_tool("list_tasks", {"status": "pending"})
        assert not res.is_error
        assert res.status_code == 200
        tasks = res.raw_data.get("data", [])
        assert len(tasks) == 2

        # 2. POST to create task
        res_create = await client.call_tool(
            "create_task",
            {"title": "Automated Client Task", "priority": "urgent"},
        )
        assert not res_create.is_error
        assert res_create.status_code == 201
        created = res_create.raw_data.get("data", {})
        created_id = created.get("id")
        assert created_id == "t-5"

        # 3. PATCH to update task
        res_patch = await client.call_tool(
            "update_task",
            {"task_id": created_id, "status": "completed"},
        )
        assert not res_patch.is_error
        assert res_patch.status_code == 200
        updated = res_patch.raw_data.get("data", {})
        assert updated.get("status") == "completed"

        # 4. DELETE task
        res_del = await client.call_tool("delete_task", {"task_id": created_id})
        assert not res_del.is_error
        assert res_del.status_code == 204

        # 5. Verify 404 for deleted task
        res_get = await client.call_tool("get_task_by_id", {"task_id": created_id})
        assert res_get.is_error
        assert res_get.status_code == 404


@pytest.mark.asyncio
async def test_mcp_client_unknown_tool(
    generated_server_script: Path, live_demo_server: str
) -> None:
    """Verify calling an unregistered tool raises MCPToolNotFoundError."""
    async with MCPClient(
        server_script=generated_server_script,
        env={"TARGET_BASE_URL": live_demo_server},
    ) as client:
        with pytest.raises(MCPToolNotFoundError) as exc_info:
            await client.call_tool("nonexistent_tool_xyz", {})
        assert "nonexistent_tool_xyz" in str(exc_info.value)


@pytest.mark.asyncio
async def test_mcp_client_nonexistent_script() -> None:
    """Verify connecting to a nonexistent script raises MCPConnectionError."""
    client = MCPClient(server_script=Path("nonexistent/path/server.py"))
    with pytest.raises(MCPConnectionError) as exc_info:
        await client.connect()
    assert "not found" in str(exc_info.value).lower()
