"""Tests for generating MCP servers from Demo Task Management API OpenAPI spec."""

from pathlib import Path
import pytest

from backend.generator import generate_mcp_server, parse_openapi
from demo_api.app import app


def test_demo_api_spec_normalization() -> None:
    """Verify that Demo API OpenAPI spec normalizes cleanly into 10 operations."""
    spec = app.openapi()
    api = parse_openapi(spec)
    assert api.title == "Demo Task Management API"
    assert len(api.operations) == 10

    tool_names = {op.tool_name for op in api.operations}
    assert "get_health" in tool_names
    assert "get_task_summary" in tool_names
    assert "list_tasks" in tool_names
    assert "get_task_by_id" in tool_names
    assert "create_task" in tool_names
    assert "update_task" in tool_names
    assert "delete_task" in tool_names
    assert "list_projects" in tool_names
    assert "list_project_tasks" in tool_names
    assert "reset_database" in tool_names


def test_demo_api_full_server_generation(tmp_path: Path) -> None:
    """Verify generating complete MCP server package for Demo API."""
    spec = app.openapi()
    api = parse_openapi(spec)
    out_dir = tmp_path / "demo_mcp"

    result = generate_mcp_server(
        api=api,
        output_dir=out_dir,
        package_name="demo_mcp",
        base_url="http://127.0.0.1:8000",
        overwrite=True,
    )

    assert result.output_dir == out_dir
    assert result.package_name == "demo_mcp"
    assert result.operation_count == 10
    assert len(result.tool_names) == 10
    assert not result.read_only

    # Check generated files
    server_py = out_dir / "server.py"
    readme_py = out_dir / "README.md"
    reqs_py = out_dir / "requirements.txt"
    env_py = out_dir / ".env.example"

    assert server_py.exists()
    assert readme_py.exists()
    assert reqs_py.exists()
    assert env_py.exists()

    content = server_py.read_text(encoding="utf-8")
    assert "app = MCPServer(" in content
    assert "list_tasks" in content
    assert "create_task" in content
    assert "delete_task" in content


def test_demo_api_read_only_generation(tmp_path: Path) -> None:
    """Verify generating strict read-only MCP server from Demo API exposes only GET tools."""
    spec = app.openapi()
    api = parse_openapi(spec)
    out_dir = tmp_path / "demo_ro_mcp"

    result = generate_mcp_server(
        api=api,
        output_dir=out_dir,
        package_name="demo_ro_mcp",
        base_url="http://127.0.0.1:8000",
        read_only=True,
        overwrite=True,
    )

    assert result.read_only is True
    # 5 GET operations: get_health, get_task_summary, list_tasks, get_task_by_id, list_projects, list_project_tasks (6 total GETs)
    expected_read_only = {
        "get_health",
        "get_task_summary",
        "list_tasks",
        "get_task_by_id",
        "list_projects",
        "list_project_tasks",
    }
    assert set(result.tool_names) == expected_read_only
    assert "create_task" not in result.tool_names
    assert "update_task" not in result.tool_names
    assert "delete_task" not in result.tool_names
    assert "reset_database" not in result.tool_names
