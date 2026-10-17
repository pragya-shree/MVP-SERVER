"""Data models for MCP client, planner, and agent layers."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MCPToolDefinition:
    """Normalized metadata for a dynamically discovered MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    title: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize tool definition to dictionary format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "title": self.title,
        }


@dataclass
class MCPToolResult:
    """Normalized result of an MCP tool invocation."""

    tool_name: str
    is_error: bool
    content: str
    raw_data: Optional[Any] = None
    status_code: Optional[int] = None

    @property
    def is_success(self) -> bool:
        """Return True if tool invocation completed successfully."""
        return not self.is_error


@dataclass
class PlanAction:
    """A planned tool invocation derived from user request."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None


@dataclass
class PlanResult:
    """Output of the planner containing actions or clarification requests."""

    actions: list[PlanAction] = field(default_factory=list)
    clarification_needed: Optional[str] = None
    unsupported: bool = False
    explanation: str = ""

    @property
    def has_actions(self) -> bool:
        """Return True if the plan has at least one executable action."""
        return bool(self.actions)


@dataclass
class AgentResponse:
    """Final user-facing response from the agent."""

    success: bool
    message: str
    tool_invocations: list[dict[str, Any]] = field(default_factory=list)
    data: Optional[Any] = None
    requires_confirmation: bool = False
    pending_action: Optional[dict[str, Any]] = None
    approval_id: Optional[str] = None
    requires_approval: bool = False
    policy_decision: Optional[str] = None
    execution_status: Optional[str] = None
    secrets_redacted: bool = False

