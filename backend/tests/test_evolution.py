"""Automated tests for OpenAPI specification evolution, regeneration, and safety."""

from pathlib import Path
import pytest

from agent.client import MCPClient
from backend.generator import generate_mcp_server, parse_openapi, parse_openapi_file
from backend.generator.exceptions import OpenAPIValidationError

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"
BASELINE_SPEC = EXAMPLES_DIR / "evolution_baseline.yaml"
UPDATED_SPEC = EXAMPLES_DIR / "evolution_updated.yaml"


@pytest.mark.asyncio
async def test_specification_evolution_lifecycle(tmp_path: Path) -> None:
    """Full lifecycle: baseline generation -> tool discovery -> evolution -> regeneration -> verification."""
    target_dir = tmp_path / "evolved_server"

    # Step 1: Baseline generation
    api_v1 = parse_openapi_file(BASELINE_SPEC)
    res_v1 = generate_mcp_server(
        api=api_v1,
        output_dir=target_dir,
        package_name="evolved_server",
        overwrite=True,
    )
    server_script = res_v1.output_dir / "server.py"

    # Verify baseline tools via stdio client
    async with MCPClient(server_script=server_script) as client:
        tools_v1 = {t.name: t for t in await client.list_tools()}
        assert "list_items" in tools_v1
        assert "get_item" in tools_v1
        assert "create_item" in tools_v1
        assert "delete_item" in tools_v1
        assert "search_items" not in tools_v1

    # Step 2: Add custom user .env file
    user_env = res_v1.output_dir / ".env"
    user_env.write_text("API_SECRET_TOKEN=my_precious_secret\n", encoding="utf-8")

    # Step 3: Regenerate with updated specification (v2.0.0)
    api_v2 = parse_openapi_file(UPDATED_SPEC)
    res_v2 = generate_mcp_server(
        api=api_v2,
        output_dir=target_dir,
        package_name="evolved_server",
        overwrite=True,
    )

    # Verification: User .env was preserved!
    assert user_env.exists()
    assert "my_precious_secret" in user_env.read_text(encoding="utf-8")

    # Step 4: Discover tools from regenerated server
    async with MCPClient(server_script=server_script) as client:
        tools_v2 = {t.name: t for t in await client.list_tools()}

        # Newly added endpoint
        assert "search_items" in tools_v2

        # Removed endpoint no longer appears
        assert "delete_item" not in tools_v2

        # Renamed operationId
        assert "fetch_item_details" in tools_v2
        assert "get_item" not in tools_v2

        # Changed parameter schema reflected
        list_tool = tools_v2["list_items"]
        schema = list_tool.input_schema or {}
        props = schema.get("properties", {})
        assert "max_results" in props
        max_schema = props["max_results"]
        is_int = max_schema.get("type") == "integer" or any(
            s.get("type") == "integer" for s in max_schema.get("anyOf", [])
        )
        assert is_int
        assert max_schema.get("minimum") == 1
        assert max_schema.get("maximum") == 100


@pytest.mark.asyncio
async def test_invalid_update_preserves_valid_package(tmp_path: Path) -> None:
    """Verify that an invalid updated spec errors out and preserves the previous valid package."""
    target_dir = tmp_path / "protected_server"

    # Generate initial valid package
    api_v1 = parse_openapi_file(BASELINE_SPEC)
    res = generate_mcp_server(
        api=api_v1,
        output_dir=target_dir,
        package_name="protected_server",
        overwrite=True,
    )
    server_script = res.output_dir / "server.py"
    initial_server_code = server_script.read_text(encoding="utf-8")

    # Create local .env
    env_file = res.output_dir / ".env"
    env_file.write_text("DEV_KEY=123\n", encoding="utf-8")

    # Attempt to regenerate with an invalid OpenAPI specification (missing version)
    invalid_spec = "openapi: 3.0.3\ninfo:\n  title: Broken\npaths:\n  /test:\n    get:\n      responses:\n        '200':\n          description: ok\n"

    with pytest.raises(OpenAPIValidationError):
        bad_api = parse_openapi(invalid_spec)
        generate_mcp_server(bad_api, target_dir, overwrite=True)

    # Assert existing valid server code and .env were completely preserved
    assert server_script.exists()
    assert server_script.read_text(encoding="utf-8") == initial_server_code
    assert env_file.exists() and env_file.read_text(encoding="utf-8") == "DEV_KEY=123\n"

    # Assert existing server still runs and answers MCP requests
    async with MCPClient(server_script=server_script) as client:
        tools = await client.list_tools()
        assert len(tools) == 4


@pytest.mark.asyncio
async def test_evolution_read_only_preservation(tmp_path: Path) -> None:
    """Verify that regenerating in read-only mode exposes only safe GET operations."""
    target_dir = tmp_path / "ro_store_server"
    api_v2 = parse_openapi_file(UPDATED_SPEC)

    res = generate_mcp_server(
        api=api_v2,
        output_dir=target_dir,
        package_name="ro_store_server",
        read_only=True,
        overwrite=True,
    )
    server_script = res.output_dir / "server.py"

    async with MCPClient(server_script=server_script) as client:
        tools = {t.name for t in await client.list_tools()}
        assert tools == {"list_items", "search_items", "fetch_item_details"}
        assert "create_item" not in tools
