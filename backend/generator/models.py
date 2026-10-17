from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class NormalizedParameter(BaseModel):
    """Normalized API parameter for path, query, header, or cookie."""

    name: str = Field(description="Parameter name")
    in_: str = Field(alias="in", description="Parameter location: path, query, header, or cookie")
    description: Optional[str] = Field(default=None, description="Human-readable parameter description")
    required: bool = Field(default=False, description="Whether this parameter is required")
    deprecated: bool = Field(default=False, description="Whether this parameter is deprecated")
    schema_: Optional[dict[str, Any]] = Field(
        default=None,
        alias="schema",
        description="Preserved full JSON schema (including types, enums, defaults, formats)",
    )

    model_config = ConfigDict(populate_by_name=True)

    @property
    def is_path(self) -> bool:
        """Return True if parameter is located in path."""
        return self.in_ == "path"

    @property
    def is_query(self) -> bool:
        """Return True if parameter is located in query."""
        return self.in_ == "query"

    @property
    def is_header(self) -> bool:
        """Return True if parameter is located in header."""
        return self.in_ == "header"

    @property
    def is_cookie(self) -> bool:
        """Return True if parameter is located in cookie."""
        return self.in_ == "cookie"

    @property
    def param_type(self) -> Optional[str]:
        """Return declared schema type if available."""
        if self.schema_ and isinstance(self.schema_, dict):
            return self.schema_.get("type")
        return None


class NormalizedRequestBody(BaseModel):
    """Normalized request body metadata and payload schema."""

    description: Optional[str] = Field(default=None, description="Request body description")
    required: bool = Field(default=False, description="Whether the request body is required")
    content_types: list[str] = Field(default_factory=list, description="Supported request content types")
    schema_: Optional[dict[str, Any]] = Field(
        default=None,
        alias="schema",
        description="Primary request body JSON schema (typically application/json)",
    )
    content_schemas: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Mapping of content-type to full resolved schema",
    )

    model_config = ConfigDict(populate_by_name=True)


class NormalizedResponse(BaseModel):
    """Normalized HTTP response metadata and schema."""

    status_code: str = Field(description="HTTP status code or 'default'")
    description: str = Field(default="", description="Response description")
    content_types: list[str] = Field(default_factory=list, description="Supported response content types")
    schema_: Optional[dict[str, Any]] = Field(
        default=None,
        alias="schema",
        description="Primary response body JSON schema",
    )
    content_schemas: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Mapping of content-type to response schema",
    )

    model_config = ConfigDict(populate_by_name=True)


class SecurityScheme(BaseModel):
    """Normalized security scheme definition."""

    type: str = Field(description="Type: apiKey, http, oauth2, openIdConnect")
    description: Optional[str] = Field(default=None, description="Scheme description")
    name: Optional[str] = Field(default=None, description="Header/query/cookie parameter name for apiKey")
    in_: Optional[str] = Field(default=None, alias="in", description="Location for apiKey: header, query, cookie")
    scheme: Optional[str] = Field(default=None, description="HTTP authorization scheme: bearer, basic, etc.")
    bearer_format: Optional[str] = Field(default=None, alias="bearerFormat", description="Bearer token format")
    flows: Optional[dict[str, Any]] = Field(default=None, description="OAuth2 flows configuration")
    open_id_connect_url: Optional[str] = Field(
        default=None,
        alias="openIdConnectUrl",
        description="OpenID Connect discovery URL",
    )

    model_config = ConfigDict(populate_by_name=True)


class NormalizedOperation(BaseModel):
    """Normalized API operation containing all metadata required to generate an MCP tool."""

    operation_id: Optional[str] = Field(default=None, description="Original OpenAPI operationId if present")
    tool_name: str = Field(description="Deterministic normalized unique MCP tool name")
    method: str = Field(description="HTTP method (uppercase: GET, POST, PUT, DELETE, etc.)")
    path: str = Field(description="Original URI path template")
    summary: Optional[str] = Field(default=None, description="Short summary of the operation")
    description: Optional[str] = Field(default=None, description="Detailed operation description")
    tags: list[str] = Field(default_factory=list, description="Categorization tags")
    deprecated: bool = Field(default=False, description="Whether the operation is deprecated")
    parameters: list[NormalizedParameter] = Field(
        default_factory=list,
        description="Merged path and operation-level parameters",
    )
    request_body: Optional[NormalizedRequestBody] = Field(
        default=None,
        description="Normalized request body specification",
    )
    responses: dict[str, NormalizedResponse] = Field(
        default_factory=dict,
        description="Status code to response mapping",
    )
    security: list[dict[str, list[str]]] = Field(
        default_factory=list,
        description="Effective security requirements (accounting for global rules and overrides)",
    )
    declared_security: Optional[list[dict[str, list[str]]]] = Field(
        default=None,
        description="Explicit operation-level security, or None if inherited from global",
    )

    @property
    def is_read_only(self) -> bool:
        """Return True if this operation is strictly read-only (GET)."""
        return self.method.upper() == "GET"

    @property
    def path_parameters(self) -> list[NormalizedParameter]:
        """Return all path parameters."""
        return [p for p in self.parameters if p.is_path]

    @property
    def query_parameters(self) -> list[NormalizedParameter]:
        """Return all query parameters."""
        return [p for p in self.parameters if p.is_query]

    @property
    def header_parameters(self) -> list[NormalizedParameter]:
        """Return all header parameters."""
        return [p for p in self.parameters if p.is_header]

    @property
    def cookie_parameters(self) -> list[NormalizedParameter]:
        """Return all cookie parameters."""
        return [p for p in self.parameters if p.is_cookie]

    @property
    def required_parameters(self) -> list[NormalizedParameter]:
        """Return all required parameters."""
        return [p for p in self.parameters if p.required]

    @property
    def optional_parameters(self) -> list[NormalizedParameter]:
        """Return all optional parameters."""
        return [p for p in self.parameters if not p.required]


class NormalizedAPI(BaseModel):
    """Complete normalized OpenAPI specification representation."""

    openapi_version: str = Field(description="OpenAPI specification version (e.g. 3.0.3, 3.1.0)")
    title: str = Field(description="API Title from info.title")
    description: Optional[str] = Field(default=None, description="API description from info.description")
    version: str = Field(description="API version from info.version")
    server_urls: list[str] = Field(default_factory=list, description="Declared base server URLs")
    global_security: list[dict[str, list[str]]] = Field(
        default_factory=list,
        description="Global root-level security requirements",
    )
    security_schemes: dict[str, SecurityScheme] = Field(
        default_factory=dict,
        description="Component security scheme definitions",
    )
    operations: list[NormalizedOperation] = Field(
        default_factory=list,
        description="Normalized operations across all paths",
    )

    def get_operation_by_tool_name(self, tool_name: str) -> Optional[NormalizedOperation]:
        """Lookup an operation by its normalized tool name."""
        for op in self.operations:
            if op.tool_name == tool_name:
                return op
        return None

    def get_operation_by_id(self, operation_id: str) -> Optional[NormalizedOperation]:
        """Lookup an operation by its original operationId."""
        for op in self.operations:
            if op.operation_id == operation_id:
                return op
        return None

    @property
    def read_only_operations(self) -> list[NormalizedOperation]:
        """Return only read-only (GET) operations for safe exposure modes."""
        return [op for op in self.operations if op.is_read_only]


class GenerationResult(BaseModel):
    """Result metadata from generating an MCP server package."""

    output_dir: Path = Field(description="Directory containing the generated server package")
    package_name: str = Field(description="Name of the generated package")
    tool_names: list[str] = Field(default_factory=list, description="List of generated MCP tool names")
    operation_count: int = Field(description="Total number of operations included in server")
    read_only: bool = Field(default=False, description="Whether server was generated in read-only mode")
    base_url: str = Field(description="Configured default base URL")
    files_created: list[Path] = Field(default_factory=list, description="List of generated files")

    model_config = ConfigDict(arbitrary_types_allowed=True)
