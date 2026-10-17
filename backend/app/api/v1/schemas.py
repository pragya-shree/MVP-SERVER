"""Pydantic schemas for Generator HTTP API v1."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class OperationSummary(BaseModel):
    """Summary of an operation exposed by an OpenAPI specification."""

    tool_name: str = Field(description="Normalized MCP tool identifier")
    method: str = Field(description="HTTP method (GET, POST, etc.)")
    path: str = Field(description="Endpoint path route")
    summary: Optional[str] = Field(default=None, description="Short operation description")
    is_read_only: bool = Field(description="Whether operation is safe read-only GET")
    parameters_count: int = Field(default=0, description="Number of parameters required or optional")
    has_request_body: bool = Field(default=False, description="Whether operation defines a request body")


class SpecValidateResponse(BaseModel):
    """Result of validating an OpenAPI specification."""

    valid: bool = Field(description="True if specification is structurally and semantically valid")
    title: Optional[str] = Field(default=None, description="API title from spec info")
    version: Optional[str] = Field(default=None, description="API version from spec info")
    operation_count: int = Field(default=0, description="Total supported operations parsed")
    operations: list[OperationSummary] = Field(default_factory=list, description="List of parsed operations")
    errors: list[str] = Field(default_factory=list, description="Validation errors if invalid")


class SpecValidateRequest(BaseModel):
    """Payload for validating a raw OpenAPI specification string."""

    spec: str = Field(description="OpenAPI 3.x specification text in YAML or JSON format")


class ServerGenerateRequest(BaseModel):
    """Payload for generating an MCP server from a specification string."""

    spec: str = Field(description="OpenAPI 3.x specification text in YAML or JSON format")
    base_url: Optional[str] = Field(default=None, description="Optional override for target API base URL")
    package_name: Optional[str] = Field(default=None, description="Optional override for generated package name")
    read_only: bool = Field(default=False, description="Strict read-only mode (exposes only GET tools)")


class ToolMetadata(BaseModel):
    """Metadata for an individual generated MCP tool."""

    name: str = Field(description="MCP tool name")
    description: str = Field(description="Tool description and usage documentation")
    method: str = Field(description="Underlying HTTP method")
    path: str = Field(description="Underlying API path")
    is_read_only: bool = Field(description="Whether tool is read-only")
    input_schema: dict[str, Any] = Field(default_factory=dict, description="JSON Schema for tool inputs")


class ServerGenerateResponse(BaseModel):
    """Result metadata for a generated MCP server package."""

    generation_id: str = Field(description="Unique generation run UUID")
    package_name: str = Field(description="Name of the generated server package")
    api_title: str = Field(description="API title derived from specification")
    api_version: str = Field(description="API version derived from specification")
    read_only: bool = Field(description="Whether server exposes only read-only tools")
    base_url: str = Field(description="Configured target API base URL")
    tool_count: int = Field(description="Total number of MCP tools exposed")
    tool_names: list[str] = Field(description="List of exposed tool names")
    download_url: str = Field(description="URL endpoint to download the generated ZIP archive")
    created_at: str = Field(description="ISO timestamp of generation")


class ToolsInspectResponse(BaseModel):
    """Tool metadata inspection payload for a generation run."""

    generation_id: str = Field(description="Generation run identifier")
    package_name: str = Field(description="Package name")
    tool_count: int = Field(description="Number of tools")
    tools: list[ToolMetadata] = Field(description="List of detailed tool definitions")


class GeneratorHealthResponse(BaseModel):
    """Health status response schema for generator API."""

    status: str = Field(default="ok", description="Health status indicator")
    service: str = Field(default="anything-to-mcp-generator", description="Service identifier")
    version: str = Field(default="0.1.0", description="Service version")
    timestamp: str = Field(description="Current server timestamp")
