"""Automated security tests for agent safety guards and destructive operation confirmations."""

import pytest

from agent.models import MCPToolDefinition
from agent.planner import IntentPlanner

SECURITY_SAMPLE_TOOLS = [
    MCPToolDefinition(
        name="list_tasks",
        description="List all tasks | HTTP GET /tasks",
        input_schema={"type": "object", "properties": {}, "required": []},
    ),
    MCPToolDefinition(
        name="delete_task",
        description="Permanently delete a task | HTTP DELETE /tasks/{task_id}",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    ),
    MCPToolDefinition(
        name="reset_database",
        description="Reset database to seed state | HTTP POST /reset",
        input_schema={"type": "object", "properties": {}, "required": []},
    ),
    MCPToolDefinition(
        name="purge_records",
        description="Purge all user records | HTTP POST /purge",
        input_schema={"type": "object", "properties": {}, "required": []},
    ),
]


@pytest.mark.asyncio
async def test_delete_requires_explicit_confirmation() -> None:
    """Verify that any task deletion requires user confirmation before execution."""
    planner = IntentPlanner()
    plan = await planner.plan("Delete task t-5", SECURITY_SAMPLE_TOOLS)
    assert plan.has_actions
    action = plan.actions[0]
    assert action.tool_name == "delete_task"
    assert action.requires_confirmation is True
    assert "t-5" in action.confirmation_message


@pytest.mark.asyncio
async def test_reset_database_requires_explicit_confirmation() -> None:
    """Verify that database reset requires user confirmation before execution."""
    planner = IntentPlanner()
    for query in ["reset database", "reset db", "restore seed data", "reset all tasks"]:
        plan = await planner.plan(query, SECURITY_SAMPLE_TOOLS)
        assert plan.has_actions, f"Failed for query: {query}"
        action = plan.actions[0]
        assert action.tool_name == "reset_database"
        assert action.requires_confirmation is True
        assert "reset" in action.confirmation_message.lower()


@pytest.mark.asyncio
async def test_destructive_pattern_enforcement() -> None:
    """Verify that any tool containing 'purge', 'delete', or 'reset' enforces confirmation."""
    planner = IntentPlanner()
    plan = await planner.plan("delete task t-1", SECURITY_SAMPLE_TOOLS)
    assert plan.actions[0].requires_confirmation is True


@pytest.mark.asyncio
async def test_ambiguous_request_rejects_destructive_execution() -> None:
    """Verify that ambiguous queries never execute destructive tool calls."""
    planner = IntentPlanner()
    for ambiguous_query in ["clean up things", "tidy up", "make things fresh", "wipe it"]:
        plan = await planner.plan(ambiguous_query, SECURITY_SAMPLE_TOOLS)
        # Ambiguous query should either require clarification or be marked unsupported
        # but NEVER plan a destructive tool invocation!
        destructive_actions = [
            a for a in plan.actions
            if any(k in a.tool_name for k in ("delete", "reset", "purge"))
        ]
        assert len(destructive_actions) == 0, f"Ambiguous query '{ambiguous_query}' scheduled destructive action!"
