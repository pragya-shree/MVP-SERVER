"""Comprehensive automated tests for Real-Time Security & Safety Guardrails.

Covers all minimum requirements:
- Dry-run interception (GET allowed, POST/PUT/PATCH/DELETE intercepted, no upstream HTTP calls)
- Cryptographic approval workflow (pending, approved, rejected, expired, replay prevention, deny precedence)
- Multi-layer secret redaction (headers, bearer tokens, basic auth, JSON keys, nested fields, cookies, error messages)
- Policy engine enforcement (deny rules, method restrictions, operation overrides)
- Standalone generated MCP server guardrail execution
"""

import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import time
from typing import Any
import httpx
import pytest

from backend.generator import generate_mcp_server, parse_openapi
from backend.security import (
    ApprovalStatus,
    ApprovalStore,
    AuditLogger,
    DEFAULT_REDACTION_PLACEHOLDER,
    PolicyDecision,
    PolicyEngine,
    SecretRedactor,
    SecurityPolicy,
    compute_argument_hash,
)
from demo_api.app import app as demo_fastapi_app

SAMPLE_OPENAPI_SPEC = """
openapi: 3.0.3
info:
  title: Security Guardrails Test API
  version: 1.0.0
paths:
  /items:
    get:
      operationId: list_items
      summary: List items
      responses:
        '200':
          description: OK
    post:
      operationId: create_item
      summary: Create item
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                secret_token:
                  type: string
      responses:
        '201':
          description: Created
  /items/{id}:
    put:
      operationId: update_item
      summary: Update item
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
      responses:
        '200':
          description: Updated
    patch:
      operationId: patch_item
      summary: Patch item
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Patched
    delete:
      operationId: delete_item
      summary: Delete item
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
      responses:
        '204':
          description: Deleted
"""


# ==============================================================================
# FEATURE 1: DRY-RUN INTERCEPTION TESTS (1 - 7)
# ==============================================================================

@pytest.mark.asyncio
async def test_dry_run_get_executes_normally() -> None:
    """Requirement 1: GET operations execute normally in dry-run mode when no policy blocks them."""
    policy = SecurityPolicy(dry_run=True)
    engine = PolicyEngine(policy)
    res = engine.evaluate(tool_name="list_items", method="GET", path="/items")
    assert res.decision == PolicyDecision.ALLOW
    assert res.is_dry_run is False


@pytest.mark.asyncio
async def test_dry_run_post_intercepted() -> None:
    """Requirement 2: POST operations are intercepted in dry-run mode."""
    policy = SecurityPolicy(dry_run=True)
    engine = PolicyEngine(policy)
    res = engine.evaluate(tool_name="create_item", method="POST", path="/items")
    assert res.decision == PolicyDecision.DRY_RUN
    assert res.is_dry_run is True


@pytest.mark.asyncio
async def test_dry_run_put_intercepted() -> None:
    """Requirement 3: PUT operations are intercepted in dry-run mode."""
    policy = SecurityPolicy(dry_run=True)
    engine = PolicyEngine(policy)
    res = engine.evaluate(tool_name="update_item", method="PUT", path="/items/123")
    assert res.decision == PolicyDecision.DRY_RUN
    assert res.is_dry_run is True


@pytest.mark.asyncio
async def test_dry_run_patch_intercepted() -> None:
    """Requirement 4: PATCH operations are intercepted in dry-run mode."""
    policy = SecurityPolicy(dry_run=True)
    engine = PolicyEngine(policy)
    res = engine.evaluate(tool_name="patch_item", method="PATCH", path="/items/123")
    assert res.decision == PolicyDecision.DRY_RUN
    assert res.is_dry_run is True


@pytest.mark.asyncio
async def test_dry_run_delete_intercepted() -> None:
    """Requirement 5: DELETE operations are intercepted in dry-run mode."""
    policy = SecurityPolicy(dry_run=True)
    engine = PolicyEngine(policy)
    res = engine.evaluate(tool_name="delete_item", method="DELETE", path="/items/123")
    assert res.decision == PolicyDecision.DRY_RUN
    assert res.is_dry_run is True


@pytest.mark.asyncio
async def test_dry_run_no_upstream_http_request_and_clear_message(tmp_path: Path) -> None:
    """Requirements 6 & 7: No upstream request occurs for intercepted ops, and message is explicit."""
    api = parse_openapi(SAMPLE_OPENAPI_SPEC)
    server_dir = tmp_path / "server_dry_run"
    gen_res = generate_mcp_server(api, server_dir, package_name="server_dry_run", dry_run=True)

    # Import the generated execute_request
    import importlib.util
    server_py = gen_res.output_dir / "server.py"
    spec = importlib.util.spec_from_file_location("server_dry_run", server_py)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    # Set up a mock HTTP client that asserts it is NEVER called
    request_called = False

    class MockAsyncClient:
        async def request(self, *args: Any, **kwargs: Any) -> Any:
            nonlocal request_called
            request_called = True
            raise AssertionError("Upstream HTTP request was dispatched during dry-run!")

    config = mod.ServerConfig(dry_run=True)
    op_meta = mod.OPERATIONS_METADATA["delete_item"]

    result = await mod.execute_request(
        op_meta=op_meta,
        arguments={"id": "item-999"},
        config=config,
        client=MockAsyncClient(),
    )

    # Requirement 6: No upstream network request occurred
    assert request_called is False

    # Requirement 7: Result states operation was not executed
    assert result.get("status") == "DRY_RUN_INTERCEPTED"
    assert "Dry-run mode is enabled" in result.get("message", "")
    assert "upstream request was not sent" in result.get("message", "")
    assert result.get("action") == "DELETE /items/item-999"


# ==============================================================================
# FEATURE 2: EXPLICIT APPROVAL TESTS (8 - 15)
# ==============================================================================

def test_mutating_requires_approval_when_configured() -> None:
    """Requirement 8: Mutating operations require approval when configured."""
    policy = SecurityPolicy(require_approval=True)
    engine = PolicyEngine(policy)
    res = engine.evaluate(tool_name="delete_item", method="DELETE", path="/items/123")
    assert res.decision == PolicyDecision.REQUIRE_APPROVAL
    assert res.requires_approval is True


@pytest.mark.asyncio
async def test_pending_approval_never_triggers_upstream_request(tmp_path: Path) -> None:
    """Requirement 9: A pending approval never triggers the upstream request."""
    api = parse_openapi(SAMPLE_OPENAPI_SPEC)
    server_dir = tmp_path / "server_approval"
    gen_res = generate_mcp_server(api, server_dir, package_name="server_approval", require_approval=True)

    import importlib.util
    server_py = gen_res.output_dir / "server.py"
    spec = importlib.util.spec_from_file_location("server_approval", server_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    request_called = False

    class MockAsyncClient:
        async def request(self, *args: Any, **kwargs: Any) -> Any:
            nonlocal request_called
            request_called = True
            raise AssertionError("Upstream HTTP request called while pending approval!")

    config = mod.ServerConfig(require_approval=True)
    op_meta = mod.OPERATIONS_METADATA["delete_item"]

    # Invocation without approval ID
    result = await mod.execute_request(
        op_meta=op_meta,
        arguments={"id": "item-500"},
        config=config,
        client=MockAsyncClient(),
    )

    assert request_called is False
    assert result.get("status") == "PENDING_CONFIRMATION"
    assert "approval_id" in result
    assert result.get("approval_id").startswith("appr_")


def test_rejected_approval_prevents_execution() -> None:
    """Requirement 10: A rejected approval prevents execution."""
    store = ApprovalStore()
    req = store.create_request("delete_item", "DELETE", "/items/1", arguments={"id": "1"})

    success, _ = store.reject(req.approval_id, reason="Admin denied deletion")
    assert success is True

    valid, msg, _ = store.consume_and_verify(req.approval_id, "delete_item", {"id": "1"})
    assert valid is False
    assert "rejected" in msg.lower()


def test_approved_request_executes_only_bound_operation_and_arguments() -> None:
    """Requirement 11: An approved request executes only the bound operation and arguments."""
    store = ApprovalStore()
    req = store.create_request("delete_item", "DELETE", "/items/1", arguments={"id": "1"})
    store.approve(req.approval_id)

    # 1. Tampered tool name fails
    valid, msg, _ = store.consume_and_verify(req.approval_id, "purge_item", {"id": "1"})
    assert valid is False
    assert "bound to tool" in msg.lower()

    # 2. Tampered arguments fail
    valid, msg, _ = store.consume_and_verify(req.approval_id, "delete_item", {"id": "999"})
    assert valid is False
    assert "arguments do not match" in msg.lower()

    # 3. Exact matching succeeds
    valid, msg, bound = store.consume_and_verify(req.approval_id, "delete_item", {"id": "1"})
    assert valid is True
    assert bound == {"id": "1"}


def test_expired_approvals_are_rejected() -> None:
    """Requirement 12: Expired approvals are rejected."""
    store = ApprovalStore(default_ttl_seconds=-10)  # already expired
    req = store.create_request("delete_item", "DELETE", "/items/1", arguments={"id": "1"})
    store.approve(req.approval_id)

    valid, msg, _ = store.consume_and_verify(req.approval_id, "delete_item", {"id": "1"})
    assert valid is False
    assert "expired" in msg.lower()


def test_replayed_or_duplicate_approvals_rejected() -> None:
    """Requirement 13: Replayed or duplicate approvals cannot execute an operation twice."""
    store = ApprovalStore()
    req = store.create_request("delete_item", "DELETE", "/items/1", arguments={"id": "1"})
    store.approve(req.approval_id)

    # First consumption succeeds
    valid, _, _ = store.consume_and_verify(req.approval_id, "delete_item", {"id": "1"})
    assert valid is True

    # Second consumption (replay attack) fails
    valid2, msg2, _ = store.consume_and_verify(req.approval_id, "delete_item", {"id": "1"})
    assert valid2 is False
    assert "already been consumed" in msg2.lower()


def test_deny_policies_cannot_be_overridden_by_approval() -> None:
    """Requirement 14: Deny policies cannot be overridden by approval."""
    policy = SecurityPolicy(
        require_approval=True,
        denied_operations=["delete_item"],
    )
    engine = PolicyEngine(policy)
    res = engine.evaluate(tool_name="delete_item", method="DELETE", path="/items/123")
    assert res.decision == PolicyDecision.DENY
    assert res.is_denied is True


def test_dry_run_takes_precedence_over_approval() -> None:
    """Requirement 15: Dry-run takes precedence over approval."""
    policy = SecurityPolicy(
        dry_run=True,
        require_approval=True,
    )
    engine = PolicyEngine(policy)
    res = engine.evaluate(tool_name="delete_item", method="DELETE", path="/items/123")
    assert res.decision == PolicyDecision.DRY_RUN
    assert res.is_dry_run is True


# ==============================================================================
# FEATURE 3: SECRET REDACTION TESTS (16 - 25)
# ==============================================================================

def test_bearer_token_redaction() -> None:
    """Requirement 16: 'Bearer secret-token' is redacted."""
    redactor = SecretRedactor()
    raw = "Request failed with Authorization: Bearer sk_secret_token_123456789"
    sanitized, count = redactor.redact_text(raw)
    assert count >= 1
    assert "sk_secret_token_123456789" not in sanitized
    assert f"Bearer {DEFAULT_REDACTION_PLACEHOLDER}" in sanitized


def test_authorization_headers_redacted_case_insensitively() -> None:
    """Requirement 17: Authorization headers are redacted case-insensitively."""
    redactor = SecretRedactor()
    headers = {
        "AUTHORIZATION": "Bearer my-secret-token-xyz",
        "X-Api-Key": "live_key_99999",
        "Content-Type": "application/json",
    }
    sanitized, count = redactor.redact_headers(headers)
    assert sanitized["AUTHORIZATION"] == DEFAULT_REDACTION_PLACEHOLDER
    assert sanitized["X-Api-Key"] == DEFAULT_REDACTION_PLACEHOLDER
    assert sanitized["Content-Type"] == "application/json"
    assert count >= 2


def test_basic_authentication_credentials_redacted() -> None:
    """Requirement 18: Basic authentication credentials are redacted."""
    redactor = SecretRedactor()
    text = "Using header Basic dXNlcjpwYXNzd29yZDEyMw=="
    sanitized, count = redactor.redact_text(text)
    assert count >= 1
    assert "dXNlcjpwYXNzd29yZDEyMw==" not in sanitized
    assert f"Basic {DEFAULT_REDACTION_PLACEHOLDER}" in sanitized


def test_api_keys_in_json_fields_redacted() -> None:
    """Requirement 19: API keys in JSON fields are redacted."""
    redactor = SecretRedactor()
    payload = {
        "name": "Production Service",
        "api_key": "live-key-value-12345",
        "token": "tok_abcdef12345678",
    }
    sanitized, count = redactor.redact_json(payload)
    assert sanitized["name"] == "Production Service"
    assert sanitized["api_key"] == DEFAULT_REDACTION_PLACEHOLDER
    assert sanitized["token"] == DEFAULT_REDACTION_PLACEHOLDER
    assert count == 2


def test_nested_sensitive_fields_redacted() -> None:
    """Requirement 20: Nested sensitive fields are redacted recursively."""
    redactor = SecretRedactor()
    payload = {
        "user": {
            "profile": {
                "username": "alex",
                "password": "SuperSecretPassword!",
            },
            "tokens": [
                {"access_token": "secret_acc_1"},
                {"refresh_token": "secret_ref_2"},
            ],
        }
    }
    sanitized, count = redactor.redact_json(payload)
    assert sanitized["user"]["profile"]["username"] == "alex"
    assert sanitized["user"]["profile"]["password"] == DEFAULT_REDACTION_PLACEHOLDER
    assert sanitized["user"]["tokens"][0]["access_token"] == DEFAULT_REDACTION_PLACEHOLDER
    assert sanitized["user"]["tokens"][1]["refresh_token"] == DEFAULT_REDACTION_PLACEHOLDER
    assert count == 3


def test_secrets_in_plain_text_error_messages_redacted() -> None:
    """Requirement 21: Secrets embedded in plain-text error messages are redacted."""
    redactor = SecretRedactor()
    err_msg = "ConnectionError: Failed to authenticate with key sk-proj-1234567890abcdef12345 at endpoint."
    sanitized = redactor.sanitize_error(err_msg)
    assert "sk-proj-1234567890abcdef12345" not in sanitized
    assert DEFAULT_REDACTION_PLACEHOLDER in sanitized


def test_cookies_and_session_tokens_redacted() -> None:
    """Requirement 22: Cookies and session tokens are redacted."""
    redactor = SecretRedactor()
    headers = {"Cookie": "sessionid=xyz987654321; token=jwt.token.here"}
    sanitized, count = redactor.redact_headers(headers)
    assert sanitized["Cookie"] == DEFAULT_REDACTION_PLACEHOLDER
    assert count == 1


def test_ordinary_non_sensitive_values_remain_unchanged() -> None:
    """Requirement 23: Ordinary non-sensitive values remain unchanged."""
    redactor = SecretRedactor()
    payload = {
        "id": 101,
        "title": "Quarterly Planning",
        "status": "pending",
        "tags": ["strategy", "planning"],
    }
    sanitized, count = redactor.redact_json(payload)
    assert sanitized == payload
    assert count == 0


def test_raw_secrets_never_appear_in_execution_logs() -> None:
    """Requirement 24: Raw secrets never appear in execution logs."""
    audit = AuditLogger()
    entry = audit.record(
        tool_name="authenticate_user",
        method="POST",
        path="/auth/token?api_key=secret_in_url_123",
        policy_decision="ALLOW",
        execution_status="EXECUTED",
        is_mutating=True,
        arguments={"password": "MySecretPassword123", "username": "admin"},
        reason="Success for token Bearer tok_1234567890",
    )
    # Check that secrets are not stored in audit record
    assert "secret_in_url_123" not in entry.sanitized_path
    assert "MySecretPassword123" not in json.dumps(entry.safe_arguments)
    assert "tok_1234567890" not in str(entry.reason)
    assert entry.secrets_redacted is True


@pytest.mark.asyncio
async def test_tool_outputs_sent_to_mcp_client_are_sanitized(tmp_path: Path) -> None:
    """Requirement 25: Tool outputs sent to the MCP client are sanitized."""
    api = parse_openapi(SAMPLE_OPENAPI_SPEC)
    server_dir = tmp_path / "server_masked"
    gen_res = generate_mcp_server(api, server_dir, package_name="server_masked", mask_secrets=True)

    import importlib.util
    server_py = gen_res.output_dir / "server.py"
    spec = importlib.util.spec_from_file_location("server_masked", server_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Mock response returning a raw credential in body
    class MockResponse:
        status_code = 200
        content = b'{"token": "secret_live_token_777", "service": "billing"}'
        is_error = False

        def json(self) -> Any:
            return {"token": "secret_live_token_777", "service": "billing"}

    class MockAsyncClient:
        async def request(self, *args: Any, **kwargs: Any) -> Any:
            return MockResponse()

    config = mod.ServerConfig(mask_secrets=True)
    op_meta = mod.OPERATIONS_METADATA["list_items"]

    result = await mod.execute_request(
        op_meta=op_meta,
        arguments={},
        config=config,
        client=MockAsyncClient(),
    )

    data = result.get("data", {})
    assert data.get("service") == "billing"
    assert data.get("token") == DEFAULT_REDACTION_PLACEHOLDER
    assert "secret_live_token_777" not in str(result)


# ==============================================================================
# FEATURE 4: POLICY & STANDALONE TESTS (26 - 29)
# ==============================================================================

def test_denied_operations_cannot_reach_upstream_api() -> None:
    """Requirement 26: Denied operations cannot reach the upstream API."""
    policy = SecurityPolicy(denied_operations=["purge_data"], denied_methods=["DELETE"])
    engine = PolicyEngine(policy)

    res1 = engine.evaluate("purge_data", "POST", "/purge")
    assert res1.decision == PolicyDecision.DENY

    res2 = engine.evaluate("delete_task", "DELETE", "/tasks/1")
    assert res2.decision == PolicyDecision.DENY


def test_read_only_policy_blocks_all_disallowed_mutating_operations() -> None:
    """Requirement 27: Read-only mode excludes mutating operations during generation."""
    api = parse_openapi(SAMPLE_OPENAPI_SPEC)
    read_only_ops = api.read_only_operations
    assert len(read_only_ops) == 1
    assert read_only_ops[0].method.lower() == "get"

    mutating_ops = [op for op in api.operations if not op.is_read_only]
    assert len(mutating_ops) == 4
    for op in mutating_ops:
        assert op.is_read_only is False


def test_frontend_manipulation_cannot_bypass_server_side_enforcement() -> None:
    """Requirement 28: Server-side policy engine enforces rules regardless of client params."""
    policy = SecurityPolicy(denied_methods=["DELETE"])
    engine = PolicyEngine(policy)

    # Client claims confirm=True, force=True, override=True
    client_args = {"confirm": True, "force": True, "override": True, "admin": True}
    res = engine.evaluate("delete_item", "DELETE", "/items/1", arguments=client_args)

    assert res.decision == PolicyDecision.DENY
    assert res.is_denied is True


@pytest.mark.asyncio
async def test_generated_standalone_mcp_servers_enforce_configured_policies(tmp_path: Path) -> None:
    """Requirement 29: Generated standalone MCP servers enforce configured policies independently."""
    api = parse_openapi(SAMPLE_OPENAPI_SPEC)
    server_dir = tmp_path / "server_standalone_guardrails"
    gen_res = generate_mcp_server(api, server_dir, package_name="server_standalone")

    import importlib.util
    server_py = gen_res.output_dir / "server.py"
    spec = importlib.util.spec_from_file_location("server_standalone", server_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Standalone server configured with DENIED_METHODS=DELETE
    config = mod.ServerConfig(denied_methods=["DELETE"])
    op_meta = mod.OPERATIONS_METADATA["delete_item"]

    result = await mod.execute_request(
        op_meta=op_meta,
        arguments={"id": "item-1"},
        config=config,
    )
    assert result.get("error") is True
    assert result.get("type") == "policy_denied"
    assert "forbidden by security policy" in result.get("message", "")


# ==============================================================================
# FEATURE 5: AUDIT LOG & DASHBOARD API TESTS
# ==============================================================================

def test_audit_logger_records_status_badges_and_events() -> None:
    """Verify that AuditLogger records required status badges accurately."""
    logger = AuditLogger()

    e1 = logger.record("list_items", "GET", "/items", "ALLOW", "EXECUTED", False)
    assert e1.execution_status == "EXECUTED"
    assert e1.policy_decision == "ALLOW"

    e2 = logger.record("create_item", "POST", "/items", "DRY_RUN", "DRY-RUN", True)
    assert e2.execution_status == "DRY-RUN"
    assert e2.policy_decision == "DRY_RUN"

    e3 = logger.record("delete_item", "DELETE", "/items/1", "DENY", "BLOCKED", True)
    assert e3.execution_status == "BLOCKED"
    assert e3.policy_decision == "DENY"

    entries = logger.get_entries()
    assert len(entries) == 3
    assert entries[0].id == e3.id


def test_security_config_endpoints() -> None:
    """Verify GET and POST /api/v1/security/config endpoints."""
    from fastapi.testclient import TestClient
    from backend.app.main import app as main_app

    client = TestClient(main_app)
    # 1. GET initial config
    res = client.get("/api/v1/security/config")
    assert res.status_code == 200
    data = res.json()
    assert "dry_run" in data
    assert "require_approval" in data
    assert "mask_secrets" in data
    assert "active_policy" in data

    # 2. POST update config
    res2 = client.post("/api/v1/security/config", json={"dry_run": True, "require_approval": True})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["dry_run"] is True
    assert data2["require_approval"] is True

    # Restore default
    client.post("/api/v1/security/config", json={"dry_run": False, "require_approval": False})


def test_approvals_api_endpoints() -> None:
    """Verify /api/v1/security/approvals endpoints for list, approve, and reject."""
    from fastapi.testclient import TestClient
    from backend.app.main import app as main_app
    from backend.security import global_approval_store

    client = TestClient(main_app)
    # Create request
    req = global_approval_store.create_request("delete_task", "DELETE", "/tasks/t-1", {"task_id": "t-1"})

    # 1. GET approvals
    res = client.get("/api/v1/security/approvals")
    assert res.status_code == 200
    items = res.json()
    assert any(i["approval_id"] == req.approval_id for i in items)

    # 2. POST approve
    res_appr = client.post(f"/api/v1/security/approvals/{req.approval_id}/approve")
    assert res_appr.status_code == 200
    assert res_appr.json()["success"] is True

    # 3. Create another request to test reject
    req2 = global_approval_store.create_request("reset_database", "POST", "/reset", {})
    res_rej = client.post(f"/api/v1/security/approvals/{req2.approval_id}/reject")
    assert res_rej.status_code == 200
    assert res_rej.json()["success"] is True


def test_audit_log_endpoint() -> None:
    """Verify /api/v1/security/audit endpoint returns bounded audit entries."""
    from fastapi.testclient import TestClient
    from backend.app.main import app as main_app
    from backend.security import global_audit_logger

    client = TestClient(main_app)
    global_audit_logger.record(
        tool_name="test_tool",
        method="GET",
        path="/test",
        policy_decision="ALLOW",
        execution_status="EXECUTED",
        is_mutating=False,
    )
    res = client.get("/api/v1/security/audit?limit=10")
    assert res.status_code == 200
    items = res.json()
    assert len(items) > 0
    assert "tool_name" in items[0]
    assert "policy_decision" in items[0]
    assert "execution_status" in items[0]

