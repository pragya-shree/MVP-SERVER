"""Script to generate runnable MCP server package from Demo Task Management API OpenAPI spec."""

import argparse
import json
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.generator import generate_mcp_server, parse_openapi
from demo_api.app import app


def export_openapi_json(output_path: Path) -> dict:
    """Export the live OpenAPI spec dictionary and save to file."""
    spec = app.openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate runnable MCP server from Demo Task Management API specification."
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=REPO_ROOT / "generated" / "demo_task_mcp",
        help="Target output directory for generated MCP server (default: generated/demo_task_mcp)",
    )
    parser.add_argument(
        "--base-url",
        "-b",
        type=str,
        default="http://127.0.0.1:8000",
        help="Target API base URL for generated tools (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--read-only",
        "-r",
        action="store_true",
        help="Generate server in strict read-only mode (GET tools only)",
    )
    parser.add_argument(
        "--export-spec",
        type=Path,
        default=REPO_ROOT / "examples" / "demo_api_openapi.json",
        help="Path where OpenAPI JSON spec file should also be exported",
    )
    args = parser.parse_args()

    print("[INFO] Extracting OpenAPI specification from Demo Task Management API...")
    spec = export_openapi_json(args.export_spec)
    print(f"[INFO] Exported OpenAPI specification to {args.export_spec}")

    print(f"[INFO] Normalizing OpenAPI specification: '{spec['info']['title']}' v{spec['info']['version']}...")
    normalized_api = parse_openapi(spec)
    print(f"[INFO] Normalized {len(normalized_api.operations)} operations across {len(spec['paths'])} endpoints.")

    package_name = args.output.name or "demo_task_mcp"
    print(f"[INFO] Generating MCP server package '{package_name}' into '{args.output}'...")
    res = generate_mcp_server(
        api=normalized_api,
        output_dir=args.output,
        package_name=package_name,
        base_url=args.base_url,
        read_only=args.read_only,
        overwrite=True,
    )

    print("[SUCCESS] MCP Server package generated successfully!")
    print(f"  Package Directory: {res.output_dir}")
    print(f"  Configured Base URL: {res.base_url}")
    print(f"  Read-only mode: {res.read_only}")
    print(f"  Total tools generated ({len(res.tool_names)}):")
    for name in res.tool_names:
        print(f"    - {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
