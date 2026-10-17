"""Custom exceptions for MCP client and agent orchestration."""


class AgentError(Exception):
    """Base exception for all agent operations."""

    pass


class MCPClientError(AgentError):
    """Base exception for MCP client operations."""

    pass


class MCPConnectionError(MCPClientError):
    """Raised when client fails to connect or initialize MCP server."""

    pass


class MCPTimeoutError(MCPClientError):
    """Raised when an MCP operation times out."""

    pass


class MCPToolNotFoundError(MCPClientError):
    """Raised when requesting an undiscovered or unregistered tool."""

    pass


class MCPToolExecutionError(MCPClientError):
    """Raised when a tool execution fails at the MCP protocol level."""

    pass


class PlanningError(AgentError):
    """Raised when intent planning fails or cannot resolve tools."""

    pass


class ConfirmationRequiredError(AgentError):
    """Raised when an unconfirmed destructive action is attempted."""

    pass
