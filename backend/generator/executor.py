"""In-process tool executor supporting both serverless environments and local execution."""

import copy
import hashlib
import json
import os
import re
import time
from typing import Any, Optional
import urllib.parse

import httpx

from backend.security import (
    PolicyDecision,
    global_approval_store,
    global_audit_logger,
    global_policy_engine,
)
from backend.security.redaction import global_redactor
from demo_api.app import app as demo_fastapi_app


class InProcessConfig:
    """Runtime configuration for in-process tool execution."""

    def __init__(
        self,
        target_base_url: str = "http://127.0.0.1:8000/demo-target",
        bearer_token: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_header: str = "X-API-Key",
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        max_response_bytes: int = 10485760,
        dry_run: bool = False,
        require_approval: bool = False,
        mask_secrets: bool = True,
        denied_operations: Optional[list[str]] = None,
        denied_methods: Optional[list[str]] = None,
    ) -> None:
        self.target_base_url = target_base_url
        self.bearer_token = bearer_token
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_response_bytes = max_response_bytes
        self.dry_run = dry_run
        self.require_approval = require_approval
        self.mask_secrets = mask_secrets
        self.denied_operations = denied_operations or []
        self.denied_methods = denied_methods or []

    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None) -> "InProcessConfig":
        """Construct config from environment dict or os.environ."""
        source = dict(os.environ)
        if env:
            source.update(env)

        default_base = "http://127.0.0.1:8000/demo-target"
        if "VERCEL_URL" in source and "DEMO_API_BASE_URL" not in source:
            default_base = f"https://{source['VERCEL_URL']}/demo-target"
        elif "DEMO_API_BASE_URL" in source:
            default_base = source["DEMO_API_BASE_URL"]

        return cls(
            target_base_url=source.get("TARGET_BASE_URL", default_base),
            bearer_token=source.get("BEARER_TOKEN"),
            api_key=source.get("API_KEY"),
            api_key_header=source.get("API_KEY_HEADER", "X-API-Key"),
            connect_timeout=float(source.get("CONNECT_TIMEOUT_SECONDS", "10.0")),
            read_timeout=float(source.get("READ_TIMEOUT_SECONDS", "30.0")),
            max_response_bytes=int(source.get("MAX_RESPONSE_BYTES", "10485760")),
            dry_run=source.get("DRY_RUN", "false").lower() in ("true", "1", "yes"),
            require_approval=source.get("REQUIRE_APPROVAL", "false").lower() in ("true", "1", "yes"),
            mask_secrets=source.get("MASK_SECRETS", "true").lower() in ("true", "1", "yes"),
            denied_operations=[
                op.strip()
                for op in source.get("DENIED_OPERATIONS", "").split(",")
                if op.strip()
            ],
            denied_methods=[
                m.strip().upper()
                for m in source.get("DENIED_METHODS", "").split(",")
                if m.strip()
            ],
        )


async def execute_tool_in_process(
    op_meta: dict[str, Any],
    arguments: dict[str, Any],
    config: Optional[InProcessConfig] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Execute target HTTP request corresponding to an MCP tool invocation with security guardrails."""
    if config is None:
        config = InProcessConfig.from_env()

    path = op_meta["path"]
    method = op_meta["method"].upper()
    tool_name = op_meta.get("tool_name", "")
    is_mutating = method in ("POST", "PUT", "PATCH", "DELETE")

    # Clean incoming arguments for validation (ignoring meta approval ID)
    clean_arguments = {k: v for k, v in arguments.items() if k != "approval_id"}

    # Resolve path parameters for action display and dry-run reporting
    resolved_path = path
    for param_name in op_meta.get("path_params", []):
        if param_name in clean_arguments and clean_arguments[param_name] is not None:
            encoded_val = urllib.parse.quote(str(clean_arguments[param_name]), safe="")
            resolved_path = resolved_path.replace("{" + param_name + "}", encoded_val)

    # Guardrail 1: Policy Deny Check (Absolute Precedence)
    if tool_name in config.denied_operations or method in config.denied_methods:
        return {
            "error": True,
            "type": "policy_denied",
            "message": f"Operation '{method} {resolved_path}' is forbidden by security policy.",
        }

    # Guardrail 2: Dry-Run Mode Interception (Precedence over approval)
    if config.dry_run and is_mutating:
        safe_args, _ = global_redactor.redact_json(clean_arguments) if config.mask_secrets else (clean_arguments, 0)
        return {
            "status": "DRY_RUN_INTERCEPTED",
            "action": f"{method} {resolved_path}",
            "message": "Dry-run mode is enabled. The upstream request was not sent.",
            "method": method,
            "path": resolved_path,
            "arguments": safe_args,
            "is_mutating": True,
        }

    # Guardrail 3: Explicit Approval Mode
    if config.require_approval and is_mutating:
        approval_id = arguments.get("approval_id")
        if not approval_id:
            req = global_approval_store.create_request(
                tool_name=tool_name,
                method=method,
                path=resolved_path,
                arguments=clean_arguments,
                reason=f"Mutating operation {method} {resolved_path} requires explicit human approval",
            )
            safe_args = req.safe_arguments
            return {
                "status": "PENDING_CONFIRMATION",
                "approval_id": req.approval_id,
                "tool_name": tool_name,
                "action": f"{method} {resolved_path}",
                "message": f"Approval required to execute {method} {resolved_path}. Re-invoke with approval_id='{req.approval_id}'.",
                "safe_arguments": safe_args,
                "expires_at": req.expires_at,
            }
        else:
            valid, msg, _bound_args = global_approval_store.consume_and_verify(
                approval_id=approval_id,
                tool_name=tool_name,
                arguments=clean_arguments,
            )
            if not valid:
                return {
                    "error": True,
                    "type": "approval_rejected",
                    "message": msg,
                }

    # 1. Path parameters substitution
    for param_name in op_meta.get("path_params", []):
        if param_name not in clean_arguments or clean_arguments[param_name] is None:
            return {
                "error": True,
                "type": "invalid_parameters",
                "message": f"Missing required path parameter '{param_name}'.",
            }
        encoded_val = urllib.parse.quote(str(clean_arguments[param_name]), safe="")
        path = path.replace("{" + param_name + "}", encoded_val)

    if "{" in path and "}" in path:
        return {
            "error": True,
            "type": "unresolved_path",
            "message": f"Path contains unresolved parameters: '{path}'.",
        }

    # 2. Query parameters
    params: dict[str, Any] = {}
    for param_name in op_meta.get("query_params", []):
        if param_name in clean_arguments and clean_arguments[param_name] is not None:
            params[param_name] = clean_arguments[param_name]

    # 3. Header parameters
    headers: dict[str, str] = {}
    for param_name in op_meta.get("header_params", []):
        if (
            param_name in clean_arguments
            and clean_arguments[param_name] is not None
            and param_name.lower() not in {"authorization", "x-api-key", "host"}
        ):
            headers[param_name] = str(clean_arguments[param_name])

    # 4. Request Body
    json_payload = None
    if op_meta.get("has_body"):
        if "body" in clean_arguments and clean_arguments["body"] is not None:
            json_payload = clean_arguments["body"]
        else:
            path_params = set(op_meta.get("path_params", []))
            query_params = set(op_meta.get("query_params", []))
            header_params = set(op_meta.get("header_params", []))
            gathered_body = {
                k: v
                for k, v in clean_arguments.items()
                if k not in path_params and k not in query_params and k not in header_params
            }
            if gathered_body:
                json_payload = gathered_body
            elif op_meta.get("body_required"):
                json_payload = {}

    # 5. Authentication injection
    op_security = op_meta.get("security")
    if op_security != []:  # Not explicitly public
        if config.bearer_token:
            headers["Authorization"] = f"Bearer {config.bearer_token}"
        elif config.api_key:
            headers[config.api_key_header] = config.api_key

    # 6. Target URL determination & dispatch
    target_base = config.target_base_url.rstrip("/")
    # Check if target is the local demo API
    is_local_demo = (
        "demo-target" in target_base
        or "127.0.0.1:8000" in target_base
        or "localhost:8000" in target_base
        or target_base == "/demo-target"
        or target_base.endswith("/demo-target")
    )

    timeout = httpx.Timeout(
        connect=config.connect_timeout,
        read=config.read_timeout,
        write=10.0,
        pool=10.0,
    )

    try:
        if is_local_demo:
            # Execute directly in-memory against demo_fastapi_app via ASGITransport!
            # Strip '/demo-target' prefix if present so path matches demo_fastapi_app routes
            target_path = path
            if target_path.startswith("/demo-target"):
                target_path = target_path[len("/demo-target"):]
            if not target_path.startswith("/"):
                target_path = "/" + target_path

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=demo_fastapi_app),
                base_url="http://demo-target",
                timeout=timeout,
            ) as demo_client:
                response = await demo_client.request(
                    method=method,
                    url=target_path,
                    params=params,
                    headers=headers,
                    json=json_payload,
                )
        elif client is not None:
            url = f"{target_base}/{path.lstrip('/')}"
            response = await client.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                json=json_payload,
            )
        else:
            url = f"{target_base}/{path.lstrip('/')}"
            async with httpx.AsyncClient(timeout=timeout) as live_client:
                response = await live_client.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=headers,
                    json=json_payload,
                )

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
            if config.mask_secrets:
                data, _, _ = global_redactor.redact_payload(data)
            if response.is_error:
                return {"error": True, "status_code": response.status_code, "detail": data}
            return {"status_code": response.status_code, "data": data}
        except Exception:
            text_body = response.text
            if config.mask_secrets:
                text_body, _ = global_redactor.redact_text(text_body)
            if response.is_error:
                return {"error": True, "status_code": response.status_code, "detail": text_body}
            return {"status_code": response.status_code, "text": text_body}

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
        err_msg = (
            global_redactor.redact_text(str(err))[0]
            if config.mask_secrets
            else "An error occurred while executing the HTTP request."
        )
        return {
            "error": True,
            "type": "request_error",
            "message": err_msg,
        }
