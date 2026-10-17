"""Comprehensive test suite for OpenAPI parser, reference resolution, validation, and normalization."""

from pathlib import Path
import pytest

from backend.generator import (
    ExternalReferenceError,
    MissingReferenceError,
    NormalizedAPI,
    OpenAPISyntaxError,
    OpenAPIValidationError,
    UnsupportedOpenAPIVersionError,
    parse_openapi,
    parse_openapi_file,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


def test_parse_task_management_yaml_file() -> None:
    """Verify complete parsing, parameter merging, and schema resolution of the Task Management API."""
    spec_path = EXAMPLES_DIR / "task_management_api.yaml"
    api: NormalizedAPI = parse_openapi_file(spec_path)

    # API metadata
    assert api.title == "Task Management API"
    assert api.version == "1.0.0"
    assert api.openapi_version == "3.0.3"
    assert len(api.server_urls) == 2
    assert "https://api.taskmanager.example.com/v1" in api.server_urls

    # Global security and schemes
    assert api.global_security == [{"BearerAuth": []}]
    assert "BearerAuth" in api.security_schemes
    assert api.security_schemes["BearerAuth"].scheme == "bearer"
    assert api.security_schemes["BearerAuth"].bearer_format == "JWT"
    assert "ApiKeyAuth" in api.security_schemes
    assert api.security_schemes["ApiKeyAuth"].name == "X-API-Key"
    assert api.security_schemes["ApiKeyAuth"].in_ == "header"

    # Operations
    assert len(api.operations) == 5

    # 1. GET /tasks (public override, query params, enum schema)
    list_op = api.get_operation_by_tool_name("list_tasks")
    assert list_op is not None
    assert list_op.operation_id == "listTasks"
    assert list_op.method == "GET"
    assert list_op.path == "/tasks"
    assert list_op.is_read_only is True
    assert list_op.security == []  # Overridden to public
    assert list_op.declared_security == []

    # Parameters in list_tasks
    param_names = {p.name: p for p in list_op.parameters}
    assert "status" in param_names
    assert param_names["status"].is_query
    assert param_names["status"].required is False
    assert param_names["status"].schema_["enum"] == ["todo", "in_progress", "completed", "archived"]

    assert "limit" in param_names
    assert param_names["limit"].schema_["default"] == 20
    assert param_names["limit"].schema_["maximum"] == 100

    assert "offset" in param_names
    assert param_names["offset"].schema_["default"] == 0

    # 2. POST /tasks (requestBody with nested schemas, security inheritance)
    create_op = api.get_operation_by_tool_name("create_task")
    assert create_op is not None
    assert create_op.method == "POST"
    assert create_op.is_read_only is False
    assert create_op.security == [{"BearerAuth": []}]  # Inherited from global
    assert create_op.declared_security is None

    assert create_op.request_body is not None
    assert create_op.request_body.required is True
    assert "application/json" in create_op.request_body.content_types
    rb_schema = create_op.request_body.schema_
    assert "title" in rb_schema["properties"]
    assert "priority" in rb_schema["properties"]
    assert rb_schema["properties"]["priority"]["enum"] == ["low", "medium", "high", "urgent"]

    # Responses
    assert "201" in create_op.responses
    resp_201_schema = create_op.responses["201"].schema_
    assert "id" in resp_201_schema["properties"]
    assert "assignee" in resp_201_schema["properties"]
    # Verify nested resolved schema
    assert "name" in resp_201_schema["properties"]["assignee"]["properties"]

    # 3. GET /tasks/{task_id} (path-level parameter merged into operation)
    get_task_op = api.get_operation_by_tool_name("get_task_by_id")
    assert get_task_op is not None
    assert len(get_task_op.path_parameters) == 1
    task_id_param = get_task_op.path_parameters[0]
    assert task_id_param.name == "task_id"
    assert task_id_param.required is True
    assert task_id_param.schema_["format"] == "uuid"

    # 4. Fallback naming on GET /projects/{project_id}/tasks
    project_tasks_op = api.get_operation_by_tool_name("get_projects_by_project_id_tasks")
    assert project_tasks_op is not None
    assert project_tasks_op.operation_id is None
    assert project_tasks_op.path_parameters[0].name == "project_id"
    assert project_tasks_op.path_parameters[0].required is True


def test_parse_openapi_31_json_file() -> None:
    """Verify OpenAPI 3.1 JSON parsing with modern type array definitions."""
    spec_path = FIXTURES_DIR / "openapi_31_sample.json"
    api = parse_openapi_file(spec_path)

    assert api.openapi_version == "3.1.0"
    assert api.title == "Modern Notes API 3.1"
    assert len(api.operations) == 2

    get_op = api.get_operation_by_tool_name("get_notes")
    assert get_op is not None
    items_schema = get_op.responses["200"].schema_["items"]
    # Check 3.1 type array: ['string', 'null']
    assert items_schema["properties"]["content"]["type"] == ["string", "null"]


def test_parse_from_dict_and_strings() -> None:
    """Verify parsing from dictionary, YAML string, and JSON string inputs."""
    dict_input = {
        "openapi": "3.0.3",
        "info": {"title": "Inline Dict API", "version": "1.0.0"},
        "paths": {
            "/ping": {
                "get": {
                    "operationId": "pingService",
                    "responses": {"200": {"description": "Pong"}},
                }
            }
        },
    }

    # Dict input
    api1 = parse_openapi(dict_input)
    assert api1.title == "Inline Dict API"
    assert len(api1.operations) == 1
    assert api1.operations[0].tool_name == "ping_service"

    # YAML string input
    yaml_str = """
openapi: 3.0.3
info:
  title: YAML String API
  version: 1.0.0
paths:
  /echo:
    get:
      operationId: echoEndpoint
      responses:
        '200':
          description: Echo
"""
    api2 = parse_openapi(yaml_str)
    assert api2.title == "YAML String API"
    assert api2.operations[0].tool_name == "echo_endpoint"

    # JSON string input
    json_str = '{"openapi": "3.0.3", "info": {"title": "JSON String API", "version": "1.0.0"}, "paths": {}}'
    api3 = parse_openapi(json_str)
    assert api3.title == "JSON String API"
    assert len(api3.operations) == 0


def test_swagger_v2_rejection() -> None:
    """Verify Swagger 2.0 documents are rejected with clear actionable error."""
    spec_path = FIXTURES_DIR / "swagger_v2.json"
    with pytest.raises(UnsupportedOpenAPIVersionError) as exc_info:
        parse_openapi_file(spec_path)

    assert "Swagger 2.0" in str(exc_info.value)
    assert "OpenAPI 3.0.x or 3.1.x" in str(exc_info.value)


def test_missing_and_invalid_version() -> None:
    """Verify missing or unsupported versions raise UnsupportedOpenAPIVersionError."""
    # Missing version
    with pytest.raises(UnsupportedOpenAPIVersionError) as exc_info:
        parse_openapi({"info": {"title": "No Version", "version": "1.0"}, "paths": {}})
    assert "Missing 'openapi'" in str(exc_info.value)

    # Unsupported version (e.g. 4.0.0)
    with pytest.raises(UnsupportedOpenAPIVersionError) as exc_info:
        parse_openapi({"openapi": "4.0.0", "info": {"title": "Future OAS", "version": "1.0"}, "paths": {}})
    assert "Unsupported OpenAPI version '4.0.0'" in str(exc_info.value)


def test_syntax_errors() -> None:
    """Verify empty input and malformed YAML/JSON raise OpenAPISyntaxError."""
    # Empty string
    with pytest.raises(OpenAPISyntaxError) as exc_info:
        parse_openapi("")
    assert "empty" in str(exc_info.value).lower()

    # Malformed YAML
    with pytest.raises(OpenAPISyntaxError) as exc_info:
        parse_openapi("openapi: 3.0.0\ninfo: [unclosed list")
    assert "Failed to parse" in str(exc_info.value)

    # Top-level array instead of mapping
    with pytest.raises(OpenAPISyntaxError) as exc_info:
        parse_openapi("- item1\n- item2")
    assert "top-level mapping" in str(exc_info.value)


def test_structural_validation_errors() -> None:
    """Verify missing required info and paths objects raise OpenAPIValidationError."""
    # Missing info
    with pytest.raises(OpenAPIValidationError) as exc_info:
        parse_openapi({"openapi": "3.0.3", "paths": {}})
    assert "'info'" in str(exc_info.value)

    # Missing paths
    with pytest.raises(OpenAPIValidationError) as exc_info:
        parse_openapi({"openapi": "3.0.3", "info": {"title": "T", "version": "1"}})
    assert "'paths'" in str(exc_info.value)

    # Path doesn't start with slash
    with pytest.raises(OpenAPIValidationError) as exc_info:
        parse_openapi({
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1"},
            "paths": {"invalid_path": {}},
        })
    assert "must begin with '/'" in str(exc_info.value)


def test_missing_path_parameter_declaration() -> None:
    """Verify that an undeclared path template parameter raises OpenAPIValidationError."""
    spec_path = FIXTURES_DIR / "missing_path_param.yaml"
    with pytest.raises(OpenAPIValidationError) as exc_info:
        parse_openapi_file(spec_path)

    assert "Path parameter 'project_id'" in str(exc_info.value)
    assert "was not resolved" in str(exc_info.value) or "not declared" in str(exc_info.value)


def test_parameter_merging_and_override_semantics() -> None:
    """Verify operation-level parameters override path-level parameters with the same (name, in) pair."""
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Param Override API", "version": "1.0.0"},
        "paths": {
            "/items/{item_id}": {
                "parameters": [
                    {
                        "name": "item_id",
                        "in": "path",
                        "required": True,
                        "description": "Path-level item ID",
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "filter",
                        "in": "query",
                        "description": "Path-level filter",
                        "schema": {"type": "string"},
                    },
                ],
                "get": {
                    "operationId": "getItem",
                    "parameters": [
                        # Overrides path-level item_id description
                        {
                            "name": "item_id",
                            "in": "path",
                            "required": True,
                            "description": "Operation-level item ID override",
                            "schema": {"type": "string"},
                        },
                        # Same name 'filter' but located in 'header' (different (name, in) key!)
                        {
                            "name": "filter",
                            "in": "header",
                            "description": "Header filter",
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {"200": {"description": "OK"}},
                },
            }
        },
    }

    api = parse_openapi(spec)
    op = api.operations[0]

    # Verify parameters count:
    # 1. ("item_id", "path"): overridden by operation-level
    # 2. ("filter", "query"): inherited from path-level
    # 3. ("filter", "header"): declared at operation-level
    assert len(op.parameters) == 3

    path_params = op.path_parameters
    assert len(path_params) == 1
    assert path_params[0].description == "Operation-level item ID override"
    assert path_params[0].required is True

    query_params = op.query_parameters
    assert len(query_params) == 1
    assert query_params[0].name == "filter"
    assert query_params[0].description == "Path-level filter"

    header_params = op.header_parameters
    assert len(header_params) == 1
    assert header_params[0].name == "filter"
    assert header_params[0].description == "Header filter"


def test_colliding_operation_names_disambiguation() -> None:
    """Verify colliding candidate names are deterministically disambiguated."""
    spec_path = FIXTURES_DIR / "colliding_operations.yaml"
    api = parse_openapi_file(spec_path)

    tool_names = [op.tool_name for op in api.operations]
    # list_tasks and listTasks both normalize to list_tasks
    assert "list_tasks" in tool_names
    assert "list_tasks_2" in tool_names

    # Check original operation_ids are preserved intact
    op1 = api.get_operation_by_tool_name("list_tasks")
    assert op1.operation_id == "list_tasks"

    op2 = api.get_operation_by_tool_name("list_tasks_2")
    assert op2.operation_id == "listTasks"

    # Fallback collision
    assert "get_duplicate_fallback" in tool_names
    assert "get_duplicate_fallback_2" in tool_names


def test_circular_schema_resolution() -> None:
    """Verify recursive schemas are bounded safely and preserve cycle reference."""
    spec_path = FIXTURES_DIR / "circular_schema.yaml"
    api = parse_openapi_file(spec_path)

    op = api.get_operation_by_tool_name("get_categories")
    assert op is not None
    schema = op.responses["200"].schema_

    assert schema["type"] == "object"
    assert "name" in schema["properties"]
    # Verify subcategories array items holds reference without exploding recursion
    subcategories = schema["properties"]["subcategories"]
    assert subcategories["type"] == "array"
    assert "$ref" in subcategories["items"]
    assert subcategories["items"]["$ref"] == "#/components/schemas/Category"


def test_missing_reference_error() -> None:
    """Verify missing local references raise MissingReferenceError."""
    spec_path = FIXTURES_DIR / "missing_ref.yaml"
    with pytest.raises(MissingReferenceError) as exc_info:
        parse_openapi_file(spec_path)

    assert "NonExistentItem" in str(exc_info.value)


def test_external_reference_rejection() -> None:
    """Verify external remote references are rejected for security."""
    spec_path = FIXTURES_DIR / "external_ref.yaml"
    with pytest.raises(ExternalReferenceError) as exc_info:
        parse_openapi_file(spec_path)

    assert "External" in str(exc_info.value) or "rejected" in str(exc_info.value)


def test_security_alternatives_and_combined_schemes() -> None:
    """Verify alternatives (OR) and combined (AND) security configurations."""
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Security API", "version": "1.0"},
        "security": [
            {"OAuth": ["read:items"]},  # Alternative 1
            {"ApiKey": []},             # Alternative 2
        ],
        "paths": {
            "/multi-auth": {
                "get": {
                    "operationId": "getMultiAuth",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/combined-auth": {
                "post": {
                    "operationId": "postCombinedAuth",
                    # Both SchemeA AND SchemeB required together
                    "security": [{"SchemeA": [], "SchemeB": []}],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/public-endpoint": {
                "get": {
                    "operationId": "getPublic",
                    "security": [],  # Public override
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }

    api = parse_openapi(spec)

    multi_op = api.get_operation_by_tool_name("get_multi_auth")
    assert len(multi_op.security) == 2  # Inherits global alternatives

    combined_op = api.get_operation_by_tool_name("post_combined_auth")
    assert len(combined_op.security) == 1
    assert "SchemeA" in combined_op.security[0]
    assert "SchemeB" in combined_op.security[0]

    public_op = api.get_operation_by_tool_name("get_public")
    assert public_op.security == []


def test_read_only_operations_filter() -> None:
    """Verify read_only_operations returns only GET endpoints."""
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Filter API", "version": "1.0"},
        "paths": {
            "/items": {
                "get": {"operationId": "getItems", "responses": {"200": {"description": "OK"}}},
                "post": {"operationId": "createItem", "responses": {"201": {"description": "Created"}}},
            },
            "/items/{id}": {
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "get": {"operationId": "getItem", "responses": {"200": {"description": "OK"}}},
                "delete": {"operationId": "deleteItem", "responses": {"204": {"description": "Deleted"}}},
            },
        },
    }

    api = parse_openapi(spec)
    read_only = api.read_only_operations
    assert len(read_only) == 2
    assert {op.tool_name for op in read_only} == {"get_items", "get_item"}


def test_deterministic_parsing() -> None:
    """Verify parsing multiple times yields identical results."""
    spec_path = EXAMPLES_DIR / "task_management_api.yaml"
    api1 = parse_openapi_file(spec_path)
    api2 = parse_openapi_file(spec_path)

    assert api1.model_dump() == api2.model_dump()


def test_tool_name_candidate_normalization_and_fallback() -> None:
    """Verify identifier normalization and fallback generation across various inputs."""
    from backend.generator.parser import derive_fallback_tool_name, normalize_to_identifier

    assert normalize_to_identifier("listTasks") == "list_tasks"
    assert normalize_to_identifier("getTaskById") == "get_task_by_id"
    assert normalize_to_identifier("create-task") == "create_task"
    assert normalize_to_identifier("123Upload") == "op_123_upload"
    assert normalize_to_identifier("delete $item!") == "delete_item"
    assert normalize_to_identifier("   spaces  and---hyphens   ") == "spaces_and_hyphens"

    assert (
        derive_fallback_tool_name("GET", "/projects/{project_id}/tasks/{task_id}")
        == "get_projects_by_project_id_tasks_by_task_id"
    )
    assert derive_fallback_tool_name("DELETE", "/users/{id}") == "delete_users_by_id"
    assert derive_fallback_tool_name("POST", "/webhooks") == "post_webhooks"

