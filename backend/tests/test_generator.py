"""Tests for the MCP server generator, tool discovery, execution, auth, and read-only mode."""

import importlib.util
import json
from pathlib import Path
import types
from typing import Any
import pytest
import httpx

from backend.generator import (
    GenerationError,
    GenerationResult,
    NormalizedAPI,
    generate_mcp_server,
    parse_openapi_file,
)

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


def load_generated_server_module(server_file: Path) -> types.ModuleType:
    """Dynamically load the generated server.py module into Python."""
    spec = importlib.util.spec_from_file_location("generated_server", server_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def task_api() -> NormalizedAPI:
    """Fixture providing parsed Task Management API."""
    return parse_openapi_file(EXAMPLES_DIR / "task_management_api.yaml")


def test_generate_task_management_package(tmp_path: Path, task_api: NormalizedAPI) -> None:
    """Verify package generation, file layout, and syntax of generated code."""
    result: GenerationResult = generate_mcp_server(
        api=task_api,
        output_dir=tmp_path,
        package_name="task_server",
    )

    assert result.output_dir == tmp_path / "task_server"
    assert result.package_name == "task_server"
    assert result.operation_count == 5
    assert result.read_only is False
    assert len(result.tool_names) == 5

    # Check files created
    server_file = result.output_dir / "server.py"
    readme_file = result.output_dir / "README.md"
    reqs_file = result.output_dir / "requirements.txt"
    env_file = result.output_dir / ".env.example"

    assert server_file.exists()
    assert readme_file.exists()
    assert reqs_file.exists()
    assert env_file.exists()

    # Verify python syntax
    code = server_file.read_text(encoding="utf-8")
    compiled = compile(code, str(server_file), "exec")
    assert compiled is not None

    # Verify independence: generated code must not import backend.generator
    assert "backend.generator" not in code
    assert "from backend" not in code

    # Verify credentials are not hardcoded
    env_text = env_file.read_text(encoding="utf-8")
    assert "BEARER_TOKEN=" in env_text
    assert "API_KEY=" in env_text


def test_deterministic_generation(tmp_path: Path, task_api: NormalizedAPI) -> None:
    """Verify repeated generation produces byte-for-byte deterministic output."""
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"

    res1 = generate_mcp_server(api=task_api, output_dir=out1, package_name="mcp_pkg")
    res2 = generate_mcp_server(api=task_api, output_dir=out2, package_name="mcp_pkg")

    server1 = (res1.output_dir / "server.py").read_text(encoding="utf-8")
    server2 = (res2.output_dir / "server.py").read_text(encoding="utf-8")
    assert server1 == server2

    readme1 = (res1.output_dir / "README.md").read_text(encoding="utf-8")
    readme2 = (res2.output_dir / "README.md").read_text(encoding="utf-8")
    assert readme1 == readme2


def test_generation_overwrite_protection(tmp_path: Path, task_api: NormalizedAPI) -> None:
    """Verify GenerationError is raised when target exists and overwrite=False."""
    out = tmp_path / "protected"
    generate_mcp_server(api=task_api, output_dir=out, package_name="pkg", overwrite=True)

    with pytest.raises(GenerationError) as exc_info:
        generate_mcp_server(api=task_api, output_dir=out, package_name="pkg", overwrite=False)

    assert "already exists" in str(exc_info.value)


@pytest.mark.asyncio
async def test_mcp_tool_discovery_and_schemas(tmp_path: Path, task_api: NormalizedAPI) -> None:
    """Verify tools are discovered through MCP SDK with expected schemas and descriptions."""
    res = generate_mcp_server(api=task_api, output_dir=tmp_path, package_name="discovery_pkg")
    server_module = load_generated_server_module(res.output_dir / "server.py")

    app = server_module.build_server()
    tools = await app.list_tools()

    assert len(tools) == 5
    tool_map = {t.name: t for t in tools}

    expected_tools = {
        "list_tasks",
        "create_task",
        "get_task_by_id",
        "delete_task",
        "get_projects_by_project_id_tasks",
    }
    assert set(tool_map.keys()) == expected_tools

    # 1. get_task_by_id schema check
    get_task = tool_map["get_task_by_id"]
    assert "task_id" in get_task.input_schema["properties"]
    assert "task_id" in get_task.input_schema["required"]
    assert "HTTP GET /tasks/{task_id}" in get_task.description

    # 2. list_tasks schema check (enum, defaults)
    list_tasks = tool_map["list_tasks"]
    assert "status" in list_tasks.input_schema["properties"]
    assert list_tasks.input_schema["properties"]["status"]["enum"] == [
        "todo",
        "in_progress",
        "completed",
        "archived",
    ]
    assert list_tasks.input_schema["properties"]["limit"]["default"] == 20

    # 3. create_task schema check (required body property)
    create_task = tool_map["create_task"]
    assert "title" in create_task.input_schema["properties"]
    assert "title" in create_task.input_schema["required"]


@pytest.mark.asyncio
async def test_http_execution_get_with_params(tmp_path: Path, task_api: NormalizedAPI) -> None:
    """Verify GET request execution with path and query parameters using mock transport."""
    res = generate_mcp_server(api=task_api, output_dir=tmp_path, package_name="exec_pkg")
    server_module = load_generated_server_module(res.output_dir / "server.py")

    recorded_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        if request.url.path == "/tasks":
            status = request.url.params.get("status")
            limit = request.url.params.get("limit")
            return httpx.Response(
                200,
                json=[{"id": "1", "title": "Test Task", "status": status, "limit": limit}],
            )
        return httpx.Response(404, json={"detail": "Not found"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler), base_url="http://test-api")
    config = server_module.ServerConfig(target_base_url="http://test-api")
    app = server_module.build_server(config=config, client=mock_client)

    result = await app.call_tool("list_tasks", {"status": "todo", "limit": 10})
    assert not result.is_error

    data = json.loads(result.content[0].text)
    assert data["status_code"] == 200
    assert data["data"][0]["status"] == "todo"
    assert data["data"][0]["limit"] == "10"

    assert len(recorded_requests) == 1
    assert recorded_requests[0].method == "GET"


@pytest.mark.asyncio
async def test_http_execution_post_json_body(tmp_path: Path, task_api: NormalizedAPI) -> None:
    """Verify POST request execution with structured JSON body."""
    res = generate_mcp_server(api=task_api, output_dir=tmp_path, package_name="post_pkg")
    server_module = load_generated_server_module(res.output_dir / "server.py")

    recorded_bodies = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content.decode("utf-8"))
        recorded_bodies.append(body)
        return httpx.Response(201, json={"id": "new-123", **body})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler), base_url="http://test-api")
    config = server_module.ServerConfig(target_base_url="http://test-api")
    app = server_module.build_server(config=config, client=mock_client)

    result = await app.call_tool("create_task", {"title": "Write Unit Tests", "priority": "urgent"})
    assert not result.is_error

    data = json.loads(result.content[0].text)
    assert data["status_code"] == 201
    assert data["data"]["title"] == "Write Unit Tests"
    assert data["data"]["priority"] == "urgent"

    assert len(recorded_bodies) == 1
    assert recorded_bodies[0]["title"] == "Write Unit Tests"


@pytest.mark.asyncio
async def test_http_execution_path_param_encoding_and_204(tmp_path: Path, task_api: NormalizedAPI) -> None:
    """Verify URL path encoding and empty response (HTTP 204) handling."""
    res = generate_mcp_server(api=task_api, output_dir=tmp_path, package_name="path_pkg")
    server_module = load_generated_server_module(res.output_dir / "server.py")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        # Check path parameter was properly URL encoded on the wire
        if request.url.raw_path == b"/tasks/item%20with%20spaces":
            if request.method == "GET":
                return httpx.Response(200, json={"id": "item with spaces"})
            elif request.method == "DELETE":
                return httpx.Response(204)
        return httpx.Response(404, json={"detail": "Not found"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler), base_url="http://test-api")
    config = server_module.ServerConfig(target_base_url="http://test-api")
    app = server_module.build_server(config=config, client=mock_client)

    # 1. GET with spaces in path parameter
    res_get = await app.call_tool("get_task_by_id", {"task_id": "item with spaces"})
    data_get = json.loads(res_get.content[0].text)
    assert data_get["status_code"] == 200
    assert data_get["data"]["id"] == "item with spaces"

    # 2. DELETE with 204 No Content
    res_del = await app.call_tool("delete_task", {"task_id": "item with spaces"})
    data_del = json.loads(res_del.content[0].text)
    assert data_del["status_code"] == 204
    assert data_del["data"] is None
    assert data_del["message"] == "No Content"


@pytest.mark.asyncio
async def test_http_execution_error_and_timeout_handling(tmp_path: Path, task_api: NormalizedAPI) -> None:
    """Verify HTTP error statuses and timeouts are handled without server crash or leaking secrets."""
    res = generate_mcp_server(api=task_api, output_dir=tmp_path, package_name="error_pkg")
    server_module = load_generated_server_module(res.output_dir / "server.py")

    # 1. HTTP 404 test
    def not_found_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error_code": "NOT_FOUND", "message": "Task does not exist."})

    client_404 = httpx.AsyncClient(transport=httpx.MockTransport(not_found_handler), base_url="http://test")
    app_404 = server_module.build_server(client=client_404)
    res_404 = await app_404.call_tool("get_task_by_id", {"task_id": "missing-uuid"})
    data_404 = json.loads(res_404.content[0].text)
    assert data_404["error"] is True
    assert data_404["status_code"] == 404
    assert data_404["detail"]["error_code"] == "NOT_FOUND"

    # 2. Timeout test
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read operation timed out", request=request)

    client_timeout = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler), base_url="http://test")
    app_timeout = server_module.build_server(client=client_timeout)
    res_timeout = await app_timeout.call_tool("get_task_by_id", {"task_id": "timeout-uuid"})
    data_timeout = json.loads(res_timeout.content[0].text)
    assert data_timeout["error"] is True
    assert data_timeout["type"] == "timeout"


@pytest.mark.asyncio
async def test_authentication_bearer_and_api_key_injection(tmp_path: Path, task_api: NormalizedAPI) -> None:
    """Verify bearer tokens and API keys are injected, and public override is honored."""
    res = generate_mcp_server(api=task_api, output_dir=tmp_path, package_name="auth_pkg")
    server_module = load_generated_server_module(res.output_dir / "server.py")

    captured_headers: dict[str, str] = {}

    def auth_handler(request: httpx.Request) -> httpx.Response:
        captured_headers.clear()
        captured_headers.update(dict(request.headers))
        return httpx.Response(200, json={"ok": True})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(auth_handler), base_url="http://test")

    # Configure Bearer token
    config_bearer = server_module.ServerConfig(
        target_base_url="http://test",
        bearer_token="secret-jwt-token-xyz",
    )
    app_bearer = server_module.build_server(config=config_bearer, client=mock_client)

    # 1. Calling protected endpoint (POST /tasks) -> Authorization header present
    await app_bearer.call_tool("create_task", {"title": "Auth Task"})
    assert "authorization" in captured_headers
    assert captured_headers["authorization"] == "Bearer secret-jwt-token-xyz"

    # 2. Calling public override endpoint (GET /tasks has security: []) -> Authorization header NOT present
    await app_bearer.call_tool("list_tasks", {})
    assert "authorization" not in captured_headers

    # 3. Configure API Key
    config_apikey = server_module.ServerConfig(
        target_base_url="http://test",
        api_key="secret-api-key-123",
        api_key_header="X-API-Key",
    )
    app_apikey = server_module.build_server(config=config_apikey, client=mock_client)
    await app_apikey.call_tool("create_task", {"title": "API Key Task"})
    assert "x-api-key" in captured_headers
    assert captured_headers["x-api-key"] == "secret-api-key-123"


@pytest.mark.asyncio
async def test_read_only_mode_generation(tmp_path: Path, task_api: NormalizedAPI) -> None:
    """Verify read_only=True generates server containing only GET tools."""
    res: GenerationResult = generate_mcp_server(
        api=task_api,
        output_dir=tmp_path,
        package_name="readonly_pkg",
        read_only=True,
    )

    assert res.read_only is True
    assert res.operation_count == 3  # Exactly the 3 GET operations

    server_module = load_generated_server_module(res.output_dir / "server.py")
    app = server_module.build_server()
    tools = await app.list_tools()

    assert len(tools) == 3
    tool_names = {t.name for t in tools}
    assert tool_names == {"list_tasks", "get_task_by_id", "get_projects_by_project_id_tasks"}

    # Verify write tools (POST, DELETE) are completely absent from server
    assert "create_task" not in tool_names
    assert "delete_task" not in tool_names
    assert "create_task" not in server_module.OPERATIONS_METADATA
    assert "delete_task" not in server_module.OPERATIONS_METADATA


def test_generation_empty_operations_raises_error(tmp_path: Path) -> None:
    """Verify GenerationError when no operations match criteria (e.g. read_only on POST-only API)."""
    post_only_api = NormalizedAPI(
        openapi_version="3.0.3",
        title="Write Only API",
        version="1.0.0",
        operations=[],
    )

    with pytest.raises(GenerationError) as exc_info:
        generate_mcp_server(api=post_only_api, output_dir=tmp_path, read_only=True)

    assert "No operations available" in str(exc_info.value)
