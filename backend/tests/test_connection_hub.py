"""Automated tests for MCP Server Connection Hub endpoints, integrations, and connection verification."""

from datetime import datetime
import io
import json
from pathlib import Path
import zipfile
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.storage import storage_service
from backend.security import global_audit_logger

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"
SAMPLE_YAML_PATH = EXAMPLES_DIR / "task_management_api.yaml"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """FastAPI TestClient with isolated temporary storage directory."""
    original_storage = storage_service.storage_dir
    storage_service.storage_dir = tmp_path / "test_hub_artifacts"
    storage_service.storage_dir.mkdir(parents=True, exist_ok=True)

    test_client = TestClient(app)
    yield test_client

    storage_service.storage_dir = original_storage


def test_get_server_integrations_success(client: TestClient) -> None:
    """Verify GET /api/v1/servers/{generation_id}/integrations returns complete client configs."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    gen_resp = client.post(
        "/api/v1/servers/generate",
        json={
            "spec": yaml_content,
            "package_name": "hub_test_mcp",
            "base_url": "http://127.0.0.1:8000/demo-target",
        },
    )
    assert gen_resp.status_code == 201
    gen_id = gen_resp.json()["generation_id"]

    resp = client.get(f"/api/v1/servers/{gen_id}/integrations")
    assert resp.status_code == 200
    data = resp.json()

    assert data["generation_id"] == gen_id
    assert data["package_name"] == "hub_test_mcp"
    assert data["base_url"] == "http://127.0.0.1:8000/demo-target"
    assert data["read_only"] is False
    assert data["available_transports"] == ["stdio"]
    assert "server.py" in data["server_path"]

    # Verify all expected integrations are present
    integration_ids = [item["id"] for item in data["integrations"]]
    assert "claude-desktop" in integration_ids
    assert "claude-code" in integration_ids
    assert "cursor" in integration_ids
    assert "vscode" in integration_ids
    assert "stdio" in integration_ids
    assert "docker" in integration_ids
    assert "hosted" in integration_ids

    # 1. Claude Desktop checks
    claude_desktop = next(i for i in data["integrations"] if i["id"] == "claude-desktop")
    assert claude_desktop["transport"] == "stdio"
    assert claude_desktop["format"] == "json"
    assert "claude_desktop_config.json" in claude_desktop["target_file"]
    desktop_parsed = json.loads(claude_desktop["snippet"])
    assert "hub_test_mcp" in desktop_parsed["mcpServers"]
    assert desktop_parsed["mcpServers"]["hub_test_mcp"]["command"] == "python"
    assert desktop_parsed["mcpServers"]["hub_test_mcp"]["args"][0] == data["server_path"]
    assert desktop_parsed["mcpServers"]["hub_test_mcp"]["env"]["TARGET_BASE_URL"] == "http://127.0.0.1:8000/demo-target"
    assert desktop_parsed["mcpServers"]["hub_test_mcp"]["env"]["BEARER_TOKEN"] == "${YOUR_BEARER_TOKEN}"

    # 2. Claude Code checks
    claude_code = next(i for i in data["integrations"] if i["id"] == "claude-code")
    assert claude_code["transport"] == "stdio"
    assert claude_code["format"] == "bash"
    assert "claude mcp add hub_test_mcp" in claude_code["snippet"]
    assert "${YOUR_BEARER_TOKEN}" in claude_code["snippet"]

    # 3. Cursor checks
    cursor = next(i for i in data["integrations"] if i["id"] == "cursor")
    assert cursor["transport"] == "stdio"
    assert cursor["target_file"] == ".cursor/mcp.json"
    cursor_parsed = json.loads(cursor["snippet"])
    assert "hub_test_mcp" in cursor_parsed["mcpServers"]

    # 4. VS Code checks
    vscode = next(i for i in data["integrations"] if i["id"] == "vscode")
    assert vscode["transport"] == "stdio"
    assert "mcp_settings.json" in vscode["target_file"]
    vscode_parsed = json.loads(vscode["snippet"])
    assert "hub_test_mcp" in vscode_parsed["mcpServers"]

    # 5. Local stdio checks
    stdio = next(i for i in data["integrations"] if i["id"] == "stdio")
    assert stdio["transport"] == "stdio"
    assert stdio["format"] == "bash"
    assert "python server.py" in stdio["snippet"]

    # 6. Docker checks
    docker = next(i for i in data["integrations"] if i["id"] == "docker")
    assert docker["transport"] == "stdio"
    assert "docker build -t hub_test_mcp:latest" in docker["snippet"]
    assert "docker run -i" in docker["snippet"]

    # 7. Hosted MCP checks
    hosted = next(i for i in data["integrations"] if i["id"] == "hosted")
    assert hosted["transport"] == "http"
    assert hosted["is_available"] is False
    assert "Not Available" in hosted["snippet"]
    assert "stdio" in hosted["snippet"].lower()

    # Secret Redaction & Safety Assurance: No real secret tokens in any snippet
    for item in data["integrations"]:
        snippet = item["snippet"]
        assert "sk-" not in snippet
        assert "ghp_" not in snippet
        assert "password123" not in snippet


def test_get_server_integrations_invalid_and_missing_id(client: TestClient) -> None:
    """Verify 400 for path traversal ID and 404 for nonexistent UUID."""
    resp_traversal = client.get("/api/v1/servers/../../bad_id/integrations")
    assert resp_traversal.status_code in (400, 404)

    resp_404 = client.get("/api/v1/servers/00000000-0000-0000-0000-000000000000/integrations")
    assert resp_404.status_code == 404


def test_connection_test_success_stdio_handshake(client: TestClient) -> None:
    """Verify POST /api/v1/servers/{generation_id}/test-connection launches stdio process and discovers tools."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    gen_resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": yaml_content, "package_name": "conn_test_pkg"},
    )
    assert gen_resp.status_code == 201
    gen_id = gen_resp.json()["generation_id"]

    test_resp = client.post(f"/api/v1/servers/{gen_id}/test-connection")
    assert test_resp.status_code == 200
    data = test_resp.json()

    assert data["success"] is True
    assert data["generation_id"] == gen_id
    assert data["package_name"] == "conn_test_pkg"
    assert data["transport"] == "stdio"
    assert data["tool_count"] == 5
    assert "list_tasks" in data["discovered_tools"]
    assert "create_task" in data["discovered_tools"]
    assert "delete_task" in data["discovered_tools"]
    assert data["error"] is None
    assert "tested_at" in data
    assert "successfully" in data["message"].lower()


def test_connection_test_invalid_and_missing_id(client: TestClient) -> None:
    """Verify 400 for invalid UUID format and 404 for nonexistent UUID on test-connection."""
    # Invalid UUID format directly hits route and triggers validation 400
    resp_invalid = client.post("/api/v1/servers/not-a-valid-uuid-12345/test-connection")
    assert resp_invalid.status_code == 400

    # Path traversal attempt
    resp_traversal = client.post("/api/v1/servers/../../bad_id/test-connection")
    assert resp_traversal.status_code in (400, 404, 405)

    resp_404 = client.post("/api/v1/servers/00000000-0000-0000-0000-000000000000/test-connection")
    assert resp_404.status_code == 404


def test_connection_test_audit_logging_and_sanitization(client: TestClient) -> None:
    """Verify connection tests are recorded into the security audit log without leaking raw paths."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    gen_resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": yaml_content, "package_name": "audit_test_pkg"},
    )
    gen_id = gen_resp.json()["generation_id"]

    # Run connection test
    test_resp = client.post(f"/api/v1/servers/{gen_id}/test-connection")
    assert test_resp.status_code == 200

    # Query audit history
    audit_resp = client.get("/api/v1/security/audit?limit=10")
    assert audit_resp.status_code == 200
    entries = audit_resp.json()

    # Look for mcp_connection_test entry
    test_entry = next((e for e in entries if e["tool_name"] == "mcp_connection_test"), None)
    assert test_entry is not None
    assert test_entry["method"] == "MCP_INIT"
    assert test_entry["execution_status"] == "EXECUTED"
    assert test_entry["policy_decision"] == "ALLOW"
    assert test_entry["is_mutating"] is False
    assert test_entry["safe_arguments"]["server_name"] == "audit_test_pkg"
    assert test_entry["safe_arguments"]["tool_count"] == 5


def test_connection_test_failure_graceful_handling(client: TestClient) -> None:
    """Verify that a broken server script returns success=False without crashing the FastAPI app."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    gen_resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": yaml_content, "package_name": "broken_test_pkg"},
    )
    gen_id = gen_resp.json()["generation_id"]

    # Deliberately corrupt server.py
    gen_dir = storage_service.get_generation_dir(gen_id)
    assert gen_dir is not None
    server_py = gen_dir / "broken_test_pkg" / "server.py"
    server_py.write_text("import sys\nsys.exit(42)\n", encoding="utf-8")

    test_resp = client.post(f"/api/v1/servers/{gen_id}/test-connection")
    assert test_resp.status_code == 200
    data = test_resp.json()

    assert data["success"] is False
    assert data["tool_count"] == 0
    assert data["discovered_tools"] == []
    assert data["error"] is not None


def test_read_only_server_integrations_and_connection(client: TestClient) -> None:
    """Verify strict read-only server exposes only GET tools and sets read_only=True."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    gen_resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": yaml_content, "package_name": "readonly_hub_pkg", "read_only": True},
    )
    assert gen_resp.status_code == 201
    gen_id = gen_resp.json()["generation_id"]

    # Verify integrations reflect read_only
    int_resp = client.get(f"/api/v1/servers/{gen_id}/integrations")
    assert int_resp.status_code == 200
    assert int_resp.json()["read_only"] is True

    # Verify connection discovers only the 2 read-only GET tools
    test_resp = client.post(f"/api/v1/servers/{gen_id}/test-connection")
    assert test_resp.status_code == 200
    data = test_resp.json()
    assert data["success"] is True
    assert data["tool_count"] == 3
    assert set(data["discovered_tools"]) == {
        "list_tasks",
        "get_task_by_id",
        "get_projects_by_project_id_tasks",
    }


def test_dockerfile_generated_in_package(client: TestClient) -> None:
    """Verify Dockerfile is generated and packaged in the downloadable ZIP."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    gen_resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": yaml_content, "package_name": "docker_pkg"},
    )
    gen_id = gen_resp.json()["generation_id"]

    # Verify ZIP archive includes Dockerfile
    dl_resp = client.get(f"/api/v1/servers/{gen_id}/download")
    assert dl_resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(dl_resp.content))
    namelist = zf.namelist()
    assert "Dockerfile" in namelist
    dockerfile_content = zf.read("Dockerfile").decode("utf-8")
    assert "FROM python:3.11-slim" in dockerfile_content
    assert 'ENTRYPOINT ["python", "server.py"]' in dockerfile_content
