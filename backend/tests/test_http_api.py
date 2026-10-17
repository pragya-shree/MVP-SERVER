"""Automated tests for Generator HTTP API v1 endpoints and artifact management."""

import io
from pathlib import Path
import time
import zipfile
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.storage import storage_service

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"
SAMPLE_YAML_PATH = EXAMPLES_DIR / "task_management_api.yaml"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """FastAPI TestClient with isolated temporary storage directory."""
    original_storage = storage_service.storage_dir
    storage_service.storage_dir = tmp_path / "test_artifacts"
    storage_service.storage_dir.mkdir(parents=True, exist_ok=True)

    test_client = TestClient(app)
    yield test_client

    storage_service.storage_dir = original_storage


def test_api_v1_health(client: TestClient) -> None:
    """Verify GET /api/v1/health returns 200 and operational metadata."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "anything-to-mcp-generator"
    assert "timestamp" in data


def test_validate_spec_success(client: TestClient) -> None:
    """Verify POST /api/v1/specs/validate with valid specification content."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    resp = client.post("/api/v1/specs/validate", json={"spec": yaml_content})
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["title"] == "Task Management API"
    assert data["version"] == "1.0.0"
    assert data["operation_count"] == 5
    assert len(data["operations"]) == 5
    tool_names = [op["tool_name"] for op in data["operations"]]
    assert "list_tasks" in tool_names
    assert "create_task" in tool_names
    assert data["errors"] == []


def test_validate_spec_via_file_upload(client: TestClient) -> None:
    """Verify POST /api/v1/specs/validate using multipart file upload."""
    yaml_bytes = SAMPLE_YAML_PATH.read_bytes()
    resp = client.post(
        "/api/v1/specs/validate",
        files={"file": ("spec.yaml", yaml_bytes, "application/x-yaml")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["operation_count"] == 5


def test_validate_spec_invalid_syntax(client: TestClient) -> None:
    """Verify validation returns valid=False and error details on syntax error."""
    bad_yaml = "openapi: 3.0.3\ninfo:\n  title: Broken\npaths: [this is invalid yaml: :"
    resp = client.post("/api/v1/specs/validate", json={"spec": bad_yaml})
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    assert len(data["errors"]) > 0


def test_validate_spec_exceeding_size_limit(client: TestClient) -> None:
    """Verify uploading payload > 5 MB returns 413 Request Entity Too Large."""
    huge_payload = "a" * (5 * 1024 * 1024 + 100)
    resp = client.post(
        "/api/v1/specs/validate",
        files={"file": ("huge.yaml", io.BytesIO(huge_payload.encode()), "application/x-yaml")},
    )
    assert resp.status_code == 413
    assert "exceeds" in resp.json()["detail"].lower()


def test_generate_server_success(client: TestClient) -> None:
    """Verify generating MCP server package returns 201, ID, and download link."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": yaml_content, "package_name": "custom_task_pkg"},
    )
    assert resp.status_code == 201
    data = resp.json()
    generation_id = data["generation_id"]
    assert generation_id
    assert data["package_name"] == "custom_task_pkg"
    assert data["tool_count"] == 5
    assert data["download_url"] == f"/api/v1/servers/{generation_id}/download"
    assert "list_tasks" in data["tool_names"]


def test_generate_server_read_only_mode(client: TestClient) -> None:
    """Verify generating in read-only mode exposes only GET operations."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": yaml_content, "read_only": True},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["read_only"] is True
    # Exactly the 3 GET operations
    assert set(data["tool_names"]) == {"list_tasks", "get_task_by_id", "get_projects_by_project_id_tasks"}


def test_generate_server_invalid_base_url(client: TestClient) -> None:
    """Verify rejecting unsafe or malformed base URL schemes."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": yaml_content, "base_url": "file:///etc/passwd"},
    )
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"].lower()


def test_generate_server_path_traversal_package_name(client: TestClient) -> None:
    """Verify rejecting package names attempting directory traversal."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": yaml_content, "package_name": "../../traversal_pkg"},
    )
    assert resp.status_code == 400
    assert "package_name" in resp.json()["detail"].lower()


def test_inspect_tools(client: TestClient) -> None:
    """Verify inspecting tools of a valid generation run returns actual schemas."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    gen_resp = client.post("/api/v1/servers/generate", json={"spec": yaml_content})
    gen_id = gen_resp.json()["generation_id"]

    resp = client.get(f"/api/v1/servers/{gen_id}/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert data["generation_id"] == gen_id
    assert data["tool_count"] == 5

    tools_by_name = {t["name"]: t for t in data["tools"]}
    assert "list_tasks" in tools_by_name
    assert "create_task" in tools_by_name

    # Verify input_schema is included and populated
    create_schema = tools_by_name["create_task"]["input_schema"]
    assert "properties" in create_schema
    assert "title" in create_schema["properties"]


def test_inspect_tools_invalid_and_missing_id(client: TestClient) -> None:
    """Verify 400 for path traversal ID and 404 for nonexistent UUID."""
    # Path traversal attempt
    resp_traversal = client.get("/api/v1/servers/../../bad_id/tools")
    assert resp_traversal.status_code in (400, 404)

    # Valid UUID format but nonexistent
    resp_404 = client.get("/api/v1/servers/00000000-0000-0000-0000-000000000000/tools")
    assert resp_404.status_code == 404


def test_download_zip_archive_and_contents(client: TestClient) -> None:
    """Verify downloading generated package ZIP and validate files inside archive."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    gen_resp = client.post(
        "/api/v1/servers/generate",
        json={"spec": yaml_content, "package_name": "zip_test_pkg"},
    )
    gen_id = gen_resp.json()["generation_id"]

    resp = client.get(f"/api/v1/servers/{gen_id}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert 'filename="zip_test_pkg.zip"' in resp.headers["content-disposition"]

    # Read and inspect ZIP in-memory
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    namelist = zf.namelist()
    assert "server.py" in namelist
    assert "README.md" in namelist
    assert "requirements.txt" in namelist
    assert ".env.example" in namelist

    # Verify server.py inside zip has valid Python code
    server_content = zf.read("server.py").decode("utf-8")
    assert "app = MCPServer(" in server_content
    compile(server_content, "<zip_server>", "exec")


def test_artifact_isolation_and_concurrent_requests(client: TestClient) -> None:
    """Verify that multiple generation requests produce isolated directories."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")

    resp1 = client.post("/api/v1/servers/generate", json={"spec": yaml_content, "package_name": "pkg_a"})
    resp2 = client.post("/api/v1/servers/generate", json={"spec": yaml_content, "package_name": "pkg_b"})

    id1 = resp1.json()["generation_id"]
    id2 = resp2.json()["generation_id"]
    assert id1 != id2

    tools1 = client.get(f"/api/v1/servers/{id1}/tools").json()
    tools2 = client.get(f"/api/v1/servers/{id2}/tools").json()

    assert tools1["package_name"] == "pkg_a"
    assert tools2["package_name"] == "pkg_b"


def test_artifact_cleanup_expiration(client: TestClient) -> None:
    """Verify cleanup_expired removes old directories while keeping fresh ones."""
    yaml_content = SAMPLE_YAML_PATH.read_text(encoding="utf-8")
    resp = client.post("/api/v1/servers/generate", json={"spec": yaml_content})
    gen_id = resp.json()["generation_id"]

    # When max_age is large (e.g. 1 hour), nothing is deleted
    deleted_none = storage_service.cleanup_expired(max_age_seconds=3600)
    assert deleted_none == 0
    assert client.get(f"/api/v1/servers/{gen_id}/tools").status_code == 200

    # When max_age is 0, expired artifacts are purged
    deleted_old = storage_service.cleanup_expired(max_age_seconds=0)
    assert deleted_old >= 1
    assert client.get(f"/api/v1/servers/{gen_id}/tools").status_code == 404
