"""Unit tests for the agent IntentPlanner."""

import pytest

from agent.models import MCPToolDefinition
from agent.planner import IntentPlanner

SAMPLE_TOOLS = [
    MCPToolDefinition(
        name="get_health",
        description="Health check endpoint | HTTP GET /health",
        input_schema={"type": "object", "properties": {}, "required": []},
    ),
    MCPToolDefinition(
        name="get_task_summary",
        description="Get aggregated task metrics | HTTP GET /tasks/summary",
        input_schema={"type": "object", "properties": {}, "required": []},
    ),
    MCPToolDefinition(
        name="list_tasks",
        description="List all tasks | HTTP GET /tasks",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "priority": {"type": "string"},
                "project_id": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
            "required": [],
        },
    ),
    MCPToolDefinition(
        name="get_task_by_id",
        description="Get task by identifier | HTTP GET /tasks/{task_id}",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    ),
    MCPToolDefinition(
        name="create_task",
        description="Create a new task | HTTP POST /tasks",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "string"},
                "status": {"type": "string"},
                "project_id": {"type": "string"},
            },
            "required": ["title"],
        },
    ),
    MCPToolDefinition(
        name="update_task",
        description="Update an existing task | HTTP PATCH /tasks/{task_id}",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "title": {"type": "string"},
                "status": {"type": "string"},
                "priority": {"type": "string"},
            },
            "required": ["task_id"],
        },
    ),
    MCPToolDefinition(
        name="delete_task",
        description="Delete a task | HTTP DELETE /tasks/{task_id}",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    ),
    MCPToolDefinition(
        name="list_projects",
        description="List all projects | HTTP GET /projects",
        input_schema={"type": "object", "properties": {}, "required": []},
    ),
    MCPToolDefinition(
        name="list_project_tasks",
        description="List tasks for a project | HTTP GET /projects/{project_id}/tasks",
        input_schema={
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
    ),
    MCPToolDefinition(
        name="reset_database",
        description="Reset database to seed state | HTTP POST /reset",
        input_schema={"type": "object", "properties": {}, "required": []},
    ),
]


@pytest.mark.asyncio
async def test_plan_list_pending_tasks() -> None:
    """Verify mapping 'Show me all pending tasks' to list_tasks."""
    planner = IntentPlanner()
    plan = await planner.plan("Show me all pending tasks", SAMPLE_TOOLS)
    assert plan.has_actions
    assert not plan.unsupported
    assert plan.clarification_needed is None

    action = plan.actions[0]
    assert action.tool_name == "list_tasks"
    assert action.arguments == {"status": "pending"}
    assert not action.requires_confirmation


@pytest.mark.asyncio
async def test_plan_find_single_task() -> None:
    """Verify mapping 'Find task t-2' to get_task_by_id."""
    planner = IntentPlanner()
    plan = await planner.plan("Find task t-2", SAMPLE_TOOLS)
    assert plan.has_actions
    action = plan.actions[0]
    assert action.tool_name == "get_task_by_id"
    assert action.arguments == {"task_id": "t-2"}
    assert not action.requires_confirmation


@pytest.mark.asyncio
async def test_plan_show_task_summary() -> None:
    """Verify mapping 'Show the task summary' to get_task_summary."""
    planner = IntentPlanner()
    plan = await planner.plan("Show the task summary", SAMPLE_TOOLS)
    assert plan.has_actions
    action = plan.actions[0]
    assert action.tool_name == "get_task_summary"
    assert action.arguments == {}


@pytest.mark.asyncio
async def test_plan_create_task_with_priority() -> None:
    """Verify mapping task creation with title and priority."""
    planner = IntentPlanner()
    plan = await planner.plan(
        "Create a task called Prepare hackathon demo with priority urgent",
        SAMPLE_TOOLS,
    )
    assert plan.has_actions
    action = plan.actions[0]
    assert action.tool_name == "create_task"
    assert action.arguments["title"] == "Prepare hackathon demo"
    assert action.arguments["priority"] == "urgent"


@pytest.mark.asyncio
async def test_plan_delete_task_requires_confirmation() -> None:
    """Verify delete_task action is flagged with requires_confirmation=True."""
    planner = IntentPlanner()
    plan = await planner.plan("Delete task t-3", SAMPLE_TOOLS)
    assert plan.has_actions
    action = plan.actions[0]
    assert action.tool_name == "delete_task"
    assert action.arguments == {"task_id": "t-3"}
    assert action.requires_confirmation is True
    assert "t-3" in action.confirmation_message


@pytest.mark.asyncio
async def test_plan_update_task() -> None:
    """Verify mapping update task request."""
    planner = IntentPlanner()
    plan = await planner.plan("Update task t-1 status to completed", SAMPLE_TOOLS)
    assert plan.has_actions
    action = plan.actions[0]
    assert action.tool_name == "update_task"
    assert action.arguments["task_id"] == "t-1"
    assert action.arguments["status"] == "completed"


@pytest.mark.asyncio
async def test_plan_create_task_missing_title_clarification() -> None:
    """Verify asking for clarification when create task has no title."""
    planner = IntentPlanner()
    plan = await planner.plan("Create a task", SAMPLE_TOOLS)
    assert not plan.has_actions
    assert plan.clarification_needed is not None
    assert "title" in plan.clarification_needed.lower()


@pytest.mark.asyncio
async def test_plan_delete_task_missing_id_clarification() -> None:
    """Verify asking for clarification when delete task has no ID."""
    planner = IntentPlanner()
    plan = await planner.plan("Delete task", SAMPLE_TOOLS)
    assert not plan.has_actions
    assert plan.clarification_needed is not None
    assert "id" in plan.clarification_needed.lower()


@pytest.mark.asyncio
async def test_plan_unsupported_request() -> None:
    """Verify unknown or unsupported user queries are rejected cleanly."""
    planner = IntentPlanner()
    plan = await planner.plan("Book a flight to Paris tomorrow", SAMPLE_TOOLS)
    assert not plan.has_actions
    assert plan.unsupported is True
    assert "could not map" in plan.explanation.lower()
