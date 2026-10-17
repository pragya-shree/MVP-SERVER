"""End-to-end tests for MCPAgent executing natural language requests against live API."""

import asyncio
from pathlib import Path
import pytest
import uvicorn
import threading
import time

from agent.agent import MCPAgent
from agent.client import MCPClient
from backend.generator import generate_mcp_server, parse_openapi
from demo_api.app import app
from demo_api.repository import repository


@pytest.fixture(scope="module")
def e2e_demo_server():
    """Start background FastAPI Demo server on dynamic port."""
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

    while not server.started:
        time.sleep(0.05)

    port = server.servers[0].sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    yield url

    server.should_exit = True
    thread.join(timeout=3.0)


@pytest.fixture(scope="module")
def e2e_server_script(tmp_path_factory: pytest.TempPathFactory, e2e_demo_server: str) -> Path:
    """Generate MCP server package targeting the test demo server."""
    out_dir = tmp_path_factory.mktemp("agent_e2e_pkg")
    spec = app.openapi()
    api = parse_openapi(spec)
    res = generate_mcp_server(
        api=api,
        output_dir=out_dir,
        package_name="agent_e2e_pkg",
        base_url=e2e_demo_server,
        overwrite=True,
    )
    return res.output_dir / "server.py"


@pytest.fixture(autouse=True)
def reset_db_state():
    """Reset demo database before each test run."""
    repository.reset()
    yield
    repository.reset()


@pytest.mark.asyncio
async def test_agent_e2e_query_and_create(
    e2e_server_script: Path, e2e_demo_server: str
) -> None:
    """Verify natural language querying, task retrieval, and task creation."""
    client = MCPClient(
        server_script=e2e_server_script,
        env={"TARGET_BASE_URL": e2e_demo_server},
    )
    async with client:
        agent = MCPAgent(client=client)

        # 1. Query pending tasks
        res_list = await agent.execute("Show me all pending tasks")
        assert res_list.success is True
        assert len(res_list.tool_invocations) == 1
        assert res_list.tool_invocations[0]["tool_name"] == "list_tasks"
        assert len(res_list.data["data"]) == 2

        # 2. Retrieve specific task
        res_get = await agent.execute("Find task t-1")
        assert res_get.success is True
        assert res_get.tool_invocations[0]["tool_name"] == "get_task_by_id"
        assert res_get.data["data"]["id"] == "t-1"

        # 3. Create a new task
        res_create = await agent.execute(
            "Create a task called E2E Agent Task with priority urgent"
        )
        assert res_create.success is True
        assert res_create.tool_invocations[0]["tool_name"] == "create_task"
        created_id = res_create.data["data"]["id"]
        assert created_id == "t-5"
        assert res_create.data["data"]["title"] == "E2E Agent Task"

        # 4. Confirm newly created task can be retrieved
        res_verify = await agent.execute(f"Find task {created_id}")
        assert res_verify.success is True
        assert res_verify.data["data"]["title"] == "E2E Agent Task"


@pytest.mark.asyncio
async def test_agent_e2e_delete_confirmation_workflow(
    e2e_server_script: Path, e2e_demo_server: str
) -> None:
    """Verify safety guard on DELETE: requires confirmation before actual removal."""
    client = MCPClient(
        server_script=e2e_server_script,
        env={"TARGET_BASE_URL": e2e_demo_server},
    )
    async with client:
        agent = MCPAgent(client=client)

        # Step 1: Attempt deletion without confirmation -> BLOCKED
        res_unconfirmed = await agent.execute("Delete task t-2", confirm_destructive=False)
        assert res_unconfirmed.success is False
        assert res_unconfirmed.requires_confirmation is True
        assert len(res_unconfirmed.tool_invocations) == 0  # No tool was executed!
        assert "t-2" in res_unconfirmed.message

        # Verify task t-2 is still present in database
        res_check = await agent.execute("Find task t-2")
        assert res_check.success is True
        assert res_check.data["data"]["id"] == "t-2"

        # Step 2: Attempt deletion WITH explicit confirmation -> EXECUTED
        res_confirmed = await agent.execute("Delete task t-2", confirm_destructive=True)
        assert res_confirmed.success is True
        assert res_confirmed.requires_confirmation is False
        assert len(res_confirmed.tool_invocations) == 1
        assert res_confirmed.tool_invocations[0]["tool_name"] == "delete_task"

        # Step 3: Verify task t-2 is now deleted (subsequent GET returns 404 error)
        res_after = await agent.execute("Find task t-2")
        assert res_after.success is False
        assert res_after.tool_invocations[0]["status_code"] == 404


@pytest.mark.asyncio
async def test_agent_e2e_clarifications_and_unsupported(
    e2e_server_script: Path, e2e_demo_server: str
) -> None:
    """Verify clarification for missing args and rejection of unsupported queries."""
    client = MCPClient(
        server_script=e2e_server_script,
        env={"TARGET_BASE_URL": e2e_demo_server},
    )
    async with client:
        agent = MCPAgent(client=client)

        # Missing required title
        res_clarify = await agent.execute("Create a task")
        assert res_clarify.success is False
        assert "title" in res_clarify.message.lower()
        assert len(res_clarify.tool_invocations) == 0

        # Unsupported query
        res_unsupported = await agent.execute("What is the capital of France?")
        assert res_unsupported.success is False
        assert "could not map" in res_unsupported.message.lower()
        assert len(res_unsupported.tool_invocations) == 0
