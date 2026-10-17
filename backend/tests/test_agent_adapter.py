import os
import shutil
import threading
import time
import pytest
import uvicorn
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.v1.agent import GENERATED_DIR, ensure_demo_server_generated
from demo_api.app import app as demo_app
from demo_api.repository import repository as demo_repo


@pytest.fixture(scope="module", autouse=True)
def live_demo_server():
    """Start background FastAPI Demo server on dynamic port for MCP tool calls."""
    config = uvicorn.Config(
        app=demo_app,
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
    old_base = os.environ.get("DEMO_API_BASE_URL")
    os.environ["DEMO_API_BASE_URL"] = url

    if GENERATED_DIR.exists():
        shutil.rmtree(GENERATED_DIR, ignore_errors=True)
    ensure_demo_server_generated(base_url=url)

    yield url

    server.should_exit = True
    thread.join(timeout=3.0)
    if old_base is not None:
        os.environ["DEMO_API_BASE_URL"] = old_base
    else:
        os.environ.pop("DEMO_API_BASE_URL", None)


@pytest.fixture(autouse=True)
def reset_db_state():
    """Ensure tests run against a clean seed state."""
    demo_repo.reset()
    yield
    demo_repo.reset()


@pytest.fixture
def client() -> TestClient:
    """Test client fixture."""
    return TestClient(app)


def test_get_demo_spec(client: TestClient) -> None:
    """Verify /api/v1/demo/spec returns the bundled Task Management OpenAPI document."""
    resp = client.get("/api/v1/demo/spec")
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "task_management_api.yaml"
    assert "openapi: 3.0.3" in data["spec"]
    assert data["title"] == "Task Management API"
    assert data["operation_count"] == 5
    assert "default_base_url" in data


def test_get_agent_status(client: TestClient) -> None:
    """Verify /api/v1/agent/status returns readiness and task statistics."""
    resp = client.get("/api/v1/agent/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["service"] == "demo-task-management-agent"
    assert data["total_tasks"] == 4
    assert "counts_by_status" in data


def test_get_agent_tools(client: TestClient) -> None:
    """Verify /api/v1/agent/tools discovers tools from generated MCP server."""
    resp = client.get("/api/v1/agent/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert isinstance(tools, list)
    tool_names = {t["name"] for t in tools}
    assert "list_tasks" in tool_names
    assert "create_task" in tool_names
    assert "get_task_by_id" in tool_names
    assert "delete_task" in tool_names


def test_agent_execute_read_query(client: TestClient) -> None:
    """Verify /api/v1/agent/execute executes a safe read query."""
    resp = client.post(
        "/api/v1/agent/execute",
        json={"request": "Show me all pending tasks", "confirm_destructive": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["requires_confirmation"] is False
    assert len(data["tool_invocations"]) == 1
    assert data["tool_invocations"][0]["tool_name"] == "list_tasks"


def test_agent_execute_destructive_blocked_without_confirmation(client: TestClient) -> None:
    """Verify delete action is blocked when confirm_destructive is False."""
    resp = client.post(
        "/api/v1/agent/execute",
        json={"request": "Delete task t-3", "confirm_destructive": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["requires_confirmation"] is True
    assert len(data["tool_invocations"]) == 0
    assert "t-3" in data["message"]


def test_agent_execute_destructive_with_confirmation(client: TestClient) -> None:
    """Verify delete action succeeds when confirm_destructive is True."""
    resp = client.post(
        "/api/v1/agent/execute",
        json={"request": "Delete task t-3", "confirm_destructive": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["requires_confirmation"] is False
    assert len(data["tool_invocations"]) == 1
    assert data["tool_invocations"][0]["tool_name"] == "delete_task"

    # Confirm task was removed
    get_resp = client.post(
        "/api/v1/agent/execute",
        json={"request": "Find task t-3"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["success"] is False


def test_agent_reset_database(client: TestClient) -> None:
    """Verify /api/v1/agent/reset guards reset action behind confirmation."""
    # Unconfirmed reset
    resp_unconfirmed = client.post("/api/v1/agent/reset", json={"confirm": False})
    assert resp_unconfirmed.status_code == 200
    data_unconfirmed = resp_unconfirmed.json()
    assert data_unconfirmed["requires_confirmation"] is True
    assert data_unconfirmed["success"] is False

    # Confirmed reset
    resp_confirmed = client.post("/api/v1/agent/reset", json={"confirm": True})
    assert resp_confirmed.status_code == 200
    data_confirmed = resp_confirmed.json()
    assert data_confirmed["success"] is True
    assert data_confirmed["total_tasks"] == 4
