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
GENERATED_DIR = REPO_ROOT / "generated" / "demo_task_mcp"


class AgentExecuteRequest(BaseModel):
    """Payload for submitting a natural language prompt to the agent."""

    request: str = Field(min_length=1, description="Natural language prompt for the agent")
    confirm_destructive: bool = Field(default=False, description="Explicit approval to execute destructive tool calls")


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
    pending_action: Optional[dict[str, Any]] = None


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
    target_base = base_url or os.environ.get("DEMO_API_BASE_URL", "http://127.0.0.1:8000/demo-target")
    server_script = GENERATED_DIR / "server.py"

    if not server_script.exists():
        api_model = parse_openapi(demo_fastapi_app.openapi())
        generate_mcp_server(
            api=api_model,
            output_dir=GENERATED_DIR,
            package_name="demo_task_mcp",
            base_url=target_base,
            overwrite=True,
        )

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
    base_url = os.environ.get("DEMO_API_BASE_URL", "http://127.0.0.1:8000/demo-target")

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
    target_base = os.environ.get("DEMO_API_BASE_URL", "http://127.0.0.1:8000/demo-target")

    return {
        "status": "ready",
        "service": "demo-task-management-agent",
        "server_script": str(server_script.name),
        "target_base_url": target_base,
        "total_tasks": summary.total_tasks,
        "counts_by_status": summary.counts_by_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/agent/tools",
    summary="List demo MCP tools dynamically discovered from the server",
    description="Connects to the demo MCP server via stdio, calls session.list_tools(), and returns tool definitions.",
)
async def get_agent_tools() -> list[dict[str, Any]]:
    """Discover tools dynamically using the real MCP stdio client."""
    server_script = ensure_demo_server_generated()
    target_base = os.environ.get("DEMO_API_BASE_URL", "http://127.0.0.1:8000/demo-target")

    client = MCPClient(
        server_script=server_script,
        env={"TARGET_BASE_URL": target_base},
    )

    try:
        async with client:
            tools = await client.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to discover tools via MCP stdio: {err}",
        )


@router.post(
    "/agent/execute",
    response_model=AgentExecuteResponse,
    summary="Execute a natural language request through the real MCP Agent",
    description="Plans intent against discovered MCP tools, enforces safety confirmation for destructive actions, and executes via stdio.",
)
async def execute_agent_request(payload: AgentExecuteRequest) -> AgentExecuteResponse:
    """Execute natural language query through the real MCPAgent over stdio transport."""
    server_script = ensure_demo_server_generated()
    target_base = os.environ.get("DEMO_API_BASE_URL", "http://127.0.0.1:8000/demo-target")

    client = MCPClient(
        server_script=server_script,
        env={"TARGET_BASE_URL": target_base},
    )

    try:
        async with client:
            agent = MCPAgent(client=client)
            response = await agent.execute(
                request=payload.request,
                confirm_destructive=payload.confirm_destructive,
            )

            return AgentExecuteResponse(
                success=response.success,
                message=response.message,
                tool_invocations=response.tool_invocations,
                data=response.data,
                requires_confirmation=response.requires_confirmation,
                pending_action=response.pending_action,
            )
    except Exception as err:
        return AgentExecuteResponse(
            success=False,
            message=f"Agent execution encountered an error: {err}",
            requires_confirmation=False,
        )


@router.post(
    "/agent/reset",
    summary="Reset demo database to seed state",
    description="Explicitly resets demo tasks and projects after confirmation verification.",
)
async def reset_demo_database(payload: AgentResetRequest) -> dict[str, Any]:
    """Reset repository data store if explicitly confirmed."""
    if not payload.confirm:
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
