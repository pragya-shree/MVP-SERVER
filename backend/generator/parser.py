"""OpenAPI 3.x parser, reference resolver, validator, and normalizer."""

import copy
import json
from pathlib import Path
import re
from typing import Any, Optional, Union

import openapi_spec_validator
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError as SpecValidatorError
from openapi_spec_validator.exceptions import OpenAPISpecValidatorError
import referencing.exceptions
import yaml

from backend.generator.exceptions import (
    CircularReferenceError,
    ExternalReferenceError,
    MissingReferenceError,
    OpenAPIParserError,
    OpenAPIReferenceError,
    OpenAPISyntaxError,
    OpenAPIValidationError,
    UnsupportedOpenAPIVersionError,
)
from backend.generator.models import (
    NormalizedAPI,
    NormalizedOperation,
    NormalizedParameter,
    NormalizedRequestBody,
    NormalizedResponse,
    SecurityScheme,
)

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def unescape_json_pointer(token: str) -> str:
    """Unescape RFC 6901 JSON pointer token (~1 -> /, ~0 -> ~)."""
    return token.replace("~1", "/").replace("~0", "~")


class ReferenceResolver:
    """Resolves local JSON pointer references ($ref) with cycle protection and SSRF guards."""

    def __init__(self, root_doc: dict[str, Any], max_depth: int = 25) -> None:
        self.root_doc = root_doc
        self.max_depth = max_depth

    def resolve_pointer(self, ref: str) -> Any:
        """Resolve a JSON pointer reference string within the root document."""
        if not ref.startswith("#/"):
            if ref.startswith(("http://", "https://", "ftp://", "file://")):
                raise ExternalReferenceError(
                    f"External remote references are rejected for security: '{ref}'"
                )
            if not ref.startswith("#"):
                raise ExternalReferenceError(
                    f"External file references are rejected for security: '{ref}'"
                )
            raise MissingReferenceError(f"Malformed reference pointer: '{ref}'")

        pointer_path = ref[2:]
        if not pointer_path:
            return self.root_doc

        tokens = [unescape_json_pointer(t) for t in pointer_path.split("/")]
        curr: Any = self.root_doc

        for token in tokens:
            if isinstance(curr, dict):
                if token in curr:
                    curr = curr[token]
                else:
                    raise MissingReferenceError(
                        f"Reference '{ref}' could not be resolved: token '{token}' not found."
                    )
            elif isinstance(curr, list):
                try:
                    idx = int(token)
                    curr = curr[idx]
                except (ValueError, IndexError) as err:
                    raise MissingReferenceError(
                        f"Reference '{ref}' could not be resolved at array index '{token}'."
                    ) from err
            else:
                raise MissingReferenceError(
                    f"Reference '{ref}' cannot traverse into primitive value at token '{token}'."
                )

        return curr

    def resolve_schema(
        self,
        schema: Any,
        seen_refs: Optional[set[str]] = None,
        depth: int = 0,
    ) -> Any:
        """Recursively resolve schema references while preserving valid circular structures."""
        if seen_refs is None:
            seen_refs = set()

        if not isinstance(schema, dict):
            return schema

        if "$ref" in schema:
            ref = schema["$ref"]
            if ref in seen_refs or depth >= self.max_depth:
                # Retain recursive reference safely without infinite expansion
                return {"$ref": ref}

            target = self.resolve_pointer(ref)
            new_seen = set(seen_refs)
            new_seen.add(ref)

            resolved_target = self.resolve_schema(target, new_seen, depth + 1)
            if isinstance(resolved_target, dict):
                merged = copy.deepcopy(resolved_target)
                # In OpenAPI 3.1, sibling fields alongside $ref override/augment
                for k, v in schema.items():
                    if k != "$ref":
                        merged[k] = v
                return merged
            return resolved_target

        result: dict[str, Any] = {}
        for k, v in schema.items():
            if k == "properties" and isinstance(v, dict):
                result[k] = {
                    prop_name: self.resolve_schema(prop_val, seen_refs, depth + 1)
                    for prop_name, prop_val in v.items()
                }
            elif k == "items" and isinstance(v, dict):
                result[k] = self.resolve_schema(v, seen_refs, depth + 1)
            elif k in ("allOf", "anyOf", "oneOf") and isinstance(v, list):
                result[k] = [self.resolve_schema(item, seen_refs, depth + 1) for item in v]
            elif k == "additionalProperties" and isinstance(v, dict):
                result[k] = self.resolve_schema(v, seen_refs, depth + 1)
            else:
                result[k] = copy.deepcopy(v)

        return result

    def resolve_item(self, item: Any) -> Any:
        """Resolve a top-level dictionary if it is a reference pointer."""
        if isinstance(item, dict) and "$ref" in item:
            ref = item["$ref"]
            resolved = self.resolve_pointer(ref)
            if isinstance(resolved, dict):
                merged = copy.deepcopy(resolved)
                for k, v in item.items():
                    if k != "$ref":
                        merged[k] = v
                return merged
            return resolved
        return item


def normalize_to_identifier(name: str) -> str:
    """Normalize a raw string into a clean, snake_case identifier."""
    # Convert camelCase and PascalCase to snake_case
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    # Replace non-alphanumeric characters with underscore
    s3 = re.sub(r"[^a-zA-Z0-9_]", "_", s2)
    # Collapse consecutive underscores and strip ends
    s4 = re.sub(r"_+", "_", s3).strip("_").lower()
    # Prepend op_ if starting with a digit
    if s4 and s4[0].isdigit():
        s4 = f"op_{s4}"
    return s4 or "operation"


def derive_fallback_tool_name(method: str, path: str) -> str:
    """Derive a readable, deterministic candidate tool name from HTTP method and path."""
    parts = []
    for segment in path.split("/"):
        segment = segment.strip()
        if not segment:
            continue
        if segment.startswith("{") and segment.endswith("}"):
            var_name = segment[1:-1]
            parts.append(f"by_{var_name}")
        else:
            parts.append(segment)

    joined = "_".join(parts)
    candidate = f"{method.lower()}_{joined}" if joined else method.lower()
    return normalize_to_identifier(candidate)


def generate_unique_tool_name(
    operation_id: Optional[str],
    method: str,
    path: str,
    seen_names: dict[str, int],
) -> str:
    """Generate a unique candidate tool name prioritizing operationId and disambiguating collisions."""
    if operation_id and operation_id.strip():
        base_name = normalize_to_identifier(operation_id)
    else:
        base_name = derive_fallback_tool_name(method, path)

    if base_name not in seen_names:
        seen_names[base_name] = 1
        return base_name

    count = seen_names[base_name] + 1
    seen_names[base_name] = count
    return f"{base_name}_{count}"


def parse_raw_source(source: Union[str, bytes, dict[str, Any], Path]) -> dict[str, Any]:
    """Parse raw OpenAPI input into a validated Python dictionary."""
    if isinstance(source, Path):
        return parse_openapi_file(source)

    if isinstance(source, dict):
        return copy.deepcopy(source)

    if isinstance(source, bytes):
        source = source.decode("utf-8")

    if isinstance(source, str):
        content = source.strip()
        if not content:
            raise OpenAPISyntaxError("OpenAPI specification input is empty.")

        if len(content.encode("utf-8") if isinstance(content, str) else content) > 10 * 1024 * 1024:
            raise OpenAPIValidationError("OpenAPI specification exceeds maximum allowable size (10 MB).")

        # Check if source string is an existing file path
        if "\n" not in content and len(content) < 4096:
            potential_path = Path(content)
            if potential_path.is_file():
                return parse_openapi_file(potential_path)

        # Attempt JSON parsing if it starts like a JSON structure
        if content.startswith("{") or content.startswith("["):
            try:
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise OpenAPISyntaxError("OpenAPI document must be a top-level mapping/object.")
                return parsed
            except json.JSONDecodeError:
                pass  # Fall through to YAML loader which can parse JSON superset

        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as err:
            raise OpenAPISyntaxError(f"Failed to parse OpenAPI document as YAML or JSON: {err}") from err

        if not isinstance(parsed, dict):
            raise OpenAPISyntaxError("OpenAPI document must be a top-level mapping/object.")

        return parsed

    raise OpenAPISyntaxError(f"Unsupported source type: {type(source).__name__}")


def validate_version_and_spec(spec: dict[str, Any]) -> None:
    """Validate specification version and structural schema."""
    if "swagger" in spec:
        swagger_ver = spec["swagger"]
        raise UnsupportedOpenAPIVersionError(
            f"Swagger {swagger_ver} specifications are not supported. "
            "Please provide an OpenAPI 3.0.x or 3.1.x specification."
        )

    if "openapi" not in spec:
        raise UnsupportedOpenAPIVersionError(
            "Missing 'openapi' version field. OpenAPI 3.0.x or 3.1.x is required."
        )

    openapi_version = spec["openapi"]
    if not isinstance(openapi_version, str) or not (
        openapi_version.startswith("3.0") or openapi_version.startswith("3.1")
    ):
        raise UnsupportedOpenAPIVersionError(
            f"Unsupported OpenAPI version '{openapi_version}'. Only OpenAPI 3.0.x and 3.1.x are supported."
        )

    if "info" not in spec or not isinstance(spec["info"], dict):
        raise OpenAPIValidationError("Missing required 'info' object in OpenAPI specification.")

    if "paths" not in spec or not isinstance(spec["paths"], dict):
        raise OpenAPIValidationError("Missing required 'paths' object in OpenAPI specification.")

    for path_key in spec["paths"].keys():
        if not path_key.startswith("/") and not path_key.startswith("x-"):
            raise OpenAPIValidationError(f"Invalid path '{path_key}': paths must begin with '/'.")

    # Validate schema using openapi-spec-validator
    try:
        openapi_spec_validator.validate(spec)
    except SpecValidatorError as err:
        raise OpenAPIValidationError(f"OpenAPI schema validation failed: {err.message}") from err
    except referencing.exceptions.PointerToNowhere as err:
        raise MissingReferenceError(f"Unresolvable local reference pointer: {err}") from err
    except referencing.exceptions.Unresolvable as err:
        raise ExternalReferenceError(f"External reference rejected: {err}") from err
    except OpenAPISpecValidatorError as err:
        raise OpenAPIValidationError(f"OpenAPI validation error: {err}") from err
    except Exception as err:
        # Check if underlying error is a reference issue
        err_str = str(err)
        if "PointerToNowhere" in type(err).__name__ or "does not exist within" in err_str:
            raise MissingReferenceError(f"Missing component reference: {err_str}") from err
        raise OpenAPIValidationError(f"OpenAPI specification is invalid: {err_str}") from err


def parse_openapi_file(file_path: Union[str, Path]) -> NormalizedAPI:
    """Parse and normalize an OpenAPI specification from a file path."""
    path_obj = Path(file_path)
    if not path_obj.exists():
        raise OpenAPISyntaxError(f"OpenAPI file not found: {path_obj}")
    if not path_obj.is_file():
        raise OpenAPISyntaxError(f"Path is not a regular file: {path_obj}")
    if path_obj.stat().st_size > 10 * 1024 * 1024:
        raise OpenAPIValidationError("OpenAPI specification file exceeds maximum allowable size (10 MB).")

    try:
        raw_content = path_obj.read_text(encoding="utf-8")
    except Exception as err:
        raise OpenAPISyntaxError(f"Error reading OpenAPI file '{path_obj}': {err}") from err

    return parse_openapi(raw_content)


def parse_openapi(source: Union[str, bytes, dict[str, Any], Path]) -> NormalizedAPI:
    """Parse, validate, resolve, and normalize an OpenAPI 3.x document into a NormalizedAPI object."""
    spec = parse_raw_source(source)
    validate_version_and_spec(spec)

    resolver = ReferenceResolver(spec)

    # API-level metadata
    openapi_version = str(spec.get("openapi", "3.0.0"))
    info = spec.get("info", {})
    title = str(info.get("title", "OpenAPI Service"))
    description = info.get("description")
    version = str(info.get("version", "1.0.0"))

    server_urls = [s["url"] for s in spec.get("servers", []) if isinstance(s, dict) and "url" in s]
    global_security = spec.get("security", [])

    # Security schemes
    security_schemes: dict[str, SecurityScheme] = {}
    components = spec.get("components", {})
    if isinstance(components, dict):
        raw_schemes = components.get("securitySchemes", {})
        if isinstance(raw_schemes, dict):
            for scheme_name, raw_scheme in raw_schemes.items():
                resolved_scheme = resolver.resolve_item(raw_scheme)
                if isinstance(resolved_scheme, dict):
                    security_schemes[scheme_name] = SecurityScheme.model_validate(resolved_scheme)

    operations: list[NormalizedOperation] = []
    seen_tool_names: dict[str, int] = {}

    paths = spec.get("paths", {})
    for path, path_item in paths.items():
        if not path.startswith("/"):
            raise OpenAPIValidationError(f"Invalid path '{path}': paths must begin with '/'.")

        path_item = resolver.resolve_item(path_item)
        if not isinstance(path_item, dict):
            raise OpenAPIValidationError(f"Invalid path item for path '{path}'.")

        # Resolve path-level parameters
        raw_path_params = path_item.get("parameters", [])
        resolved_path_params: list[NormalizedParameter] = []
        for p in raw_path_params:
            resolved_p = resolver.resolve_item(p)
            if not isinstance(resolved_p, dict):
                raise OpenAPIValidationError(f"Invalid path-level parameter declaration in '{path}'.")
            if "schema" in resolved_p:
                resolved_p["schema"] = resolver.resolve_schema(resolved_p["schema"])
            param_obj = NormalizedParameter.model_validate(resolved_p)
            resolved_path_params.append(param_obj)

        # Extract path template variables (e.g. {project_id})
        path_template_vars = re.findall(r"\{([^}]+)\}", path)

        for method_key, raw_operation in path_item.items():
            method_lower = method_key.lower()
            if method_lower not in HTTP_METHODS:
                continue

            raw_operation = resolver.resolve_item(raw_operation)
            if not isinstance(raw_operation, dict):
                raise OpenAPIValidationError(f"Invalid operation object for {method_lower.upper()} {path}.")

            operation_id = raw_operation.get("operationId")
            tool_name = generate_unique_tool_name(operation_id, method_lower, path, seen_tool_names)

            # Resolve operation-level parameters
            raw_op_params = raw_operation.get("parameters", [])
            resolved_op_params: list[NormalizedParameter] = []
            for p in raw_op_params:
                resolved_p = resolver.resolve_item(p)
                if not isinstance(resolved_p, dict):
                    raise OpenAPIValidationError(
                        f"Invalid operation parameter declaration in {method_lower.upper()} '{path}'."
                    )
                if "schema" in resolved_p:
                    resolved_p["schema"] = resolver.resolve_schema(resolved_p["schema"])
                param_obj = NormalizedParameter.model_validate(resolved_p)
                resolved_op_params.append(param_obj)

            # Merge parameters: operation-level (name, in) overrides path-level
            merged_params_map: dict[tuple[str, str], NormalizedParameter] = {}
            for p in resolved_path_params:
                merged_params_map[(p.name, p.in_)] = p
            for p in resolved_op_params:
                merged_params_map[(p.name, p.in_)] = p

            merged_params = list(merged_params_map.values())

            # Path parameter validation
            declared_path_param_names = {p.name for p in merged_params if p.is_path}
            for var in path_template_vars:
                if var not in declared_path_param_names:
                    raise OpenAPIValidationError(
                        f"Path parameter '{var}' in path '{path}' is not declared in parameters "
                        f"for operation '{tool_name}' ({method_lower.upper()} {path})."
                    )

            # Enforce required=True for all path parameters
            for p in merged_params:
                if p.is_path:
                    p.required = True

            # Request body extraction
            request_body_model: Optional[NormalizedRequestBody] = None
            if "requestBody" in raw_operation:
                raw_rb = resolver.resolve_item(raw_operation["requestBody"])
                if isinstance(raw_rb, dict):
                    rb_desc = raw_rb.get("description")
                    rb_req = raw_rb.get("required", False)
                    rb_content = raw_rb.get("content", {})
                    content_schemas: dict[str, dict[str, Any]] = {}
                    content_types = list(rb_content.keys())

                    for ct, media_obj in rb_content.items():
                        resolved_media = resolver.resolve_item(media_obj)
                        if isinstance(resolved_media, dict) and "schema" in resolved_media:
                            content_schemas[ct] = resolver.resolve_schema(resolved_media["schema"])

                    primary_schema = content_schemas.get("application/json")
                    if not primary_schema and content_schemas:
                        primary_schema = next(iter(content_schemas.values()))

                    request_body_model = NormalizedRequestBody(
                        description=rb_desc,
                        required=rb_req,
                        content_types=content_types,
                        schema=primary_schema,
                        content_schemas=content_schemas,
                    )

            # Responses extraction
            responses_map: dict[str, NormalizedResponse] = {}
            raw_responses = raw_operation.get("responses", {})
            if isinstance(raw_responses, dict):
                for status_code, raw_resp in raw_responses.items():
                    resolved_resp = resolver.resolve_item(raw_resp)
                    if isinstance(resolved_resp, dict):
                        resp_desc = resolved_resp.get("description", "")
                        resp_content = resolved_resp.get("content", {})
                        resp_content_schemas: dict[str, dict[str, Any]] = {}
                        resp_content_types = list(resp_content.keys())

                        for ct, media_obj in resp_content.items():
                            resolved_media = resolver.resolve_item(media_obj)
                            if isinstance(resolved_media, dict) and "schema" in resolved_media:
                                resp_content_schemas[ct] = resolver.resolve_schema(resolved_media["schema"])

                        primary_resp_schema = resp_content_schemas.get("application/json")
                        if not primary_resp_schema and resp_content_schemas:
                            primary_resp_schema = next(iter(resp_content_schemas.values()))

                        responses_map[str(status_code)] = NormalizedResponse(
                            status_code=str(status_code),
                            description=resp_desc,
                            content_types=resp_content_types,
                            schema=primary_resp_schema,
                            content_schemas=resp_content_schemas,
                        )

            # Security resolution
            if "security" in raw_operation:
                declared_security = raw_operation["security"]
                effective_security = declared_security  # [] means public, overrides global
            else:
                declared_security = None
                effective_security = global_security

            op_model = NormalizedOperation(
                operation_id=operation_id,
                tool_name=tool_name,
                method=method_lower.upper(),
                path=path,
                summary=raw_operation.get("summary"),
                description=raw_operation.get("description"),
                tags=raw_operation.get("tags", []),
                deprecated=raw_operation.get("deprecated", False),
                parameters=merged_params,
                request_body=request_body_model,
                responses=responses_map,
                security=effective_security,
                declared_security=declared_security,
            )
            operations.append(op_model)

    return NormalizedAPI(
        openapi_version=openapi_version,
        title=title,
        description=description,
        version=version,
        server_urls=server_urls,
        global_security=global_security,
        security_schemes=security_schemes,
        operations=operations,
    )
