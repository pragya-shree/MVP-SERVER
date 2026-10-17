"""High-level AI agent coordinating MCP client and intent planner."""

import json
from typing import Any, Optional

from agent.client import MCPClient
from agent.exceptions import ConfirmationRequiredError
from agent.models import AgentResponse, MCPToolDefinition, MCPToolResult, PlanAction, PlanResult
from agent.planner import BasePlanner, create_default_planner


class MCPAgent:
    """Agent orchestrating MCP tool discovery, planning, confirmation guards, and execution."""

    def __init__(
        self,
        client: MCPClient,
        planner: Optional[BasePlanner] = None,
    ) -> None:
        self.client = client
        self.planner = planner or create_default_planner()
        self._discovered_tools: list[MCPToolDefinition] = []

    async def initialize(self) -> list[MCPToolDefinition]:
        """Connect to MCP server and discover exposed tools."""
        if not self.client.is_connected:
            await self.client.connect()
        self._discovered_tools = await self.client.list_tools()
        return self._discovered_tools

    @property
    def discovered_tools(self) -> list[MCPToolDefinition]:
        """Return list of discovered tools."""
        return self._discovered_tools

    async def execute(
        self,
        request: str,
        confirm_destructive: bool = False,
    ) -> AgentResponse:
        """Process a natural language request through planning, validation, and MCP tool execution."""
        # Ensure MCP client is connected and tools are discovered
        if not self._discovered_tools:
            await self.initialize()

        # Step 1: Generate plan from natural language query
        plan: PlanResult = await self.planner.plan(request, self._discovered_tools)

        # Handle requests needing clarification
        if plan.clarification_needed:
            return AgentResponse(
                success=False,
                message=plan.clarification_needed,
                data=None,
            )

        # Handle unsupported requests
        if plan.unsupported:
            return AgentResponse(
                success=False,
                message=plan.explanation or "Request is unsupported by discovered API tools.",
                data=None,
            )

        # Handle empty plans
        if not plan.actions:
            return AgentResponse(
                success=False,
                message="No actions could be determined for your request.",
                data=None,
            )

        tool_invocations: list[dict[str, Any]] = []
        last_result: Optional[MCPToolResult] = None

        # Step 2: Execute planned actions with safety verification
        for action in plan.actions:
            # Safety check: Destructive operations require explicit confirmation
            if action.requires_confirmation and not confirm_destructive:
                return AgentResponse(
                    success=False,
                    message=action.confirmation_message or f"Confirmation required to execute destructive action '{action.tool_name}'.",
                    requires_confirmation=True,
                    pending_action={
                        "tool_name": action.tool_name,
                        "arguments": action.arguments,
                        "reasoning": action.reasoning,
                    },
                )

            # Step 3: Invoke tool through MCP stdio client
            result = await self.client.call_tool(action.tool_name, action.arguments)
            last_result = result

            invocation_record = {
                "tool_name": action.tool_name,
                "arguments": action.arguments,
                "is_error": result.is_error,
                "status_code": result.status_code,
                "response": result.raw_data if result.raw_data is not None else result.content,
            }
            tool_invocations.append(invocation_record)

            # If tool invocation reported an error, halt and report actual failure
            if result.is_error:
                error_msg = f"Tool '{action.tool_name}' failed"
                if result.status_code:
                    error_msg += f" (HTTP {result.status_code})"
                if isinstance(result.raw_data, dict) and "detail" in result.raw_data:
                    error_msg += f": {result.raw_data['detail']}"
                elif result.content:
                    error_msg += f": {result.content}"

                return AgentResponse(
                    success=False,
                    message=error_msg,
                    tool_invocations=tool_invocations,
                    data=result.raw_data,
                )

        # Step 4: Construct user-facing success summary
        message = self._format_success_message(plan.actions[-1], last_result)
        return AgentResponse(
            success=True,
            message=message,
            tool_invocations=tool_invocations,
            data=last_result.raw_data if last_result else None,
        )

    def _format_success_message(self, action: PlanAction, result: Optional[MCPToolResult]) -> str:
        """Format a concise, informative success message based on executed action."""
        if not result or result.raw_data is None:
            return f"Executed {action.tool_name} successfully."

        raw = result.raw_data
        data = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw

        if action.tool_name == "list_tasks":
            count = len(data) if isinstance(data, list) else 0
            filter_info = f" with {action.arguments}" if action.arguments else ""
            return f"Found {count} tasks{filter_info}."

        if action.tool_name == "get_task_by_id":
            title = data.get("title", "") if isinstance(data, dict) else ""
            status = data.get("status", "") if isinstance(data, dict) else ""
            return f"Retrieved task {action.arguments.get('task_id')}: '{title}' (Status: {status})."

        if action.tool_name == "create_task":
            task_id = data.get("id", "") if isinstance(data, dict) else ""
            title = data.get("title", "") if isinstance(data, dict) else ""
            return f"Successfully created task {task_id}: '{title}'."

        if action.tool_name == "update_task":
            task_id = action.arguments.get("task_id", "")
            return f"Successfully updated task '{task_id}'."

        if action.tool_name == "delete_task":
            task_id = action.arguments.get("task_id", "")
            return f"Successfully deleted task '{task_id}'."

        if action.tool_name == "get_task_summary":
            total = data.get("total_tasks", 0) if isinstance(data, dict) else 0
            return f"Task summary retrieved: {total} total tasks."

        if action.tool_name == "list_projects":
            count = len(data) if isinstance(data, list) else 0
            return f"Retrieved {count} projects."

        if action.tool_name == "list_project_tasks":
            count = len(data) if isinstance(data, list) else 0
            proj = action.arguments.get("project_id", "")
            return f"Found {count} tasks for project '{proj}'."

        if action.tool_name == "get_health":
            return f"Service health: {data.get('status', 'ok')}."

        if action.tool_name == "reset_database":
            return "Demo database successfully reset to seed state."

        return f"Completed '{action.tool_name}' successfully."
