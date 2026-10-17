"""Typed exceptions for OpenAPI parsing, validation, and normalization."""


class OpenAPIParserError(Exception):
    """Base exception for all OpenAPI parsing, validation, and normalization errors."""


class OpenAPISyntaxError(OpenAPIParserError):
    """Raised when the OpenAPI input is empty or cannot be parsed as valid JSON or YAML."""


class UnsupportedOpenAPIVersionError(OpenAPIParserError):
    """Raised when the document version is unsupported (e.g. Swagger 2.0 or missing version)."""


class OpenAPIValidationError(OpenAPIParserError):
    """Raised when the document fails OpenAPI 3.x structural or semantic validation."""


class OpenAPIReferenceError(OpenAPIParserError):
    """Base exception for reference resolution issues."""


class MissingReferenceError(OpenAPIReferenceError):
    """Raised when a local reference ($ref) points to a non-existent component or pointer."""


class ExternalReferenceError(OpenAPIReferenceError):
    """Raised when an external reference is detected that violates security policy (e.g. SSRF)."""


class CircularReferenceError(OpenAPIReferenceError):
    """Raised when an unresolvable circular reference causes a processing hazard."""


class OperationCollisionError(OpenAPIParserError):
    """Raised when operation candidates collide and cannot be deterministically disambiguated."""


class GenerationError(OpenAPIParserError):
    """Raised when MCP server code generation fails."""
