"""Command-line interface for the Anything-to-MCP OpenAPI generator."""

import argparse
from pathlib import Path
import sys
from typing import Optional, Sequence

from backend.generator.exceptions import OpenAPIParserError
from backend.generator.generator import generate_mcp_server
from backend.generator.parser import parse_openapi_file

CLI_VERSION = "0.1.0"


def create_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="anything-to-mcp",
        description="Convert OpenAPI 3.x specifications into self-contained, runnable MCP servers.",
    )

    parser.add_argument(
        "--spec",
        "-s",
        type=Path,
        help="Path to OpenAPI 3.x specification file (YAML or JSON).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("generated"),
        help="Target directory where the generated server package will be saved (default: ./generated).",
    )
    parser.add_argument(
        "--base-url",
        "-b",
        type=str,
        default=None,
        help="Override the default target API base URL for outgoing tool requests.",
    )
    parser.add_argument(
        "--package-name",
        "-n",
        type=str,
        default=None,
        help="Override the generated package name (default: derived from API title).",
    )
    parser.add_argument(
        "--read-only",
        "-r",
        action="store_true",
        default=False,
        help="Strict read-only mode: only expose HTTP GET operations as MCP tools.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        default=False,
        help="Refuse to overwrite an existing non-empty output directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Enable dry-run mode: intercept mutating operations without executing upstream HTTP requests.",
    )
    parser.add_argument(
        "--require-approval",
        action="store_true",
        default=False,
        help="Enable approval mode: require explicit human approval before executing mutating operations.",
    )
    parser.add_argument(
        "--mask-secrets",
        action="store_true",
        default=True,
        help="Enable multi-layer secret redaction for credentials, tokens, and sensitive headers (default: True).",
    )
    parser.add_argument(
        "--no-mask-secrets",
        action="store_false",
        dest="mask_secrets",
        help="Disable automatic secret masking (warning: increases credential exposure risk).",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"%(prog)s {CLI_VERSION}",
        help="Show program version and exit.",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI execution entrypoint."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.spec:
        parser.error("The following argument is required: --spec/-s")

    spec_path: Path = args.spec
    if not spec_path.exists():
        sys.stderr.write(f"Error: Specification file not found: {spec_path}\n")
        return 1

    try:
        # 1. Parse and validate OpenAPI document
        api = parse_openapi_file(spec_path)

        # 2. Generate MCP server package
        overwrite = not args.no_overwrite
        result = generate_mcp_server(
            api=api,
            output_dir=args.output,
            package_name=args.package_name,
            base_url=args.base_url,
            read_only=args.read_only,
            overwrite=overwrite,
            dry_run=args.dry_run,
            require_approval=args.require_approval,
            mask_secrets=args.mask_secrets,
        )

        mode_str = "Read-Only (GET only)" if result.read_only else "Full API"
        sys.stdout.write(
            f"Successfully generated MCP server!\n"
            f"  Package: {result.package_name}\n"
            f"  Location: {result.output_dir}\n"
            f"  Mode: {mode_str}\n"
            f"  Base URL: {result.base_url}\n"
            f"  Guardrails:\n"
            f"    - Dry-Run: {'Enabled' if result.dry_run else 'Disabled'}\n"
            f"    - Require Approval: {'Enabled' if result.require_approval else 'Disabled'}\n"
            f"    - Secret Masking: {'Enabled' if result.mask_secrets else 'Disabled'}\n"
            f"  Tools Generated ({result.operation_count}):\n"
        )
        for name in result.tool_names:
            sys.stdout.write(f"    - {name}\n")

        return 0

    except OpenAPIParserError as err:
        sys.stderr.write(f"Generation failed: {err}\n")
        return 1
    except Exception as err:
        sys.stderr.write(f"Unexpected error: {err}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
