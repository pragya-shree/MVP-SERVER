"""Core generator for converting NormalizedAPI models into runnable MCP servers."""

import copy
import json
from pathlib import Path
import re
import shutil
from typing import Any, Optional, Union
import urllib.parse
import uuid

from backend.generator.exceptions import GenerationError
from backend.generator.models import GenerationResult, NormalizedAPI, NormalizedOperation


def normalize_package_name(name: str) -> str:
    """Normalize an API title into a valid Python package/folder name."""
    s = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    if s and s[0].isdigit():
        s = f"pkg_{s}"
    return s or "mcp_server"


def build_tool_description(op: NormalizedOperation) -> str:
    """Combine operation summary, description, method, path, and tags into a rich tool description."""
    parts = []
    if op.summary and op.summary.strip():
        parts.append(op.summary.strip())
    if op.description and op.description.strip() and op.description.strip() != (op.summary or "").strip():
        parts.append(op.description.strip())

    parts.append(f"HTTP {op.method.upper()} {op.path}")
    if op.is_read_only:
        parts.append("(Read-only)")
    if op.tags:
        parts.append(f"Tags: {', '.join(op.tags)}")

    return " | ".join(parts)


def build_operation_input_schema(op: NormalizedOperation) -> dict[str, Any]:
    """Derive a typed MCP input schema from normalized parameters and request body."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    # 1. Path parameters (always required)
    for p in op.path_parameters:
        schema = copy.deepcopy(p.schema_ or {"type": "string"})
        if p.description:
            schema["description"] = p.description
        properties[p.name] = schema
        required.append(p.name)

    # 2. Query parameters
    for p in op.query_parameters:
        schema = copy.deepcopy(p.schema_ or {"type": "string"})
        if p.description:
            schema["description"] = p.description
        properties[p.name] = schema
        if p.required:
            required.append(p.name)

    # 3. Header parameters (excluding protected auth headers)
    for p in op.header_parameters:
        if p.name.lower() in {"authorization", "x-api-key", "host"}:
            continue
        schema = copy.deepcopy(p.schema_ or {"type": "string"})
        if p.description:
            schema["description"] = p.description
        properties[p.name] = schema
        if p.required:
            required.append(p.name)

    # 4. Request body properties
    if op.request_body and op.request_body.schema_:
        rb_schema = op.request_body.schema_
        if rb_schema.get("type") == "object" and "properties" in rb_schema:
            rb_required = rb_schema.get("required", [])
            for prop_name, prop_schema in rb_schema["properties"].items():
                if prop_name not in properties:
                    properties[prop_name] = copy.deepcopy(prop_schema)
                    if prop_name in rb_required and op.request_body.required:
                        required.append(prop_name)
            # Allow optional explicit body object as well
            properties["body"] = copy.deepcopy(rb_schema)
            properties["body"]["description"] = "Optional explicit request body payload"
        else:
            properties["body"] = copy.deepcopy(rb_schema)
            if op.request_body.required:
                required.append("body")

    return {
        "type": "object",
        "properties": properties,
        "required": list(dict.fromkeys(required)),
    }


def render_server_code(
    api: NormalizedAPI,
    operations: list[NormalizedOperation],
    default_base_url: str,
    server_name: str,
) -> str:
    """Generate self-contained server.py source code."""
    ops_metadata: dict[str, Any] = {}
    for op in operations:
        body_props: list[str] = []
        if op.request_body and op.request_body.schema_ and op.request_body.schema_.get("type") == "object":
            body_props = list(op.request_body.schema_.get("properties", {}).keys())

        ops_metadata[op.tool_name] = {
            "tool_name": op.tool_name,
            "operation_id": op.operation_id,
            "method": op.method.upper(),
            "path": op.path,
            "summary": op.summary,
            "description": build_tool_description(op),
            "path_params": [p.name for p in op.path_parameters],
            "query_params": [p.name for p in op.query_parameters],
            "header_params": [p.name for p in op.header_parameters],
            "body_properties": body_props,
            "has_body": bool(op.request_body),
            "body_required": bool(op.request_body.required) if op.request_body else False,
            "security": op.security,
            "input_schema": build_operation_input_schema(op),
        }

    ops_json = json.dumps(ops_metadata, indent=2)

SERVER_TEMPLATE = '''"""Standalone Model Context Protocol (MCP) server generated by Anything-to-MCP.

Generated for: __API_TITLE__ (v__API_VERSION__)
OpenAPI Version: __OPENAPI_VERSION__
"""

import asyncio
import inspect
import json
import os
from typing import Annotated, Any, Optional
import urllib.parse

from dotenv import load_dotenv
import httpx
from pydantic import BaseModel, ConfigDict, Field

from mcp.server.mcpserver import MCPServer

# Load environment configuration if present
load_dotenv()

SERVER_NAME = "__SERVER_NAME__"
DEFAULT_BASE_URL = "__DEFAULT_BASE_URL__"

OPERATIONS_METADATA: dict[str, Any] = json.loads(r"""__OPERATIONS_JSON__""")


class ServerConfig(BaseModel):
    """Runtime configuration for target API execution and authentication."""

    target_base_url: str = Field(default=DEFAULT_BASE_URL, description="Target base URL")
    bearer_token: Optional[str] = Field(default=None, description="HTTP Bearer token")
    api_key: Optional[str] = Field(default=None, description="API Key value")
    api_key_header: str = Field(default="X-API-Key", description="API Key header name")
    connect_timeout: float = Field(default=10.0, description="Connection timeout in seconds")
    read_timeout: float = Field(default=30.0, description="Read timeout in seconds")
    max_response_bytes: int = Field(default=10485760, description="Maximum response size (10MB)")

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Load configuration from environment variables."""
        return cls(
            target_base_url=os.getenv("TARGET_BASE_URL", DEFAULT_BASE_URL),
            bearer_token=os.getenv("BEARER_TOKEN"),
            api_key=os.getenv("API_KEY"),
            api_key_header=os.getenv("API_KEY_HEADER", "X-API-Key"),
            connect_timeout=float(os.getenv("CONNECT_TIMEOUT_SECONDS", "10.0")),
            read_timeout=float(os.getenv("READ_TIMEOUT_SECONDS", "30.0")),
            max_response_bytes=int(os.getenv("MAX_RESPONSE_BYTES", "10485760")),
        )


async def execute_request(
    op_meta: dict[str, Any],
    arguments: dict[str, Any],
    config: ServerConfig,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Execute target HTTP request corresponding to an MCP tool invocation."""
    path = op_meta["path"]
    method = op_meta["method"]

    # 1. Path parameters substitution
    for param_name in op_meta["path_params"]:
        if param_name not in arguments or arguments[param_name] is None:
            return {
                "error": True,
                "type": "invalid_parameters",
                "message": f"Missing required path parameter '{param_name}'.",
            }
        encoded_val = urllib.parse.quote(str(arguments[param_name]), safe="")
        path = path.replace("{" + param_name + "}", encoded_val)

    if "{" in path and "}" in path:
        return {
            "error": True,
            "type": "unresolved_path",
            "message": f"Path contains unresolved parameters: '{path}'.",
        }

    url = config.target_base_url.rstrip("/") + "/" + path.lstrip("/")

    # 2. Query parameters
    params: dict[str, Any] = {}
    for param_name in op_meta["query_params"]:
        if param_name in arguments and arguments[param_name] is not None:
            params[param_name] = arguments[param_name]

    # 3. Header parameters
    headers: dict[str, str] = {}
    for param_name in op_meta["header_params"]:
        if (
            param_name in arguments
            and arguments[param_name] is not None
            and param_name.lower() not in {"authorization", "x-api-key", "host"}
        ):
            headers[param_name] = str(arguments[param_name])

    # 4. Request Body
    json_payload = None
    if op_meta["has_body"]:
        if "body" in arguments and arguments["body"] is not None:
            json_payload = arguments["body"]
        else:
            gathered_body = {
                k: arguments[k]
                for k in op_meta["body_properties"]
                if k in arguments and arguments[k] is not None
            }
            if gathered_body:
                json_payload = gathered_body
            elif op_meta["body_required"]:
                json_payload = {}

    # 5. Authentication injection (honoring operation-level overrides)
    op_security = op_meta.get("security")
    if op_security != []:  # Not explicitly public
        if config.bearer_token:
            headers["Authorization"] = f"Bearer {config.bearer_token}"
        elif config.api_key:
            headers[config.api_key_header] = config.api_key

    # 6. HTTP execution
    timeout = httpx.Timeout(
        connect=config.connect_timeout,
        read=config.read_timeout,
        write=10.0,
        pool=10.0,
    )

    try:
        if client is not None:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                json=json_payload,
            )
        else:
            async with httpx.AsyncClient(timeout=timeout) as live_client:
                response = await live_client.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=headers,
                    json=json_payload,
                )

        # Enforce response payload bounding
        if len(response.content) > config.max_response_bytes:
            return {
                "error": True,
                "type": "response_size_exceeded",
                "message": f"Response size exceeded {config.max_response_bytes} bytes limit.",
            }

        if response.status_code == 204 or len(response.content) == 0:
            return {"status_code": response.status_code, "data": None, "message": "No Content"}

        try:
            data = response.json()
            if response.is_error:
                return {"error": True, "status_code": response.status_code, "detail": data}
            return {"status_code": response.status_code, "data": data}
        except Exception:
            if response.is_error:
                return {"error": True, "status_code": response.status_code, "detail": response.text}
            return {"status_code": response.status_code, "text": response.text}

    except httpx.TimeoutException:
        return {
            "error": True,
            "type": "timeout",
            "message": f"Target API request timed out after {config.read_timeout}s.",
        }
    except httpx.ConnectError:
        return {
            "error": True,
            "type": "connection_error",
            "message": "Failed to connect to target API. Verify target server is reachable.",
        }
    except Exception as err:
        return {
            "error": True,
            "type": "request_error",
            "message": "An error occurred while executing the HTTP request.",
        }


def build_server(
    config: Optional[ServerConfig] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> MCPServer:
    """Build and configure the runnable MCPServer instance."""
    if config is None:
        config = ServerConfig.from_env()

    app = MCPServer(name=SERVER_NAME)

    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    for tool_name, op_meta in OPERATIONS_METADATA.items():
        # Factory to bind current operation metadata in closure
        def make_handler(current_op: dict[str, Any]):
            async def tool_handler(**kwargs: Any) -> Any:
                return await execute_request(current_op, kwargs, config, client=client)

            schema = current_op.get("input_schema", {})
            properties = schema.get("properties", {})
            required_set = set(schema.get("required", []))
            params = []
            annotations = {}

            for prop_name, prop_schema in properties.items():
                prop_type = prop_schema.get("type")
                base_py_type = type_map.get(prop_type, Any) if isinstance(prop_type, str) else Any
                desc = prop_schema.get("description")
                default_val = prop_schema.get("default", ... if prop_name in required_set else None)

                extra = {}
                for extra_key in ("enum", "format", "minimum", "maximum"):
                    if extra_key in prop_schema:
                        extra[extra_key] = prop_schema[extra_key]

                is_required = prop_name in required_set
                ann = Annotated[
                    base_py_type if is_required else Optional[base_py_type],
                    Field(default=default_val, description=desc, json_schema_extra=extra or None),
                ]
                param_default = default_val if default_val is not ... else inspect.Parameter.empty
                params.append(
                    inspect.Parameter(
                        name=prop_name,
                        kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        annotation=ann,
                        default=param_default,
                    )
                )
                annotations[prop_name] = ann

            params.sort(key=lambda p: p.default is not inspect.Parameter.empty)
            tool_handler.__signature__ = inspect.Signature(parameters=params)
            tool_handler.__annotations__ = annotations
            return tool_handler

        handler = make_handler(op_meta)
        app.add_tool(
            handler,
            name=tool_name,
            title=op_meta.get("summary") or tool_name,
            description=op_meta["description"],
        )

    return app


def main() -> None:
    """Run the MCP server over stdio transport."""
    server = build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
'''


def render_server_code(
    api: NormalizedAPI,
    operations: list[NormalizedOperation],
    default_base_url: str,
    server_name: str,
) -> str:
    """Generate self-contained server.py source code."""
    ops_metadata: dict[str, Any] = {}
    for op in operations:
        body_props: list[str] = []
        if op.request_body and op.request_body.schema_ and op.request_body.schema_.get("type") == "object":
            body_props = list(op.request_body.schema_.get("properties", {}).keys())

        ops_metadata[op.tool_name] = {
            "tool_name": op.tool_name,
            "operation_id": op.operation_id,
            "method": op.method.upper(),
            "path": op.path,
            "summary": op.summary,
            "description": build_tool_description(op),
            "path_params": [p.name for p in op.path_parameters],
            "query_params": [p.name for p in op.query_parameters],
            "header_params": [p.name for p in op.header_parameters],
            "body_properties": body_props,
            "has_body": bool(op.request_body),
            "body_required": bool(op.request_body.required) if op.request_body else False,
            "security": op.security,
            "input_schema": build_operation_input_schema(op),
        }

    ops_json = json.dumps(ops_metadata, indent=2)

    return (
        SERVER_TEMPLATE.replace("__API_TITLE__", api.title)
        .replace("__API_VERSION__", api.version)
        .replace("__OPENAPI_VERSION__", api.openapi_version)
        .replace("__SERVER_NAME__", server_name)
        .replace("__DEFAULT_BASE_URL__", default_base_url)
        .replace("__OPERATIONS_JSON__", ops_json)
    )


def render_readme(
    api: NormalizedAPI,
    operations: list[NormalizedOperation],
    read_only: bool,
    default_base_url: str,
) -> str:
    """Generate README.md documentation for the MCP server package."""
    table_rows = []
    for op in operations:
        table_rows.append(
            f"| `{op.tool_name}` | `{op.method}` | `{op.path}` | {'Yes' if op.is_read_only else 'No'} | {op.summary or op.description or ''} |"
        )
    rows_text = "\n".join(table_rows)

    mode_text = "Strict Read-Only Mode (GET operations only)" if read_only else "Full Mode (All supported operations)"

    return f"""# {api.title} — MCP Server

A standalone Model Context Protocol (MCP) server generated from OpenAPI specification.

## Overview
- **API Version**: {api.version}
- **OpenAPI Version**: {api.openapi_version}
- **Server Mode**: {mode_text}
- **Configured Base URL**: `{default_base_url}`
- **Exposed Tools**: {len(operations)}

---

## Exposed MCP Tools

| Tool Name | Method | Path | Read-Only | Description |
| :--- | :--- | :--- | :--- | :--- |
{rows_text}

---

## Environment Setup

### 1. Create and Activate Virtual Environment
```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Credentials
Copy `.env.example` to `.env` and fill in necessary API credentials:
```bash
cp .env.example .env
```

---

## Running the Server

Start the MCP server using stdio transport:
```bash
python server.py
```

To configure with an MCP client (such as Claude Desktop or custom agents), add to your MCP client configuration:
```json
{{
  "mcpServers": {{
    "{normalize_package_name(api.title)}": {{
      "command": "python",
      "args": ["server.py"],
      "env": {{
        "TARGET_BASE_URL": "{default_base_url}",
        "BEARER_TOKEN": "your-token-here"
      }}
    }}
  }}
}}
```
"""


def render_requirements() -> str:
    """Generate requirements.txt specifying dependencies for the standalone server."""
    return """mcp>=2.0.0
httpx>=0.27.0
pydantic>=2.7.0
python-dotenv>=1.0.0
"""


def render_env_example(default_base_url: str) -> str:
    """Generate .env.example with documented configuration placeholders."""
    return f"""# Target API Base URL
TARGET_BASE_URL={default_base_url}

# Authentication
# Provide BEARER_TOKEN for HTTP Bearer authentication
BEARER_TOKEN=

# Provide API_KEY for API Key authentication
API_KEY=
API_KEY_HEADER=X-API-Key

# Timeouts & Response Limits
CONNECT_TIMEOUT_SECONDS=10.0
READ_TIMEOUT_SECONDS=30.0
MAX_RESPONSE_BYTES=10485760
"""


def generate_mcp_server(
    api: NormalizedAPI,
    output_dir: Union[str, Path],
    package_name: Optional[str] = None,
    base_url: Optional[str] = None,
    read_only: bool = False,
    overwrite: bool = True,
) -> GenerationResult:
    """Generate a self-contained, runnable MCP server package from a NormalizedAPI model."""
    # 1. Filter operations based on read_only mode
    if read_only:
        operations = [op for op in api.operations if op.is_read_only]
    else:
        operations = list(api.operations)

    if not operations:
        raise GenerationError(
            f"No operations available for generation (read_only={read_only}, total_ops={len(api.operations)})."
        )

    # 2. Package naming, validation, and directory resolution
    if package_name is not None:
        if not re.match(r"^[a-zA-Z0-9_]{1,64}$", package_name):
            raise GenerationError(
                f"Invalid package_name '{package_name}': must contain only alphanumeric characters and underscores without path traversal."
            )
        resolved_package_name = package_name
    else:
        resolved_package_name = normalize_package_name(api.title)

    output_path = Path(output_dir)

    # If output_path doesn't already end with package_name, nest inside it
    if output_path.name != resolved_package_name:
        target_dir = output_path / resolved_package_name
    else:
        target_dir = output_path

    # Check collision if overwrite=False
    if target_dir.exists() and any(target_dir.iterdir()) and not overwrite:
        raise GenerationError(
            f"Target directory '{target_dir}' already exists and contains files (overwrite=False)."
        )

    # 3. Base URL resolution and security validation
    resolved_base_url = (
        base_url
        or (api.server_urls[0] if api.server_urls else "http://localhost:8000")
    )

    parsed_url = urllib.parse.urlparse(resolved_base_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise GenerationError(
            f"Invalid base_url '{resolved_base_url}': URL scheme must be http or https with a valid host."
        )

    # 4. Render and stage files atomically
    staging_dir = target_dir.parent / f".staging_{resolved_package_name}_{uuid.uuid4().hex[:8]}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        server_code = render_server_code(
            api=api,
            operations=operations,
            default_base_url=resolved_base_url,
            server_name=resolved_package_name,
        )
        readme_content = render_readme(
            api=api,
            operations=operations,
            read_only=read_only,
            default_base_url=resolved_base_url,
        )
        reqs_content = render_requirements()
        env_content = render_env_example(default_base_url=resolved_base_url)

        # Write to staging directory
        staging_server = staging_dir / "server.py"
        staging_readme = staging_dir / "README.md"
        staging_reqs = staging_dir / "requirements.txt"
        staging_env = staging_dir / ".env.example"

        staging_server.write_text(server_code, encoding="utf-8")
        staging_readme.write_text(readme_content, encoding="utf-8")
        staging_reqs.write_text(reqs_content, encoding="utf-8")
        staging_env.write_text(env_content, encoding="utf-8")

        # Compile check to guarantee valid Python syntax before committing
        try:
            compile(server_code, str(staging_server), "exec")
        except Exception as err:
            raise GenerationError(f"Generated server code failed syntax validation: {err}") from err

        # Atomically commit staging to target directory
        existing_env = None
        if target_dir.exists():
            target_env = target_dir / ".env"
            if target_env.exists():
                existing_env = target_env.read_text(encoding="utf-8")

        target_dir.mkdir(parents=True, exist_ok=True)
        for item in staging_dir.iterdir():
            shutil.copy2(item, target_dir / item.name)

        # Preserve existing user-configured .env
        if existing_env is not None:
            (target_dir / ".env").write_text(existing_env, encoding="utf-8")

    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    server_file = target_dir / "server.py"
    readme_file = target_dir / "README.md"
    reqs_file = target_dir / "requirements.txt"
    env_file = target_dir / ".env.example"

    tool_names = [op.tool_name for op in operations]

    return GenerationResult(
        output_dir=target_dir,
        package_name=resolved_package_name,
        tool_names=tool_names,
        operation_count=len(operations),
        read_only=read_only,
        base_url=resolved_base_url,
        files_created=[server_file, readme_file, reqs_file, env_file],
    )
