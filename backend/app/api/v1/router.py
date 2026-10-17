"""Generator HTTP API v1 endpoints for validation, generation, tool inspection, and downloads."""

from datetime import datetime, timezone
import json
import re
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

from backend.app.api.v1.schemas import (
    GeneratorHealthResponse,
    OperationSummary,
    ServerGenerateRequest,
    ServerGenerateResponse,
    SpecValidateRequest,
    SpecValidateResponse,
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
