"""Comprehensive test suite verifying that all endpoints and features work on Vercel Serverless runtime without 503 errors."""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from demo_api.repository import repository as demo_repo


SAMPLE_SPEC = """openapi: 3.0.3
info:
  title: Serverless Test API
  version: 1.0.0
paths:
  /tasks:
    get:
      operationId: list_tasks
      summary: List tasks
      responses:
        '200':
          description: OK
    post:
      operationId: create_task
      summary: Create task
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [title]
              properties:
                title: { type: string }
      responses:
        '201':
          description: Created
"""


@pytest.fixture(autouse=True)
def setup_vercel_environment(monkeypatch, tmp_path):
    """Simulate Vercel serverless environment."""
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VERCEL_URL", "mvp-server-hb7arlxho-hello-99fc.vercel.app")
    storage_dir = tmp_path / "artifacts"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GENERATOR_STORAGE_DIR", str(storage_dir))
    demo_repo.reset()
    yield
    demo_repo.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_vercel_demo_spec_and_status(client: TestClient) -> None:
    """Verify demo spec and agent status return 200 with dynamic Vercel base URL."""
    spec_resp = client.get("/api/v1/demo/spec")
    assert spec_resp.status_code == 200
    spec_data = spec_resp.json()
    assert "mvp-server-hb7arlxho-hello-99fc.vercel.app" in spec_data["default_base_url"]

    status_resp = client.get("/api/v1/agent/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "ready"
    assert status_data["total_tasks"] == 4


def test_vercel_agent_tools_discovery(client: TestClient) -> None:
    """Verify /api/v1/agent/tools returns discovered tools without 503."""
    resp = client.get("/api/v1/agent/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert isinstance(tools, list)
    assert len(tools) > 0
    names = {t["name"] for t in tools}
    assert "list_tasks" in names
    assert "create_task" in names
    assert "delete_task" in names


def test_vercel_agent_execution_read(client: TestClient) -> None:
    """Verify Agent natural language execution runs in-process on Vercel without 503."""
    resp = client.post(
        "/api/v1/agent/execute",
        json={"request": "Show me all pending tasks", "confirm_destructive": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "Found" in data["message"]
    assert len(data["tool_invocations"]) == 1
    assert data["tool_invocations"][0]["tool_name"] == "list_tasks"


def test_vercel_agent_execution_create_and_delete(client: TestClient) -> None:
    """Verify Agent can create and delete tasks in-process on Vercel."""
    # 1. Create task
    create_resp = client.post(
        "/api/v1/agent/execute",
        json={"request": "Create a task called Deploy Vercel Production with priority urgent"},
    )
    assert create_resp.status_code == 200
    create_data = create_resp.json()
    assert create_data["success"] is True
    assert "Deploy Vercel Production" in create_data["message"]

    # 2. Delete task requires confirmation
    del_unconfirmed = client.post(
        "/api/v1/agent/execute",
        json={"request": "Delete task t-3", "confirm_destructive": False},
    )
    assert del_unconfirmed.status_code == 200
    assert del_unconfirmed.json()["requires_confirmation"] is True

    # 3. Delete task confirmed
    del_confirmed = client.post(
        "/api/v1/agent/execute",
        json={"request": "Delete task t-3", "confirm_destructive": True},
    )
    assert del_confirmed.status_code == 200
    assert del_confirmed.json()["success"] is True


def test_vercel_test_connection_and_tool_execution(client: TestClient) -> None:
    """Verify generating a server, testing connection, and executing tools on Vercel."""
    # 1. Generate server
    gen_resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": SAMPLE_SPEC, "package_name": "vercel_test_mcp"},
    )
    assert gen_resp.status_code == 201
    gen_id = gen_resp.json()["generation_id"]

    # 2. Test connection (no 503!)
    test_resp = client.post(f"/api/v1/servers/{gen_id}/test-connection")
    assert test_resp.status_code == 200
    test_data = test_resp.json()
    assert test_data["success"] is True
    assert test_data["tool_count"] == 2
    assert "list_tasks" in test_data["discovered_tools"]
    assert "create_task" in test_data["discovered_tools"]

    # 3. Execute tool (no 503!)
    exec_resp = client.post(
        f"/api/v1/servers/{gen_id}/execute-tool",
        json={"tool_name": "list_tasks", "arguments": {}},
    )
    assert exec_resp.status_code == 200
    exec_data = exec_resp.json()
    assert exec_data["success"] is True
    assert exec_data["tool_name"] == "list_tasks"


def test_vercel_security_guardrails_dry_run(client: TestClient) -> None:
    """Verify dry-run mode intercepts mutating requests under Vercel environment."""
    # Enable dry-run mode
    sec_resp = client.post("/api/v1/security/config", json={"dry_run": True})
    assert sec_resp.status_code == 200
    assert sec_resp.json()["dry_run"] is True

    # Generate server
    gen_resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": SAMPLE_SPEC, "package_name": "dryrun_mcp"},
    )
    gen_id = gen_resp.json()["generation_id"]

    # Execute mutating tool
    exec_resp = client.post(
        f"/api/v1/servers/{gen_id}/execute-tool",
        json={"tool_name": "create_task", "arguments": {"title": "Dry Run Task"}},
    )
    assert exec_resp.status_code == 200
    exec_data = exec_resp.json()
    assert exec_data["success"] is True
    assert exec_data["execution_status"] == "DRY-RUN"
    assert "intercepted" in exec_data["content"].lower()

    # Reset dry-run
    client.post("/api/v1/security/config", json={"dry_run": False})
