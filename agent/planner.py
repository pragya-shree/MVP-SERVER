"""Intent planner converting natural language requests into validated MCP tool actions."""

from abc import ABC, abstractmethod
import json
import os
import re
from typing import Any, Optional

from agent.exceptions import PlanningError
from agent.models import MCPToolDefinition, PlanAction, PlanResult


class BasePlanner(ABC):
    """Abstract base class for agent planners."""

    @abstractmethod
    async def plan(self, request: str, tools: list[MCPToolDefinition]) -> PlanResult:
        """Analyze user request against available tools and generate an action plan."""
        pass


class IntentPlanner(BasePlanner):
    """Transparent, deterministic intent planner that parses requests and maps to tools."""

    async def plan(self, request: str, tools: list[MCPToolDefinition]) -> PlanResult:
        """Derive an executable plan or clarification from user request and discovered tools."""
        req = request.strip()
        if not req:
            return PlanResult(
                clarification_needed="Please provide a request or instruction."
            )

        tool_map = {t.name: t for t in tools}
        lower_req = req.lower()

        # 1. Health check intent
        if any(kw in lower_req for kw in ["health", "system status", "ping server", "is api running"]):
            if "get_health" in tool_map:
                action = PlanAction(
                    tool_name="get_health",
                    arguments={},
                    reasoning="Check server health status",
                )
                return self._validate_and_build_plan(action, tool_map)

        # 2. Task summary intent
        if any(kw in lower_req for kw in ["summary", "stats", "metrics", "overview", "count tasks", "task summary"]):
            if "get_task_summary" in tool_map:
                action = PlanAction(
                    tool_name="get_task_summary",
                    arguments={},
                    reasoning="Retrieve aggregated task summary and metrics",
                )
                return self._validate_and_build_plan(action, tool_map)

        # 3. Delete task intent (requires confirmation!)
        if any(kw in lower_req for kw in ["delete task", "remove task", "drop task"]):
            task_id = self._extract_task_id(req)
            if not task_id:
                return PlanResult(
                    clarification_needed="Please specify the task ID you would like to delete (e.g., 't-1')."
                )
            if "delete_task" in tool_map:
                action = PlanAction(
                    tool_name="delete_task",
                    arguments={"task_id": task_id},
                    reasoning=f"Permanently delete task '{task_id}'",
                    requires_confirmation=True,
                    confirmation_message=f"Are you sure you want to permanently delete task '{task_id}'? This action cannot be undone.",
                )
                return self._validate_and_build_plan(action, tool_map)

        # 4. Get single task by ID intent
        task_id_match = self._extract_task_id(req)
        single_task_keywords = ["find task", "get task", "show task", "lookup task", "fetch task", "view task", "detail"]
        if (task_id_match and any(kw in lower_req for kw in single_task_keywords)) or (
            task_id_match and "tasks" not in lower_req and not any(kw in lower_req for kw in ["create", "update", "delete", "remove"])
        ):
            if "get_task_by_id" in tool_map:
                action = PlanAction(
                    tool_name="get_task_by_id",
                    arguments={"task_id": task_id_match},
                    reasoning=f"Retrieve task details for '{task_id_match}'",
                )
                return self._validate_and_build_plan(action, tool_map)

        # 5. Create task intent
        if any(kw in lower_req for kw in ["create a task", "create task", "add a task", "add task", "new task"]):
            title = self._extract_create_title(req)
            if not title:
                return PlanResult(
                    clarification_needed="Please provide a title for the new task."
                )

            args: dict[str, Any] = {"title": title}

            # Optional priority
            priority = self._extract_priority(req)
            if priority:
                args["priority"] = priority

            # Optional status
            status = self._extract_status(req)
            if status:
                args["status"] = status

            # Optional project
            project_id = self._extract_project_id(req)
            if project_id:
                args["project_id"] = project_id

            # Optional description
            desc = self._extract_description(req)
            if desc:
                args["description"] = desc

            if "create_task" in tool_map:
                action = PlanAction(
                    tool_name="create_task",
                    arguments=args,
                    reasoning=f"Create a new task with title '{title}'",
                )
                return self._validate_and_build_plan(action, tool_map)

        # 6. Update task intent
        if any(kw in lower_req for kw in ["update task", "modify task", "change task", "mark task"]):
            task_id = self._extract_task_id(req)
            if not task_id:
                return PlanResult(
                    clarification_needed="Please specify the task ID you would like to update (e.g., 't-1')."
                )

            args = {"task_id": task_id}
            status = self._extract_status(req)
            priority = self._extract_priority(req)

            # Check for title changes
            title_match = re.search(r'(?:title to|rename to)\s+["\']?([^"\']+)["\']?', req, re.IGNORECASE)
            if title_match:
                args["title"] = title_match.group(1).strip()

            if status:
                args["status"] = status
            if priority:
                args["priority"] = priority

            if len(args) == 1:
                return PlanResult(
                    clarification_needed=f"Please specify what fields to update on task '{task_id}' (e.g. status, priority, or title)."
                )

            if "update_task" in tool_map:
                action = PlanAction(
                    tool_name="update_task",
                    arguments=args,
                    reasoning=f"Update task '{task_id}'",
                )
                return self._validate_and_build_plan(action, tool_map)

        # 7. Project queries
        if "project" in lower_req:
            proj_id = self._extract_project_id(req)
            if proj_id and any(kw in lower_req for kw in ["task", "tasks"]):
                if "list_project_tasks" in tool_map:
                    action = PlanAction(
                        tool_name="list_project_tasks",
                        arguments={"project_id": proj_id},
                        reasoning=f"List all tasks in project '{proj_id}'",
                    )
                    return self._validate_and_build_plan(action, tool_map)

            if any(kw in lower_req for kw in ["list projects", "show projects", "all projects", "view projects"]):
                if "list_projects" in tool_map:
                    action = PlanAction(
                        tool_name="list_projects",
                        arguments={},
                        reasoning="List all registered projects",
                    )
                    return self._validate_and_build_plan(action, tool_map)

        # 8. Database reset / state wipe
        if any(kw in lower_req for kw in ["reset db", "reset database", "restore seed data", "reset data", "reset tasks", "reset all tasks", "wipe tasks", "reset app", "clear database", "wipe database"]):
            if "reset_database" in tool_map:
                action = PlanAction(
                    tool_name="reset_database",
                    arguments={},
                    reasoning="Reset database to initial sample data",
                    requires_confirmation=True,
                    confirmation_message="Are you sure you want to reset the database? All custom tasks will be replaced with seed data.",
                )
                return self._validate_and_build_plan(action, tool_map)

        # 9. List tasks with filters
        if any(kw in lower_req for kw in ["task", "tasks", "show me", "list", "find all"]):
            args = {}
            status = self._extract_status(req)
            priority = self._extract_priority(req)
            project_id = self._extract_project_id(req)

            if status:
                args["status"] = status
            if priority:
                args["priority"] = priority
            if project_id:
                args["project_id"] = project_id

            limit_match = re.search(r'(?:limit|top|first)\s+(\d+)', lower_req)
            if limit_match:
                args["limit"] = int(limit_match.group(1))

            if "list_tasks" in tool_map:
                filter_desc = ", ".join(f"{k}={v}" for k, v in args.items()) if args else "all"
                action = PlanAction(
                    tool_name="list_tasks",
                    arguments=args,
                    reasoning=f"List tasks with filters: {filter_desc}",
                )
                return self._validate_and_build_plan(action, tool_map)

        # 10. Unsupported / unknown query
        available = ", ".join(t.name for t in tools[:6])
        if len(tools) > 6:
            available += f", and {len(tools) - 6} more"
        return PlanResult(
            unsupported=True,
            explanation=f"I could not map your request '{request}' to any available tool. Discovered tools include: {available}.",
        )

    def _validate_and_build_plan(
        self, action: PlanAction, tool_map: dict[str, MCPToolDefinition]
    ) -> PlanResult:
        """Validate action against tool input schema and construct PlanResult."""
        tool_def = tool_map.get(action.tool_name)
        if not tool_def:
            return PlanResult(
                unsupported=True,
                explanation=f"Required tool '{action.tool_name}' was not discovered on the MCP server.",
            )

        # Security hardening: ANY delete, reset, or destructive operation requires confirmation
        if any(kw in action.tool_name.lower() for kw in ("delete", "reset", "purge", "destroy", "drop")):
            action.requires_confirmation = True
            if not action.confirmation_message:
                action.confirmation_message = (
                    f"Are you sure you want to execute '{action.tool_name}' with {action.arguments}? "
                    "This is a destructive action that cannot be undone."
                )

        schema = tool_def.input_schema or {}
        required = schema.get("required", [])

        # Check for missing required arguments
        for req_prop in required:
            if req_prop not in action.arguments or action.arguments[req_prop] in (None, ""):
                return PlanResult(
                    clarification_needed=f"Missing required parameter '{req_prop}' for tool '{action.tool_name}'."
                )

        return PlanResult(
            actions=[action],
            explanation=f"Selected tool '{action.tool_name}' to {action.reasoning.lower()}.",
        )

    def _extract_task_id(self, text: str) -> Optional[str]:
        """Extract task identifier like 't-1', 't-2'."""
        match = re.search(r'\b(t-\d+)\b', text, re.IGNORECASE)
        if match:
            return match.group(1).lower()

        # Fallback: "task 1" -> "t-1"
        match = re.search(r'\btask\s+(\d+)\b', text, re.IGNORECASE)
        if match:
            return f"t-{match.group(1)}"

        # Explicit "task id <val>" or "task <id>"
        match = re.search(r'\btask\s+(?:id\s+)?([a-zA-Z0-9_\-]+)\b', text, re.IGNORECASE)
        if match and match.group(1).lower() not in {"all", "summary", "list", "new"}:
            return match.group(1).lower()

        return None

    def _extract_project_id(self, text: str) -> Optional[str]:
        """Extract project identifier like 'proj-1', 'proj-2'."""
        match = re.search(r'\b(proj-\d+)\b', text, re.IGNORECASE)
        if match:
            return match.group(1).lower()

        # Fallback: "project 1" -> "proj-1"
        match = re.search(r'\bproject\s+(\d+)\b', text, re.IGNORECASE)
        if match:
            return f"proj-{match.group(1)}"

        return None

    def _extract_status(self, text: str) -> Optional[str]:
        """Extract task status from query."""
        lower = text.lower()
        if "in progress" in lower or "in_progress" in lower:
            return "in_progress"
        if "completed" in lower or " done" in lower or "finished" in lower:
            return "completed"
        if "cancelled" in lower or "canceled" in lower:
            return "cancelled"
        if "pending" in lower or "todo" in lower or "to do" in lower:
            return "pending"
        return None

    def _extract_priority(self, text: str) -> Optional[str]:
        """Extract priority level from query."""
        lower = text.lower()
        for p in ["urgent", "high", "medium", "low"]:
            if re.search(rf'\b{p}\b', lower):
                return p
        return None

    def _extract_create_title(self, text: str) -> Optional[str]:
        """Extract title for a new task creation."""
        # 1. "called <title>" or "named <title>"
        match = re.search(r'(?:called|named)\s+["\']?([^"\',]+?)["\']?(?:\s+(?:with|in|priority|status)|$)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # 2. Quoted string: 'create task "Prepare demo"'
        match = re.search(r'["\']([^"\']+)["\']', text)
        if match:
            return match.group(1).strip()

        # 3. "create task <title> with..."
        match = re.search(r'create(?:\s+a)?\s+task\s+(.+?)(?:\s+(?:with|in|priority|status)|$)', text, re.IGNORECASE)
        if match:
            cand = match.group(1).strip()
            if cand and cand.lower() not in {"called", "named"}:
                return cand

        # 4. "add task <title>..."
        match = re.search(r'add(?:\s+a)?\s+task\s+(.+?)(?:\s+(?:with|in|priority|status)|$)', text, re.IGNORECASE)
        if match:
            cand = match.group(1).strip()
            if cand:
                return cand

        return None

    def _extract_description(self, text: str) -> Optional[str]:
        """Extract optional task description."""
        match = re.search(r'(?:description|described as)\s+["\']?([^"\']+)["\']?', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None


def create_default_planner() -> BasePlanner:
    """Factory creating the default planner implementation."""
    return IntentPlanner()
