"""Reusable OpenAPI parsing and MCP generation engine.

This engine is kept independent of FastAPI so that it can be invoked
via CLI, HTTP API, and background/testing workflows.
"""

from backend.generator.exceptions import (
    CircularReferenceError,
    ExternalReferenceError,
    GenerationError,
    MissingReferenceError,
    OpenAPIParserError,
    OpenAPIReferenceError,
    OpenAPISyntaxError,
    OpenAPIValidationError,
    OperationCollisionError,
    UnsupportedOpenAPIVersionError,
)
from backend.generator.generator import generate_mcp_server
from backend.generator.models import (
    GenerationResult,
    NormalizedAPI,
    NormalizedOperation,
    NormalizedParameter,
    NormalizedRequestBody,
    NormalizedResponse,
    SecurityScheme,
)
from backend.generator.parser import parse_openapi, parse_openapi_file

__all__ = [
    "parse_openapi",
    "parse_openapi_file",
    "generate_mcp_server",
    "GenerationResult",
    "NormalizedAPI",
    "NormalizedOperation",
    "NormalizedParameter",
    "NormalizedRequestBody",
    "NormalizedResponse",
    "SecurityScheme",
    "OpenAPIParserError",
    "OpenAPISyntaxError",
    "UnsupportedOpenAPIVersionError",
    "OpenAPIValidationError",
    "OpenAPIReferenceError",
    "MissingReferenceError",
    "ExternalReferenceError",
    "CircularReferenceError",
    "OperationCollisionError",
    "GenerationError",
]
