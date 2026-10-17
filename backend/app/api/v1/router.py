"""Generator HTTP API v1 endpoints for validation, generation, tool inspection, and downloads."""

from datetime import datetime, timezone
import json
import re
from pathlib import Path as FilePath
import sys
from typing import Any, Optional
import urllib.parse

from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    Request,
    status,
)
from fastapi.responses import FileResponse

from agent.client import MCPClient
from backend.security import (
    PolicyDecision,
    global_approval_store,
    global_audit_logger,
    global_policy_engine,
)
from backend.security.redaction import global_redactor
from backend.app.api.v1.schemas import (
    ConnectionTestResponse,
    GeneratorHealthResponse,
    IntegrationConfigItem,
    IntegrationVariable,
    IntegrationsResponse,
    OperationSummary,
    ServerGenerateRequest,
    ServerGenerateResponse,
    SpecValidateRequest,
    SpecValidateResponse,
    ToolExecuteRequest,
    ToolExecuteResponse,
    ToolMetadata,
    ToolsInspectResponse,
)
from backend.app.services.storage import storage_service
from backend.generator import generate_mcp_server, parse_openapi
from backend.generator.exceptions import (
    GenerationError,
    OpenAPIParserError,
    OpenAPIReferenceError,
    OpenAPISyntaxError,
    OpenAPIValidationError,
    UnsupportedOpenAPIVersionError,
)
from backend.generator.generator import (
    build_operation_input_schema,
    build_tool_description,
    normalize_package_name,
)

MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB upload size limit

router = APIRouter(prefix="/api/v1", tags=["generator"])


@router.get(
    "/health",
    response_model=GeneratorHealthResponse,
    summary="Generator API health check",
    description="Returns operational health and version of the MCP generator service.",
)
async def get_generator_health() -> GeneratorHealthResponse:
    """Return health status of the generator service."""
    return GeneratorHealthResponse(
        status="ok",
        service="anything-to-mcp-generator",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post(
    "/specs/validate",
    response_model=SpecValidateResponse,
    summary="Validate an OpenAPI specification",
    description="Accepts YAML or JSON specification via file upload or JSON payload and checks syntax, version, and structure.",
)
async def validate_openapi_spec(request: Request) -> SpecValidateResponse:
    """Validate specification and report operation summary or errors."""
    content_type = request.headers.get("content-type", "").lower()
    raw_spec = ""

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded_file = form.get("file")
        if uploaded_file and hasattr(uploaded_file, "read"):
            content_bytes = await uploaded_file.read()
            if len(content_bytes) > MAX_UPLOAD_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"Uploaded specification exceeds maximum size limit of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.",
                )
            try:
                raw_spec = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return SpecValidateResponse(
                    valid=False,
                    errors=["Specification content could not be decoded as UTF-8."],
                )
        elif "spec" in form:
            raw_spec = str(form.get("spec"))
    elif "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                raw_spec = body.get("spec", "")
            elif isinstance(body, str):
                raw_spec = body
        except Exception as err:
            return SpecValidateResponse(valid=False, errors=[f"Malformed JSON request: {err}"])
    else:
        body_bytes = await request.body()
        if len(body_bytes) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Specification payload exceeds maximum size limit of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.",
            )
        try:
            raw_spec = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return SpecValidateResponse(valid=False, errors=["Payload could not be decoded as UTF-8."])

    if not raw_spec or not raw_spec.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No specification provided. Please upload a file or submit JSON payload.",
        )

    if len(raw_spec.encode("utf-8")) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Specification payload exceeds maximum size limit of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.",
        )

    try:
        api = parse_openapi(raw_spec)
        op_summaries = [
            OperationSummary(
                tool_name=op.tool_name,
                method=op.method,
                path=op.path,
                summary=op.summary,
                is_read_only=op.is_read_only,
                parameters_count=len(op.parameters),
                has_request_body=bool(op.request_body),
            )
            for op in api.operations
        ]
        return SpecValidateResponse(
            valid=True,
            title=api.title,
            version=api.version,
            operation_count=len(api.operations),
            operations=op_summaries,
            errors=[],
        )
    except (
        OpenAPISyntaxError,
        UnsupportedOpenAPIVersionError,
        OpenAPIValidationError,
        OpenAPIReferenceError,
        OpenAPIParserError,
    ) as err:
        return SpecValidateResponse(
            valid=False,
            errors=[str(err)],
        )
    except Exception as err:
        return SpecValidateResponse(
            valid=False,
            errors=[f"Unexpected validation error: {err}"],
        )


@router.post(
    "/servers/generate",
    response_model=ServerGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate an MCP server package",
    description="Generate a runnable MCP server package from an OpenAPI specification and prepare a ZIP archive for download.",
)
async def generate_server(request: Request) -> ServerGenerateResponse:
    """Generate server package and return metadata and download link."""
    content_type = request.headers.get("content-type", "").lower()
    raw_spec = ""
    req_base_url = None
    req_package_name = None
    req_read_only = False

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded_file = form.get("file")
        if uploaded_file and hasattr(uploaded_file, "read"):
            content_bytes = await uploaded_file.read()
            if len(content_bytes) > MAX_UPLOAD_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Uploaded file exceeds 5 MB size limit.",
                )
            try:
                raw_spec = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File content must be UTF-8 encoded text.",
                )
        elif "spec" in form:
            raw_spec = str(form.get("spec"))
        req_base_url = form.get("base_url")
        req_package_name = form.get("package_name")
        req_read_only = str(form.get("read_only", "false")).lower() in ("true", "1")
    elif "application/json" in content_type:
        try:
            body = await request.json()
            raw_spec = body.get("spec", "")
            req_base_url = body.get("base_url")
            req_package_name = body.get("package_name")
            req_read_only = bool(body.get("read_only", False))
        except Exception as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Malformed JSON request: {err}",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Specification must be provided via file upload or JSON payload.",
        )

    if not raw_spec or not raw_spec.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Specification must be provided via file upload or JSON payload.",
        )

    if len(raw_spec.encode("utf-8")) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Specification payload exceeds 5 MB size limit.",
        )

    # Validate package name security
    if req_package_name is not None:
        if not re.match(r"^[a-zA-Z0-9_]{1,64}$", req_package_name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid package_name: must be alphanumeric and underscores only, without path traversal.",
            )

    # Validate base URL security
    if req_base_url:
        parsed = urllib.parse.urlparse(req_base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid base_url: URL scheme must be http or https with a valid hostname.",
            )

    # Parse specification
    try:
        api = parse_openapi(raw_spec)
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OpenAPI parsing failed: {err}",
        )

    resolved_pkg_name = req_package_name or normalize_package_name(api.title)

    # Prepare isolated generation storage directory
    generation_id, package_dir = storage_service.create_generation_dir(resolved_pkg_name)

    # Generate MCP server package into isolated storage folder
    try:
        gen_result = generate_mcp_server(
            api=api,
            output_dir=package_dir,
            package_name=resolved_pkg_name,
            base_url=req_base_url,
            read_only=req_read_only,
            overwrite=True,
        )
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Server generation failed: {err}",
        )

    # Create ZIP archive
    try:
        storage_service.create_zip_archive(generation_id, resolved_pkg_name)
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create package ZIP archive: {err}",
        )

    # Build tools metadata list for inspection
    ops = api.read_only_operations if req_read_only else api.operations
    tools_list = [
        {
            "name": op.tool_name,
            "description": build_tool_description(op),
            "method": op.method,
            "path": op.path,
            "is_read_only": op.is_read_only,
            "input_schema": build_operation_input_schema(op),
        }
        for op in ops
    ]

    now_iso = datetime.now(timezone.utc).isoformat()
    metadata = {
        "generation_id": generation_id,
        "package_name": resolved_pkg_name,
        "api_title": api.title,
        "api_version": api.version,
        "read_only": req_read_only,
        "base_url": gen_result.base_url,
        "tool_count": len(gen_result.tool_names),
        "tool_names": gen_result.tool_names,
        "created_at": now_iso,
        "tools": tools_list,
    }

    # Persist metadata JSON
    storage_service.save_metadata(generation_id, metadata)

    return ServerGenerateResponse(
        generation_id=generation_id,
        package_name=resolved_pkg_name,
        api_title=api.title,
        api_version=api.version,
        read_only=req_read_only,
        base_url=gen_result.base_url,
        tool_count=len(gen_result.tool_names),
        tool_names=gen_result.tool_names,
        download_url=f"/api/v1/servers/{generation_id}/download",
        created_at=now_iso,
    )


@router.get(
    "/servers/{generation_id}/tools",
    response_model=ToolsInspectResponse,
    summary="Inspect tools of a generated MCP server",
    description="Retrieve actual tool definitions, descriptions, HTTP methods, paths, and input schemas for a generation run.",
)
async def inspect_generated_tools(
    generation_id: str = Path(..., description="UUID identifier of the generation run"),
) -> ToolsInspectResponse:
    """Retrieve tool metadata for a generation run."""
    try:
        storage_service.validate_generation_id(generation_id)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))

    metadata = storage_service.get_metadata(generation_id)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation run '{generation_id}' not found or expired.",
        )

    tools_models = [
        ToolMetadata(
            name=t["name"],
            description=t["description"],
            method=t["method"],
            path=t["path"],
            is_read_only=t["is_read_only"],
            input_schema=t["input_schema"],
        )
        for t in metadata.get("tools", [])
    ]

    return ToolsInspectResponse(
        generation_id=generation_id,
        package_name=metadata["package_name"],
        tool_count=len(tools_models),
        tools=tools_models,
    )


@router.get(
    "/servers/{generation_id}/download",
    summary="Download generated MCP server ZIP package",
    description="Download the generated package containing server.py, README.md, requirements.txt, and .env.example as a ZIP archive.",
)
async def download_server_package(
    generation_id: str = Path(..., description="UUID identifier of the generation run"),
) -> FileResponse:
    """Download ZIP archive of the generated server."""
    try:
        storage_service.validate_generation_id(generation_id)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))

    zip_info = storage_service.get_zip_path(generation_id)
    if not zip_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generated server package for '{generation_id}' not found or expired.",
        )

    zip_path, filename = zip_info
    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def generate_client_integrations(
    generation_id: str,
    metadata: dict[str, Any],
    server_script: FilePath,
) -> IntegrationsResponse:
    """Construct verified client configurations with security placeholders."""
    pkg_name = metadata.get("package_name", "mcp_server")
    base_url = metadata.get("base_url", "http://localhost:8000")
    read_only = bool(metadata.get("read_only", False))
    raw_script_path = str(server_script)

    common_env_vars = [
        IntegrationVariable(
            name="TARGET_BASE_URL",
            description="Upstream API base URL that the MCP server dispatches requests to",
            required=True,
            placeholder=base_url,
        ),
        IntegrationVariable(
            name="BEARER_TOKEN",
            description="Bearer token for HTTP Authorization header (if target API requires auth)",
            required=False,
            placeholder="${YOUR_BEARER_TOKEN}",
        ),
        IntegrationVariable(
            name="API_KEY",
            description="API key for custom headers (if target API requires auth)",
            required=False,
            placeholder="${YOUR_API_KEY}",
        ),
        IntegrationVariable(
            name="DRY_RUN",
            description="When 'true', intercepts mutating operations without sending upstream requests",
            required=False,
            placeholder="false",
        ),
        IntegrationVariable(
            name="REQUIRE_APPROVAL",
            description="When 'true', requires explicit approval tokens for mutating operations",
            required=False,
            placeholder="false",
        ),
        IntegrationVariable(
            name="MASK_SECRETS",
            description="When 'true', redacts sensitive credentials and tokens in logs and results",
            required=False,
            placeholder="true",
        ),
    ]

    # 1. Claude Desktop configuration
    claude_desktop_snippet = json.dumps(
        {
            "mcpServers": {
                pkg_name: {
                    "command": "python",
                    "args": [raw_script_path],
                    "env": {
                        "TARGET_BASE_URL": base_url,
                        "BEARER_TOKEN": "${YOUR_BEARER_TOKEN}",
                        "API_KEY": "${YOUR_API_KEY}",
                        "MASK_SECRETS": "true",
                    },
                }
            }
        },
        indent=2,
    )

    claude_desktop = IntegrationConfigItem(
        id="claude-desktop",
        name="Claude Desktop",
        transport="stdio",
        format="json",
        target_file="~/Library/Application Support/Claude/claude_desktop_config.json (macOS) or %APPDATA%\\Claude\\claude_desktop_config.json (Windows)",
        snippet=claude_desktop_snippet,
        prerequisites=[
            "Claude Desktop app installed",
            "Python 3.10+ installed and available in PATH",
            "Dependencies installed (pip install -r requirements.txt)",
        ],
        setup_steps=[
            "Locate and open your Claude Desktop configuration file.",
            f'Add the "{pkg_name}" definition under the "mcpServers" object.',
            "Replace ${YOUR_BEARER_TOKEN} or ${YOUR_API_KEY} with your credentials if required.",
            "Restart Claude Desktop to load the server and discover tools.",
        ],
        environment_variables=common_env_vars,
        is_available=True,
        notes="Uses standard local stdio transport. Claude Desktop spawns the server as a local child process.",
    )

    # 2. Claude Code CLI configuration
    claude_code_snippet = (
        f"claude mcp add {pkg_name} \\\n"
        f'  -e TARGET_BASE_URL="{base_url}" \\\n'
        f'  -e BEARER_TOKEN="${{YOUR_BEARER_TOKEN}}" \\\n'
        f'  -- python "{raw_script_path}"'
    )

    claude_code = IntegrationConfigItem(
        id="claude-code",
        name="Claude Code",
        transport="stdio",
        format="bash",
        target_file=None,
        snippet=claude_code_snippet,
        prerequisites=[
            "Claude Code CLI installed (npm install -g @anthropic-ai/claude-code)",
            "Python 3.10+ installed",
        ],
        setup_steps=[
            "Run the 'claude mcp add' command in your terminal.",
            "Provide real authentication values in environment variables if required.",
            "Verify registration with 'claude mcp list'.",
        ],
        environment_variables=common_env_vars,
        is_available=True,
        notes="Spawns local Python process over stdio pipes.",
    )

    # 3. Cursor configuration
    cursor_snippet = json.dumps(
        {
            "mcpServers": {
                pkg_name: {
                    "command": "python",
                    "args": [raw_script_path],
                    "env": {
                        "TARGET_BASE_URL": base_url,
                        "BEARER_TOKEN": "${YOUR_BEARER_TOKEN}",
                        "API_KEY": "${YOUR_API_KEY}",
                    },
                }
            }
        },
        indent=2,
    )

    cursor = IntegrationConfigItem(
        id="cursor",
        name="Cursor",
        transport="stdio",
        format="json",
        target_file=".cursor/mcp.json",
        snippet=cursor_snippet,
        prerequisites=[
            "Cursor IDE (0.40+)",
            "MCP support enabled in Cursor Settings",
            "Python 3.10+ in workspace environment",
        ],
        setup_steps=[
            "Create or edit .cursor/mcp.json in your workspace root.",
            "Paste the JSON configuration into the mcpServers map.",
            "Set environment variables for authentication if needed.",
            "Open Cursor Settings > Features > MCP to verify the server status.",
        ],
        environment_variables=common_env_vars,
        is_available=True,
        notes="Configured per-workspace in .cursor/mcp.json or globally in Cursor Settings.",
    )

    # 4. VS Code configuration
    vscode_snippet = json.dumps(
        {
            "mcpServers": {
                pkg_name: {
                    "command": "python",
                    "args": [raw_script_path],
                    "env": {
                        "TARGET_BASE_URL": base_url,
                        "BEARER_TOKEN": "${YOUR_BEARER_TOKEN}",
                        "API_KEY": "${YOUR_API_KEY}",
                    },
                }
            }
        },
        indent=2,
    )

    vscode = IntegrationConfigItem(
        id="vscode",
        name="VS Code",
        transport="stdio",
        format="json",
        target_file="mcp_settings.json (Cline / Roo Code settings)",
        snippet=vscode_snippet,
        prerequisites=[
            "VS Code with an MCP-capable assistant extension (e.g. Cline, Roo Code, or Continue)",
            "Python 3.10+",
        ],
        setup_steps=[
            "Open extension MCP settings in VS Code.",
            "Add the server definition under mcpServers.",
            "Supply any required API credentials.",
            "Save configuration and click Reconnect.",
        ],
        environment_variables=common_env_vars,
        is_available=True,
        notes="Works seamlessly with Roo Code, Cline, and any VS Code extension adhering to the standard MCP schema.",
    )

    # 5. Local / stdio execution
    stdio_snippet = f"""# 1. Unzip the downloaded package:
unzip {pkg_name}.zip -d {pkg_name}
cd {pkg_name}

# 2. Create and activate a virtual environment:
python -m venv .venv
# On Windows:
.venv\\Scripts\\activate
# On macOS/Linux:
source .venv/bin/activate

# 3. Install required dependencies:
pip install -r requirements.txt

# 4. Configure environment credentials:
cp .env.example .env
# Edit .env and supply TARGET_BASE_URL, BEARER_TOKEN, or API_KEY

# 5. Start MCP server over stdio:
python server.py"""

    stdio = IntegrationConfigItem(
        id="stdio",
        name="Local / stdio",
        transport="stdio",
        format="bash",
        target_file=None,
        snippet=stdio_snippet,
        prerequisites=[
            "Python 3.10+",
            "Extracted package archive",
        ],
        setup_steps=[
            "Extract the generated ZIP archive.",
            "Initialize Python venv and install dependencies from requirements.txt.",
            "Configure credentials in local .env.",
            "Execute server.py. It will listen for JSON-RPC messages on stdin/stdout.",
        ],
        environment_variables=common_env_vars,
        is_available=True,
        notes="Standard local process transport. Communicates over stdin/stdout using MCP JSON-RPC protocol.",
    )

    # 6. Docker container
    docker_snippet = f"""# 1. Build Docker image from extracted package:
docker build -t {pkg_name}:latest .

# 2. Run container in interactive stdio mode:
docker run -i --rm \\
  -e TARGET_BASE_URL="{base_url}" \\
  -e BEARER_TOKEN="${{YOUR_BEARER_TOKEN}}" \\
  {pkg_name}:latest"""

    docker = IntegrationConfigItem(
        id="docker",
        name="Docker",
        transport="stdio",
        format="bash",
        target_file="Dockerfile",
        snippet=docker_snippet,
        prerequisites=[
            "Docker Engine 20.10+",
            "Extracted package directory",
        ],
        setup_steps=[
            "Ensure package contains Dockerfile and requirements.txt.",
            "Build container image using 'docker build'.",
            "Launch container with '-i' flag so stdin/stdout are attached for MCP JSON-RPC.",
        ],
        environment_variables=common_env_vars,
        is_available=True,
        notes="Container must be executed interactively (-i) so the MCP client can communicate over stdio.",
    )

    # 7. Hosted MCP
    hosted_snippet = (
        "# Hosted MCP Execution Status: Not Available (stdio Transport Only)\n"
        "# \n"
        "# This generated server is built for local stdio transport.\n"
        "# Remote SSE / HTTP streaming transport is currently not deployed on this instance.\n"
        "# To connect remotely, run the server locally or in a container with an SSE bridge."
    )

    hosted = IntegrationConfigItem(
        id="hosted",
        name="Hosted MCP",
        transport="http",
        format="text",
        target_file=None,
        snippet=hosted_snippet,
        prerequisites=[
            "Remote MCP streaming gateway (SSE/HTTP bridge)",
        ],
        setup_steps=[
            "Generated servers in this version use local stdio transport.",
            "If remote hosting is needed, deploy the server container with an MCP SSE proxy.",
        ],
        environment_variables=common_env_vars,
        is_available=False,
        notes="Hosted remote MCP execution is not currently deployed. Generated servers use local stdio transport.",
    )

    return IntegrationsResponse(
        generation_id=generation_id,
        package_name=pkg_name,
        server_path=raw_script_path,
        base_url=base_url,
        read_only=read_only,
        available_transports=["stdio"],
        integrations=[claude_desktop, claude_code, cursor, vscode, stdio, docker, hosted],
    )


@router.post(
    "/servers/{generation_id}/test-connection",
    response_model=ConnectionTestResponse,
    summary="Test generated MCP server connection and tool discovery",
    description="Safely launches the generated server process over stdio, initializes MCP session, discovers tools, and terminates cleanly.",
)
async def test_server_connection(
    generation_id: str = Path(..., description="UUID identifier of the generation run"),
) -> ConnectionTestResponse:
    """Test connection and tool discovery for a generated MCP server over stdio."""
    try:
        storage_service.validate_generation_id(generation_id)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))

    metadata = storage_service.get_metadata(generation_id)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation run '{generation_id}' not found or expired.",
        )

    package_name = metadata.get("package_name", "server")
    gen_dir = storage_service.get_generation_dir(generation_id)
    if not gen_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation directory for '{generation_id}' not found.",
        )

    server_script = (gen_dir / package_name / "server.py").resolve()
    if not server_script.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generated server script '{server_script.name}' not found.",
        )

    tested_at = datetime.now(timezone.utc).isoformat()
    client = MCPClient(
        server_script=str(server_script),
        command=sys.executable,
        args=[str(server_script)],
        timeout=15.0,
    )

    try:
        await client.connect()
        discovered = await client.list_tools()
        tool_names = [t.name for t in discovered]

        # Log sanitized tool verification event
        global_audit_logger.record(
            tool_name="mcp_connection_test",
            method="MCP_INIT",
            path=f"/servers/{generation_id}/test-connection",
            policy_decision="ALLOW",
            execution_status="EXECUTED",
            is_mutating=False,
            arguments={"server_name": package_name, "transport": "stdio", "tool_count": len(tool_names)},
            reason=f"Tested stdio MCP connection and discovered {len(tool_names)} tools.",
            status_code=200,
        )

        transport_name = "stdio" if not getattr(client, "_in_process_mode", False) else "in-process"
        return ConnectionTestResponse(
            success=True,
            generation_id=generation_id,
            package_name=package_name,
            transport=transport_name,
            tool_count=len(tool_names),
            discovered_tools=tool_names,
            tested_at=tested_at,
            message=f"Successfully initialized MCP {transport_name} session and discovered {len(tool_names)} tools.",
            error=None,
        )
    except Exception as err:
        raw_error = str(err)
        sanitized_error, _ = global_redactor.redact_text(raw_error)

        global_audit_logger.record(
            tool_name="mcp_connection_test",
            method="MCP_INIT",
            path=f"/servers/{generation_id}/test-connection",
            policy_decision="ALLOW",
            execution_status="FAILED",
            is_mutating=False,
            arguments={"server_name": package_name, "transport": "stdio", "error": sanitized_error},
            reason=f"MCP connection test failed: {sanitized_error}",
            status_code=500,
        )

        return ConnectionTestResponse(
            success=False,
            generation_id=generation_id,
            package_name=package_name,
            transport="stdio",
            tool_count=0,
            discovered_tools=[],
            tested_at=tested_at,
            message="Failed to establish MCP connection or discover tools.",
            error=sanitized_error,
        )
    finally:
        await client.close()


@router.get(
    "/servers/{generation_id}/integrations",
    response_model=IntegrationsResponse,
    summary="Get integration configurations for supported MCP clients",
    description="Returns copyable configurations and setup instructions for Claude Code, Claude Desktop, Cursor, VS Code, stdio, and Docker.",
)
async def get_server_integrations(
    generation_id: str = Path(..., description="UUID identifier of the generation run"),
) -> IntegrationsResponse:
    """Retrieve integration configurations for a generated server."""
    try:
        storage_service.validate_generation_id(generation_id)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))

    metadata = storage_service.get_metadata(generation_id)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation run '{generation_id}' not found or expired.",
        )

    package_name = metadata.get("package_name", "server")
    gen_dir = storage_service.get_generation_dir(generation_id)
    if not gen_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation directory for '{generation_id}' not found.",
        )

    server_script = (gen_dir / package_name / "server.py").resolve()
    if not server_script.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generated server script '{server_script.name}' not found.",
        )

    return generate_client_integrations(generation_id, metadata, server_script)


@router.post(
    "/servers/{generation_id}/execute-tool",
    response_model=ToolExecuteResponse,
    summary="Execute an individual tool against a generated MCP server",
    description="Invokes a specific tool on the generated server over stdio with full policy engine evaluation, argument sanitization, and audit logging.",
)
async def execute_server_tool(
    payload: ToolExecuteRequest,
    generation_id: str = Path(..., description="UUID identifier of the generation run"),
) -> ToolExecuteResponse:
    """Execute a specific MCP tool with arguments, enforcing all security guardrails."""
    try:
        storage_service.validate_generation_id(generation_id)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))

    metadata = storage_service.get_metadata(generation_id)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation run '{generation_id}' not found or expired.",
        )

    # Locate tool metadata
    tools = metadata.get("tools", [])
    tool_meta = next((t for t in tools if t.get("name") == payload.tool_name), None)
    if not tool_meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{payload.tool_name}' not found in generated server '{metadata.get('package_name')}'.",
        )

    method = str(tool_meta.get("method", "GET")).upper()
    path = str(tool_meta.get("path", ""))
    is_mutating = method in ("POST", "PUT", "PATCH", "DELETE")
    package_name = metadata.get("package_name", "server")

    # Evaluate security policy
    eval_res = global_policy_engine.evaluate(
        tool_name=payload.tool_name,
        method=method,
        path=path,
    )
    decision = eval_res.decision

    # Guardrail 1: Policy Deny (Absolute precedence)
    if decision == PolicyDecision.DENY:
        global_audit_logger.record(
            tool_name=payload.tool_name,
            method=method,
            path=path,
            policy_decision="DENY",
            execution_status="BLOCKED",
            is_mutating=is_mutating,
            arguments=payload.arguments,
            reason=f"Operation '{payload.tool_name}' is forbidden by security policy.",
            status_code=403,
        )
        return ToolExecuteResponse(
            success=False,
            generation_id=generation_id,
            tool_name=payload.tool_name,
            arguments=payload.arguments,
            is_error=True,
            policy_decision="DENY",
            execution_status="BLOCKED",
            error=f"Operation '{payload.tool_name}' ({method} {path}) is forbidden by security policy.",
        )

    # Guardrail 2: Dry-Run Mode Interception
    if decision == PolicyDecision.DRY_RUN and is_mutating:
        safe_args, _ = global_redactor.redact_json(payload.arguments)
        global_audit_logger.record(
            tool_name=payload.tool_name,
            method=method,
            path=path,
            policy_decision="DRY_RUN",
            execution_status="DRY-RUN",
            is_mutating=True,
            arguments=safe_args,
            reason="Dry-run mode intercepted mutating request before dispatch.",
            status_code=200,
        )
        return ToolExecuteResponse(
            success=True,
            generation_id=generation_id,
            tool_name=payload.tool_name,
            arguments=safe_args,
            is_error=False,
            policy_decision="DRY_RUN",
            execution_status="DRY-RUN",
            result={
                "status": "DRY_RUN_INTERCEPTED",
                "action": f"{method} {path}",
                "message": "Dry-run mode is enabled. The upstream request was not sent.",
                "method": method,
                "path": path,
                "arguments": safe_args,
                "is_mutating": True,
            },
            content=f"Dry-run mode intercepted {method} {path}. Upstream request was not sent.",
        )

    # Guardrail 3: Explicit Human Approval Mode
    if decision == PolicyDecision.REQUIRE_APPROVAL and is_mutating:
        if not payload.approval_id:
            req = global_approval_store.create_request(
                tool_name=payload.tool_name,
                method=method,
                path=path,
                arguments=payload.arguments,
                reason=f"Mutating operation {method} {path} requires human approval",
            )
            safe_args, _ = global_redactor.redact_json(payload.arguments)
            global_audit_logger.record(
                tool_name=payload.tool_name,
                method=method,
                path=path,
                policy_decision="REQUIRE_APPROVAL",
                execution_status="PENDING APPROVAL",
                is_mutating=True,
                arguments=safe_args,
                reason="Pending human approval confirmation.",
                status_code=202,
                approval_id=req.approval_id,
            )
            return ToolExecuteResponse(
                success=False,
                generation_id=generation_id,
                tool_name=payload.tool_name,
                arguments=safe_args,
                is_error=False,
                requires_approval=True,
                approval_id=req.approval_id,
                policy_decision="REQUIRE_APPROVAL",
                execution_status="PENDING APPROVAL",
                pending_action={
                    "tool_name": payload.tool_name,
                    "method": method,
                    "path": path,
                    "arguments": safe_args,
                    "approval_id": req.approval_id,
                    "expires_at": req.expires_at,
                },
                error=f"Approval required to execute {method} {path}. Re-invoke with approval_id='{req.approval_id}'.",
            )
        else:
            valid, msg, _bound_args = global_approval_store.consume_and_verify(
                approval_id=payload.approval_id,
                tool_name=payload.tool_name,
                arguments=payload.arguments,
            )
            if not valid:
                global_audit_logger.record(
                    tool_name=payload.tool_name,
                    method=method,
                    path=path,
                    policy_decision="REQUIRE_APPROVAL",
                    execution_status="FAILED",
                    is_mutating=True,
                    arguments=payload.arguments,
                    reason=f"Approval verification failed: {msg}",
                    status_code=403,
                )
                return ToolExecuteResponse(
                    success=False,
                    generation_id=generation_id,
                    tool_name=payload.tool_name,
                    arguments=payload.arguments,
                    is_error=True,
                    policy_decision="REQUIRE_APPROVAL",
                    execution_status="FAILED",
                    error=msg,
                )

    # Locate server.py script
    gen_dir = storage_service.get_generation_dir(generation_id)
    if not gen_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation directory for '{generation_id}' not found.",
        )

    server_script = (gen_dir / package_name / "server.py").resolve()
    if not server_script.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generated server script '{server_script.name}' not found.",
        )

    # Invoke tool via MCPClient
    client = MCPClient(
        server_script=str(server_script),
        command=sys.executable,
        args=[str(server_script)],
        timeout=25.0,
    )

    call_args = dict(payload.arguments)
    if payload.approval_id:
        call_args["approval_id"] = payload.approval_id

    try:
        await client.connect()
        tool_res = await client.call_tool(payload.tool_name, call_args)

        # Redact secrets in raw_data or content
        sanitized_data = tool_res.raw_data
        redactions_data = 0
        if isinstance(tool_res.raw_data, (dict, list)):
            sanitized_data, redactions_data = global_redactor.redact_json(tool_res.raw_data)

        sanitized_text = tool_res.content or ""
        redactions_text = 0
        if isinstance(tool_res.content, str):
            sanitized_text, redactions_text = global_redactor.redact_text(tool_res.content)

        total_redactions = redactions_data + redactions_text
        has_redactions = total_redactions > 0

        # Extract message / error if present in sanitized_data
        err_msg = None
        if tool_res.is_error:
            if isinstance(sanitized_data, dict) and sanitized_data.get("message"):
                err_msg = str(sanitized_data["message"])
            else:
                err_msg = sanitized_text or "Tool execution failed"

        status_code = tool_res.status_code or (200 if not tool_res.is_error else 500)

        global_audit_logger.record(
            tool_name=payload.tool_name,
            method=method,
            path=path,
            policy_decision=decision.value,
            execution_status="EXECUTED" if not tool_res.is_error else "FAILED",
            is_mutating=is_mutating,
            arguments=payload.arguments,
            status_code=status_code,
            secrets_redacted=has_redactions,
            redaction_count=total_redactions,
            approval_id=payload.approval_id,
            reason=f"Executed tool '{payload.tool_name}' through MCP stdio transport",
        )

        return ToolExecuteResponse(
            success=not tool_res.is_error,
            generation_id=generation_id,
            tool_name=payload.tool_name,
            arguments=payload.arguments,
            result=sanitized_data,
            content=sanitized_text,
            is_error=tool_res.is_error,
            status_code=status_code,
            policy_decision=decision.value,
            execution_status="EXECUTED" if not tool_res.is_error else "FAILED",
            secrets_redacted=has_redactions,
            redaction_count=total_redactions,
            error=err_msg,
        )
    except Exception as err:
        raw_error = str(err)
        sanitized_error, _ = global_redactor.redact_text(raw_error)

        global_audit_logger.record(
            tool_name=payload.tool_name,
            method=method,
            path=path,
            policy_decision=decision.value,
            execution_status="FAILED",
            is_mutating=is_mutating,
            arguments=payload.arguments,
            reason=f"Execution failed: {sanitized_error}",
            status_code=500,
        )

        return ToolExecuteResponse(
            success=False,
            generation_id=generation_id,
            tool_name=payload.tool_name,
            arguments=payload.arguments,
            is_error=True,
            policy_decision=decision.value,
            execution_status="FAILED",
            error=sanitized_error,
        )
    finally:
        await client.close()


