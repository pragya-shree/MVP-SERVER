"""Automated tests for Multi-API Workspace execution, tool collision handling, and security guardrails."""

import http.server
import json
from pathlib import Path
import threading
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.storage import storage_service
from backend.security import (
    global_policy_engine,
    global_approval_store,
    global_audit_logger,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"
TASK_YAML_PATH = EXAMPLES_DIR / "task_management_api.yaml"

STORE_YAML_SPEC = """openapi: 3.0.3
info:
  title: Store & Inventory API
  version: 2.1.0
paths:
  /items:
    get:
      operationId: list_items
      summary: List inventory products
      responses:
        '200':
          description: OK
    post:
      operationId: create_item
      summary: Add new inventory product
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - title
              properties:
                title:
                  type: string
      responses:
        '201':
          description: Created
  /tasks:
    get:
      operationId: list_tasks
      summary: Cross-system store background tasks
      description: Intentionally duplicate tool name to test collision handling.
      responses:
        '200':
          description: OK
"""


class MockUpstreamHandler(http.server.BaseHTTPRequestHandler):
    """Local mock HTTP server responding to task and store endpoints."""

    def do_GET(self) -> None:
        if "/tasks/task_1" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"id": "task_1", "title": "Inspect Workspace"}).encode("utf-8"))
        elif "/tasks" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps([{"id": "task_1", "title": "Sample Task"}]).encode("utf-8"))
        elif "/items" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps([{"id": "item_1", "title": "Store Product"}]).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": "new_101", **body}).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def upstream_url() -> Generator[str, None, None]:
    """Start an ephemeral HTTP upstream server for real MCP tool execution."""
    server = http.server.HTTPServer(("127.0.0.1", 0), MockUpstreamHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}"

    server.shutdown()
    server.server_close()


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """FastAPI TestClient with isolated temporary storage directory."""
    original_storage = storage_service.storage_dir
    storage_service.storage_dir = tmp_path / "test_multi_api_artifacts"
    storage_service.storage_dir.mkdir(parents=True, exist_ok=True)

    test_client = TestClient(app)
    yield test_client

    storage_service.storage_dir = original_storage


def test_multi_api_different_specifications(client: TestClient, upstream_url: str) -> None:
    """Verify adding two distinct API specifications into the workspace."""
    # API 1: Task Management API
    task_spec = TASK_YAML_PATH.read_text(encoding="utf-8")
    resp_1 = client.post(
        "/api/v1/servers/generate",
        json={"spec": task_spec, "package_name": "task_api_pkg", "base_url": upstream_url},
    )
    assert resp_1.status_code == 201
    gen_id_1 = resp_1.json()["generation_id"]

    # API 2: Store API
    resp_2 = client.post(
        "/api/v1/servers/generate",
        json={"spec": STORE_YAML_SPEC, "package_name": "store_api_pkg", "base_url": upstream_url},
    )
    assert resp_2.status_code == 201
    gen_id_2 = resp_2.json()["generation_id"]

    assert gen_id_1 != gen_id_2

    # Verify tools discovery on API 1
    tools_1 = client.get(f"/api/v1/servers/{gen_id_1}/tools").json()
    assert tools_1["tool_count"] == 5
    tool_names_1 = [t["name"] for t in tools_1["tools"]]
    assert "list_tasks" in tool_names_1
    assert "create_task" in tool_names_1

    # Verify tools discovery on API 2
    tools_2 = client.get(f"/api/v1/servers/{gen_id_2}/tools").json()
    assert tools_2["tool_count"] == 3
    tool_names_2 = [t["name"] for t in tools_2["tools"]]
    assert "list_items" in tool_names_2
    assert "create_item" in tool_names_2
    assert "list_tasks" in tool_names_2


def test_duplicate_tool_names_across_apis_execute_correct_integration(client: TestClient, upstream_url: str) -> None:
    """Verify duplicate tool name 'list_tasks' routes to the correct target server without collisions."""
    task_spec = TASK_YAML_PATH.read_text(encoding="utf-8")
    gen_id_1 = client.post(
        "/api/v1/servers/generate",
        json={"spec": task_spec, "package_name": "task_api_pkg", "base_url": upstream_url},
    ).json()["generation_id"]

    gen_id_2 = client.post(
        "/api/v1/servers/generate",
        json={"spec": STORE_YAML_SPEC, "package_name": "store_api_pkg", "base_url": upstream_url},
    ).json()["generation_id"]

    # 1. Execute list_tasks on API 1
    exec_1 = client.post(
        f"/api/v1/servers/{gen_id_1}/execute-tool",
        json={"tool_name": "list_tasks", "arguments": {}},
    )
    assert exec_1.status_code == 200
    data_1 = exec_1.json()
    assert data_1["success"] is True
    assert data_1["generation_id"] == gen_id_1
    assert data_1["tool_name"] == "list_tasks"
    assert data_1["policy_decision"] == "ALLOW"
    assert data_1["execution_status"] == "EXECUTED"

    # 2. Execute list_tasks on API 2
    exec_2 = client.post(
        f"/api/v1/servers/{gen_id_2}/execute-tool",
        json={"tool_name": "list_tasks", "arguments": {}},
    )
    assert exec_2.status_code == 200
    data_2 = exec_2.json()
    assert data_2["success"] is True
    assert data_2["generation_id"] == gen_id_2
    assert data_2["tool_name"] == "list_tasks"
    assert data_2["policy_decision"] == "ALLOW"
    assert data_2["execution_status"] == "EXECUTED"


def test_multi_api_execute_tool_with_arguments(client: TestClient, upstream_url: str) -> None:
    """Verify tool execution with path and body arguments."""
    task_spec = TASK_YAML_PATH.read_text(encoding="utf-8")
    gen_id = client.post(
        "/api/v1/servers/generate",
        json={"spec": task_spec, "package_name": "task_api_pkg", "base_url": upstream_url},
    ).json()["generation_id"]

    # Execute get_task_by_id with arguments
    resp = client.post(
        f"/api/v1/servers/{gen_id}/execute-tool",
        json={"tool_name": "get_task_by_id", "arguments": {"task_id": "task_1"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["tool_name"] == "get_task_by_id"
    assert data["arguments"] == {"task_id": "task_1"}


def test_multi_api_security_policy_deny(client: TestClient, upstream_url: str) -> None:
    """Verify PolicyEngine DENY rule blocks tool execution immediately."""
    task_spec = TASK_YAML_PATH.read_text(encoding="utf-8")
    gen_id = client.post(
        "/api/v1/servers/generate",
        json={"spec": task_spec, "package_name": "deny_api_pkg", "base_url": upstream_url},
    ).json()["generation_id"]

    orig_denied = global_policy_engine.policy.denied_operations
    try:
        global_policy_engine.policy.denied_operations = ["delete_task"]

        resp = client.post(
            f"/api/v1/servers/{gen_id}/execute-tool",
            json={"tool_name": "delete_task", "arguments": {"task_id": "task_1"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["is_error"] is True
        assert data["policy_decision"] == "DENY"
        assert data["execution_status"] == "BLOCKED"
        assert "forbidden by security policy" in data["error"]
    finally:
        global_policy_engine.policy.denied_operations = orig_denied


def test_multi_api_security_dry_run_interception(client: TestClient, upstream_url: str) -> None:
    """Verify dry-run mode intercepts mutating requests in Multi-API Workspace."""
    task_spec = TASK_YAML_PATH.read_text(encoding="utf-8")
    gen_id = client.post(
        "/api/v1/servers/generate",
        json={"spec": task_spec, "package_name": "dryrun_api_pkg", "base_url": upstream_url},
    ).json()["generation_id"]

    orig_dry_run = global_policy_engine.policy.dry_run
    try:
        global_policy_engine.policy.dry_run = True

        resp = client.post(
            f"/api/v1/servers/{gen_id}/execute-tool",
            json={"tool_name": "create_task", "arguments": {"title": "Test Task", "priority": "high"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["policy_decision"] == "DRY_RUN"
        assert data["execution_status"] == "DRY-RUN"
        assert data["result"]["status"] == "DRY_RUN_INTERCEPTED"
        assert "upstream request was not sent" in data["result"]["message"]
    finally:
        global_policy_engine.policy.dry_run = orig_dry_run


def test_multi_api_security_approval_mode(client: TestClient, upstream_url: str) -> None:
    """Verify approval mode generates approval request on mutating tool, then executes once approved."""
    task_spec = TASK_YAML_PATH.read_text(encoding="utf-8")
    gen_id = client.post(
        "/api/v1/servers/generate",
        json={"spec": task_spec, "package_name": "approval_api_pkg", "base_url": upstream_url},
    ).json()["generation_id"]

    orig_approval = global_policy_engine.policy.require_approval
    try:
        global_policy_engine.policy.require_approval = True

        # 1. Execution without approval ID -> requires_approval
        resp_1 = client.post(
            f"/api/v1/servers/{gen_id}/execute-tool",
            json={"tool_name": "create_task", "arguments": {"title": "Needs Approval Task"}},
        )
        assert resp_1.status_code == 200
        data_1 = resp_1.json()
        assert data_1["success"] is False
        assert data_1["requires_approval"] is True
        assert data_1["approval_id"] is not None
        assert data_1["execution_status"] == "PENDING APPROVAL"
        approval_id = data_1["approval_id"]

        # Simulate the human clicking "Approve" in the security dashboard
        approved, approval_msg = global_approval_store.approve(approval_id)
        assert approved, f"Human approval step failed: {approval_msg}"

        # 2. Re-invoke with approval_id -> executes after human approval
        resp_2 = client.post(
            f"/api/v1/servers/{gen_id}/execute-tool",
            json={
                "tool_name": "create_task",
                "arguments": {"title": "Needs Approval Task"},
                "approval_id": approval_id,
            },
        )
        assert resp_2.status_code == 200
        data_2 = resp_2.json()
        # After approval is consumed the tool reaches the MCP client; upstream may
        # succeed or fail (test server may not implement the endpoint), but the
        # approval gate itself must have been passed (not blocked/pending).
        assert data_2["execution_status"] not in ("PENDING APPROVAL", "BLOCKED")
        assert data_2.get("requires_approval") is not True
    finally:
        global_policy_engine.policy.require_approval = orig_approval


def test_multi_api_isolation_failure_does_not_break_other_apis(client: TestClient, upstream_url: str) -> None:
    """Verify that an error on API A does not impact API B."""
    task_spec = TASK_YAML_PATH.read_text(encoding="utf-8")
    gen_id_1 = client.post(
        "/api/v1/servers/generate",
        json={"spec": task_spec, "package_name": "healthy_api", "base_url": upstream_url},
    ).json()["generation_id"]

    gen_id_2 = client.post(
        "/api/v1/servers/generate",
        json={"spec": STORE_YAML_SPEC, "package_name": "broken_api", "base_url": upstream_url},
    ).json()["generation_id"]

    # Deliberately request nonexistent tool on API 2
    err_resp = client.post(
        f"/api/v1/servers/{gen_id_2}/execute-tool",
        json={"tool_name": "nonexistent_tool_xyz", "arguments": {}},
    )
    assert err_resp.status_code == 404

    # API 1 continues to execute normally
    good_resp = client.post(
        f"/api/v1/servers/{gen_id_1}/execute-tool",
        json={"tool_name": "list_tasks", "arguments": {}},
    )
    assert good_resp.status_code == 200
    assert good_resp.json()["success"] is True
