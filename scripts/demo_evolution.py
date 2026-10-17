"""Automated script demonstrating OpenAPI specification evolution and server regeneration."""

import asyncio
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.client import MCPClient
from backend.generator import generate_mcp_server, parse_openapi, parse_openapi_file
from backend.generator.exceptions import OpenAPIParserError, OpenAPIValidationError

BASELINE_SPEC_PATH = REPO_ROOT / "examples" / "evolution_baseline.yaml"
UPDATED_SPEC_PATH = REPO_ROOT / "examples" / "evolution_updated.yaml"
TARGET_OUTPUT_DIR = REPO_ROOT / "generated" / "store_mcp"


async def discover_tools_via_mcp_stdio(server_script: Path) -> dict[str, dict]:
    """Launch generated server via MCP stdio subprocess and return discovered tools mapping."""
    client = MCPClient(server_script=server_script)
    async with client:
        tools = await client.list_tools()
        return {t.name: {"description": t.description, "input_schema": t.input_schema} for t in tools}


async def main() -> int:
    print("=" * 75)
    print(" SPECIFICATION EVOLUTION & MCP SERVER REGENERATION WORKFLOW")
    print("=" * 75)

    # -------------------------------------------------------------------------
    # Phase 1: Baseline Generation
    # -------------------------------------------------------------------------
    print("\n[PHASE 1] Generating MCP server from baseline specification (v1.0.0)...")
    baseline_api = parse_openapi_file(BASELINE_SPEC_PATH)
    res_baseline = generate_mcp_server(
        api=baseline_api,
        output_dir=TARGET_OUTPUT_DIR,
        package_name="store_mcp",
        overwrite=True,
    )
    server_script = res_baseline.output_dir / "server.py"

    # Add a custom developer-configured .env to test preservation
    env_file = res_baseline.output_dir / ".env"
    env_file.write_text("CUSTOM_DEV_KEY=secret_api_key_12345\n", encoding="utf-8")
    print(f"  Generated server at: {server_script}")
    print(f"  Created developer .env file to verify preservation across updates.")

    # Discover baseline tools via actual MCP stdio
    tools_v1 = await discover_tools_via_mcp_stdio(server_script)
    print(f"  Discovered {len(tools_v1)} tools via MCP stdio protocol:")
    for name in sorted(tools_v1.keys()):
        print(f"    - {name}")

    assert "list_items" in tools_v1
    assert "get_item" in tools_v1
    assert "create_item" in tools_v1
    assert "delete_item" in tools_v1
    assert "search_items" not in tools_v1

    # -------------------------------------------------------------------------
    # Phase 2: Attempt Regeneration with Invalid Specification (Safety Check)
    # -------------------------------------------------------------------------
    print("\n[PHASE 2] Attempting regeneration with an invalid specification...")
    invalid_spec = "openapi: 3.0.3\ninfo:\n  title: Broken API\npaths:\n  /items:\n    get:\n      parameters:\n        - $ref: '#/components/parameters/NonexistentParam'\n"

    try:
        parsed_invalid = parse_openapi(invalid_spec)
        generate_mcp_server(parsed_invalid, TARGET_OUTPUT_DIR, overwrite=True)
        print("  [ERROR] Invalid spec unexpectedly succeeded!")
        return 1
    except (OpenAPIValidationError, OpenAPIParserError, Exception) as err:
        print(f"  [SAFETY CHECK PASSED] Invalid specification safely rejected: {err}")

    # Verify that existing generated server remains 100% intact and runnable
    tools_check = await discover_tools_via_mcp_stdio(server_script)
    assert set(tools_check.keys()) == set(tools_v1.keys())
    assert env_file.exists() and "secret_api_key_12345" in env_file.read_text(encoding="utf-8")
    print("  [VERIFIED] Existing server package and developer .env preserved intact.")

    # -------------------------------------------------------------------------
    # Phase 3: Regenerate Server from Updated Specification (v2.0.0)
    # -------------------------------------------------------------------------
    print("\n[PHASE 3] Regenerating server from evolved specification (v2.0.0)...")
    updated_api = parse_openapi_file(UPDATED_SPEC_PATH)
    res_updated = generate_mcp_server(
        api=updated_api,
        output_dir=TARGET_OUTPUT_DIR,
        package_name="store_mcp",
        overwrite=True,
    )
    print(f"  Regenerated server at: {res_updated.output_dir}")

    # Verify developer .env was preserved across regeneration
    assert env_file.exists(), ".env file was unexpectedly removed during regeneration!"
    assert "secret_api_key_12345" in env_file.read_text(encoding="utf-8"), ".env contents were overwritten!"
    print("  [PRESERVATION CONFIRMED] Local developer credentials in .env survived regeneration!")

    # Discover evolved tools via actual MCP stdio
    tools_v2 = await discover_tools_via_mcp_stdio(server_script)
    print(f"  Discovered {len(tools_v2)} tools via MCP stdio protocol:")
    for name in sorted(tools_v2.keys()):
        print(f"    - {name}")

    # Verification 1: Newly added endpoint becomes available as a tool
    assert "search_items" in tools_v2, "Expected newly added tool 'search_items' to be discovered!"
    print("  [VERIFIED] Newly added endpoint 'search_items' is now available as an MCP tool.")

    # Verification 2: Removed endpoint no longer appears
    assert "delete_item" not in tools_v2, "Removed operation 'delete_item' should no longer be present!"
    print("  [VERIFIED] Removed endpoint 'delete_item' no longer appears in tool discovery.")

    # Verification 3: Renamed operationId results in expected tool name
    assert "fetch_item_details" in tools_v2, "Expected renamed operation 'fetch_item_details'!"
    assert "get_item" not in tools_v2, "Old operationId 'get_item' should not appear!"
    print("  [VERIFIED] Renamed operationId 'get_item' -> 'fetch_item_details' reflected in MCP.")

    # Verification 4: Changed parameter schema reflected in discovered input schema
    list_items_schema = tools_v2["list_items"]["input_schema"]
    properties = list_items_schema.get("properties", {})
    assert "max_results" in properties, "Expected 'max_results' in list_items schema!"
    max_results_schema = properties["max_results"]
    is_integer_type = max_results_schema.get("type") == "integer" or any(
        s.get("type") == "integer" for s in max_results_schema.get("anyOf", [])
    )
    assert is_integer_type, f"Expected integer type in schema, got: {max_results_schema}"
    assert max_results_schema.get("minimum") == 1
    assert max_results_schema.get("maximum") == 100
    print("  [VERIFIED] Changed parameter schema ('max_results' integer with min 1, max 100) reflected.")

    # -------------------------------------------------------------------------
    # Phase 4: Read-Only Regeneration Mode
    # -------------------------------------------------------------------------
    print("\n[PHASE 4] Regenerating in strict read-only mode...")
    res_ro = generate_mcp_server(
        api=updated_api,
        output_dir=TARGET_OUTPUT_DIR,
        package_name="store_mcp",
        read_only=True,
        overwrite=True,
    )
    tools_ro = await discover_tools_via_mcp_stdio(server_script)
    print(f"  Discovered {len(tools_ro)} tools in read-only mode:")
    for name in sorted(tools_ro.keys()):
        print(f"    - {name}")

    assert "fetch_item_details" in tools_ro
    assert "list_items" in tools_ro
    assert "search_items" in tools_ro
    assert "create_item" not in tools_ro, "Mutation 'create_item' must not exist in read-only mode!"
    print("  [VERIFIED] Read-only mode correctly exposes strictly GET operations.")

    print("\n" + "=" * 75)
    print(" REGENERATION SUMMARY: WHAT IS PRESERVED VS REPLACED")
    print("=" * 75)
    print(" - REPLACED: server.py (tool handlers, schemas, route mappings)")
    print(" - REPLACED: README.md & requirements.txt (updated API docs & dependencies)")
    print(" - REPLACED: .env.example (updated environment template)")
    print(" - PRESERVED: .env (local developer credentials, secrets, tokens)")
    print(" - PRESERVED: Target package directory path and external caller bindings")
    print(" - ATOMIC GUARANTEE: Invalid specs reject before committing changes,")
    print("   leaving the previously working server 100% intact and operational.")
    print("=" * 75 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
