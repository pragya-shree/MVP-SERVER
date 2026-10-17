"""Agent and demo API adapter endpoints exposing safe playground and spec operations to the frontend."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from agent.agent import MCPAgent
from agent.client import MCPClient
from backend.generator import generate_mcp_server, parse_openapi
from demo_api.app import app as demo_fastapi_app
from demo_api.repository import repository as demo_repository

router = APIRouter(prefix="/api/v1", tags=["agent-demo"])

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLES_DIR = REPO_ROOT / "examples"
DEMO_SPEC_FILE = EXAMPLES_DIR / "task_management_api.yaml"


def _get_demo_generated_dir() -> Path:
    """Get writable directory for demo task MCP package."""
    storage_dir = Path(os.environ.get("GENERATOR_STORAGE_DIR", "/tmp/anything-to-mcp/artifacts"))
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        target_dir = storage_dir / "demo_task_mcp"
    else:
        target_dir = REPO_ROOT / "generated" / "demo_task_mcp"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


GENERATED_DIR = _get_demo_generated_dir()


def get_target_base_url(base_url: Optional[str] = None) -> str:
    """Resolve target API base URL for demo operations."""
    if base_url:
        return base_url
    if "DEMO_API_BASE_URL" in os.environ and os.environ["DEMO_API_BASE_URL"].strip():
        return os.environ["DEMO_API_BASE_URL"].strip()
    vercel_url = os.environ.get("VERCEL_URL", "").strip()
    if vercel_url:
        return f"https://{vercel_url}/demo-target"
    return "http://127.0.0.1:8000/demo-target"



from backend.security import (
    global_approval_store,
    global_audit_logger,
    global_policy_engine,
    global_redactor,
    PolicyDecision,
    SecurityPolicy,
)

class SecurityConfigRequest(BaseModel):
    """Payload to update runtime security guardrails configuration."""

    dry_run: Optional[bool] = None
    require_approval: Optional[bool] = None
    mask_secrets: Optional[bool] = None
    denied_operations: Optional[list[str]] = None
    denied_methods: Optional[list[str]] = None


class SecurityConfigResponse(BaseModel):
    """Current runtime security guardrails configuration."""

    dry_run: bool
    require_approval: bool
    mask_secrets: bool
    denied_operations: list[str]
    denied_methods: list[str]
    active_policy: str


class AgentExecuteRequest(BaseModel):
    """Payload for submitting a natural language prompt to the agent."""

    request: str = Field(min_length=1, description="Natural language prompt for the agent")
    confirm_destructive: bool = Field(default=False, description="Explicit approval to execute destructive tool calls")
    approval_id: Optional[str] = Field(default=None, description="Explicit security approval ID for sensitive operations")


class AgentResetRequest(BaseModel):
    """Payload for requesting database reset."""

    confirm: bool = Field(default=False, description="Confirmation to wipe and restore seed data")


class AgentExecuteResponse(BaseModel):
    """Execution response returned to the frontend."""

    success: bool
    message: str
    tool_invocations: list[dict[str, Any]] = Field(default_factory=list)
    data: Optional[Any] = None
    requires_confirmation: bool = False
    requires_approval: bool = False
    approval_id: Optional[str] = None
    pending_action: Optional[dict[str, Any]] = None
    policy_decision: Optional[str] = None
    execution_status: Optional[str] = None
    secrets_redacted: bool = False
    redaction_count: int = 0


class DemoSpecResponse(BaseModel):
    """Bundled demo specification response."""

    filename: str
    spec: str
    format: str
    title: str
    version: str
    operation_count: int
    default_base_url: str



def ensure_demo_server_generated(base_url: Optional[str] = None) -> Path:
    """Ensure generated/demo_task_mcp/server.py exists and is runnable."""
    target_base = get_target_base_url(base_url)
    gen_dir = _get_demo_generated_dir()
    server_script = gen_dir / "server.py"

    if not server_script.exists():
        try:
            api_model = parse_openapi(demo_fastapi_app.openapi())
            generate_mcp_server(
                api=api_model,
                output_dir=gen_dir,
                package_name="demo_task_mcp",
                base_url=target_base,
                overwrite=True,
            )
        except Exception:
            pass

    return server_script


@router.get(
    "/demo/spec",
    response_model=DemoSpecResponse,
    summary="Get bundled Task Management OpenAPI specification",
    description="Returns the repository's known-safe bundled demo specification for quick loading into the workspace.",
)
async def get_demo_spec() -> DemoSpecResponse:
    """Return bundled demo OpenAPI specification text and metadata."""
    if not DEMO_SPEC_FILE.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bundled demo specification file not found in repository.",
        )

    content = DEMO_SPEC_FILE.read_text(encoding="utf-8")
    api = parse_openapi(content)
    base_url = get_target_base_url()

    return DemoSpecResponse(
        filename="task_management_api.yaml",
        spec=content,
        format="yaml",
        title=api.title,
        version=api.version,
        operation_count=len(api.operations),
        default_base_url=base_url,
    )


@router.get(
    "/agent/status",
    summary="Agent playground status check",
    description="Returns status of the demo API, repository item count, and MCP server readiness.",
)
async def get_agent_status() -> dict[str, Any]:
    """Check readiness of agent, MCP server, and in-memory demo data."""
    server_script = ensure_demo_server_generated()
    summary = demo_repository.get_summary()
    target_base = get_target_base_url()

    return {
        "status": "ready",
        "service": "demo-task-management-agent",
        "server_script": str(server_script.name),
        "target_base_url": target_base,
        "total_tasks": summary.total_tasks,
        "counts_by_status": summary.counts_by_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


_CACHED_DEMO_TOOLS: Optional[list[dict[str, Any]]] = None


@router.get(
    "/agent/tools",
    summary="List demo MCP tools dynamically discovered from the server",
    description="Connects to the demo MCP server via stdio, calls session.list_tools(), and returns tool definitions.",
)
async def get_agent_tools() -> list[dict[str, Any]]:
    """Discover tools dynamically using the real MCP stdio client."""
    global _CACHED_DEMO_TOOLS
    if _CACHED_DEMO_TOOLS is not None:
        return _CACHED_DEMO_TOOLS

    server_script = ensure_demo_server_generated()
    target_base = get_target_base_url()

    client = MCPClient(
        server_script=server_script,
        env={"TARGET_BASE_URL": target_base},
    )

    try:
        async with client:
            tools = await client.list_tools()
            result = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
            _CACHED_DEMO_TOOLS = result
            return result
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to discover tools via MCP stdio: {err}",
        )


@router.get(
    "/security/config",
    response_model=SecurityConfigResponse,
    summary="Get active security guardrails configuration",
    description="Returns current state of dry-run, approval mode, secret masking, and active policy rules.",
)
async def get_security_config() -> SecurityConfigResponse:
    """Return active safety settings and policy mode."""
    pol = global_policy_engine.policy
    active = "GUARDRAILS ACTIVE"
    if pol.dry_run:
        active = "DRY-RUN (SIMULATION ONLY)"
    elif pol.require_approval:
        active = "STRICT APPROVAL REQUIRED"
    elif not pol.mask_secrets:
        active = "WARNING: SECRETS UNMASKED"

    return SecurityConfigResponse(
        dry_run=pol.dry_run,
        require_approval=pol.require_approval,
        mask_secrets=pol.mask_secrets,
        denied_operations=pol.denied_operations,
        denied_methods=pol.denied_methods,
        active_policy=active,
    )


@router.post(
    "/security/config",
    response_model=SecurityConfigResponse,
    summary="Update active security guardrails configuration",
    description="Dynamically updates security toggles (dry-run, require-approval, mask-secrets).",
)
async def update_security_config(payload: SecurityConfigRequest) -> SecurityConfigResponse:
    """Dynamically toggle guardrails like dry-run, approval mode, and secret masking."""
    pol = global_policy_engine.update_policy(
        dry_run=payload.dry_run,
        require_approval=payload.require_approval,
        mask_secrets=payload.mask_secrets,
        denied_operations=payload.denied_operations,
        denied_methods=payload.denied_methods,
    )
    if payload.mask_secrets is not None:
        global_redactor.enabled = payload.mask_secrets

    return await get_security_config()


@router.get(
    "/security/approvals",
    summary="List pending and recent human approval requests",
    description="Returns approval requests with argument fingerprint, time-to-live countdown, and current status.",
)
async def list_approvals() -> list[dict[str, Any]]:
    """Return all tracked approval requests."""
    return [req.to_dict() for req in global_approval_store.list_requests()]


@router.post(
    "/security/approvals/{approval_id}/approve",
    summary="Explicitly approve a pending sensitive operation",
    description="Transitions an approval request to APPROVED status so it can be consumed for execution.",
)
async def approve_request(approval_id: str) -> dict[str, Any]:
    """Approve a pending operation token for execution."""
    success, msg = global_approval_store.approve(approval_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    req = global_approval_store.get_request(approval_id)
    if req:
        global_audit_logger.record(
            tool_name=req.tool_name,
            method=req.method,
            path=req.path,
            policy_decision="REQUIRE_APPROVAL",
            execution_status="APPROVED",
            is_mutating=True,
            arguments=req.safe_arguments,
            approval_id=approval_id,
            reason="Human approved operation via security dashboard",
        )
    return {"success": True, "message": msg, "approval_id": approval_id}


@router.post(
    "/security/approvals/{approval_id}/reject",
    summary="Explicitly reject a pending sensitive operation",
    description="Rejects an approval token and prevents upstream execution.",
)
async def reject_request(approval_id: str) -> dict[str, Any]:
    """Reject and revoke an approval token."""
    success, msg = global_approval_store.reject(approval_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    req = global_approval_store.get_request(approval_id)
    if req:
        global_audit_logger.record(
            tool_name=req.tool_name,
            method=req.method,
            path=req.path,
            policy_decision="REQUIRE_APPROVAL",
            execution_status="BLOCKED",
            is_mutating=True,
            arguments=req.safe_arguments,
            approval_id=approval_id,
            reason="Human rejected operation via security dashboard",
        )
    return {"success": True, "message": msg, "approval_id": approval_id}


@router.get(
    "/security/audit",
    summary="Get safe execution history and audit log",
    description="Returns bounded execution events with status badges, redacted arguments, and timestamps.",
)
async def get_audit_log(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent audit log entries with status badges and redaction indicators."""
    entries = global_audit_logger.get_entries(limit=limit)
    return [entry.model_dump() for entry in entries]


@router.post(
    "/agent/execute",
    response_model=AgentExecuteResponse,
    summary="Execute a natural language request through the real MCP Agent",
    description="Plans intent against discovered MCP tools, enforces safety confirmation for destructive actions, and executes via stdio.",
)
async def execute_agent_request(payload: AgentExecuteRequest) -> AgentExecuteResponse:
    """Execute natural language query through the real MCPAgent over stdio transport with guardrails."""
    server_script = ensure_demo_server_generated()
    target_base = get_target_base_url()

    # Pass active guardrail environment variables to child MCP server
    policy = global_policy_engine.policy
    child_env = {
        "TARGET_BASE_URL": target_base,
        "DRY_RUN": "true" if policy.dry_run else "false",
        "REQUIRE_APPROVAL": "true" if policy.require_approval else "false",
        "MASK_SECRETS": "true" if policy.mask_secrets else "false",
        "DENIED_OPERATIONS": ",".join(policy.denied_operations),
        "DENIED_METHODS": ",".join(policy.denied_methods),
    }

    client = MCPClient(
        server_script=server_script,
        env=child_env,
    )

    try:
        async with client:
            agent = MCPAgent(client=client)
            response = await agent.execute(
                request=payload.request,
                confirm_destructive=payload.confirm_destructive,
                approval_id=payload.approval_id,
            )

            # Check if any tool result or message had secrets redacted
            sanitized_msg, msg_redacted, msg_count = global_redactor.redact_payload(response.message)
            sanitized_data, data_redacted, data_count = global_redactor.redact_payload(response.data)

            total_redactions = msg_count + data_count
            secrets_were_redacted = (
                response.secrets_redacted or msg_redacted or data_redacted or total_redactions > 0
            )

            # Record in execution audit log
            tool_name = "agent_action"
            status_code = None
            if response.tool_invocations:
                tool_name = response.tool_invocations[0].get("tool_name", "agent_action")
                status_code = response.tool_invocations[0].get("status_code")

            policy_dec = response.policy_decision or "ALLOW"
            exec_stat = response.execution_status or ("EXECUTED" if response.success else "FAILED")
            if secrets_were_redacted and exec_stat == "EXECUTED":
                exec_stat = "SECRETS REDACTED"

            global_audit_logger.record(
                tool_name=tool_name,
                method="POST" if any(k in tool_name for k in ("create", "update", "delete", "reset")) else "GET",
                path=f"/agent/{tool_name}",
                policy_decision=policy_dec,
                execution_status=exec_stat,
                is_mutating=any(k in tool_name for k in ("create", "update", "delete", "reset")),
                arguments={"request": payload.request},
                reason=sanitized_msg if not response.success else None,
                status_code=status_code,
                secrets_redacted=secrets_were_redacted,
                redaction_count=total_redactions,
                approval_id=response.approval_id,
            )

            return AgentExecuteResponse(
                success=response.success,
                message=sanitized_msg,
                tool_invocations=response.tool_invocations,
                data=sanitized_data,
                requires_confirmation=response.requires_confirmation,
                requires_approval=response.requires_approval,
                approval_id=response.approval_id,
                pending_action=response.pending_action,
                policy_decision=policy_dec,
                execution_status=exec_stat,
                secrets_redacted=secrets_were_redacted,
                redaction_count=total_redactions,
            )
    except Exception as err:
        clean_err = global_redactor.sanitize_error(err)
        global_audit_logger.record(
            tool_name="agent_error",
            method="UNKNOWN",
            path="/agent/execute",
            policy_decision="ALLOW",
            execution_status="FAILED",
            is_mutating=False,
            arguments={"request": payload.request},
            reason=clean_err,
        )
        return AgentExecuteResponse(
            success=False,
            message=f"Agent execution encountered an error: {clean_err}",
            requires_confirmation=False,
            execution_status="FAILED",
        )


@router.post(
    "/agent/reset",
    summary="Reset demo database to seed state",
    description="Explicitly resets demo tasks and projects after confirmation verification.",
)
async def reset_demo_database(payload: Optional[AgentResetRequest] = None) -> dict[str, Any]:
    """Reset repository data store if explicitly confirmed."""
    if payload is None or not payload.confirm:
        return {
            "success": False,
            "requires_confirmation": True,
            "message": "Confirmation required: Resetting will restore all tasks to the original seed data and erase custom changes.",
        }

    demo_repository.reset()
    return {
        "success": True,
        "requires_confirmation": False,
        "message": "Demo database successfully reset to initial seed state.",
        "total_tasks": 4,
    }

