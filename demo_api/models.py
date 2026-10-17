"""Pydantic data models for the Demo Task Management API."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Lifecycle status of a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Urgency level of a task."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Task(BaseModel):
    """A task managed in the system."""

    id: str = Field(description="Unique task identifier, e.g. 't-1'")
    title: str = Field(description="Short title describing the task")
    description: Optional[str] = Field(default=None, description="Detailed description")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current task status")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM, description="Task priority")
    project_id: Optional[str] = Field(default=None, description="Associated project identifier")
    created_at: str = Field(description="ISO 8601 creation timestamp")
    updated_at: str = Field(description="ISO 8601 last update timestamp")


class Project(BaseModel):
    """A project grouping multiple tasks."""

    id: str = Field(description="Unique project identifier, e.g. 'proj-1'")
    name: str = Field(description="Project name")
    description: Optional[str] = Field(default=None, description="Project overview")
    created_at: str = Field(description="ISO 8601 creation timestamp")


class CreateTaskRequest(BaseModel):
    """Payload for creating a new task."""

    title: str = Field(min_length=1, max_length=200, description="Title of the new task")
    description: Optional[str] = Field(default=None, description="Optional detailed task description")
    priority: Optional[TaskPriority] = Field(default=TaskPriority.MEDIUM, description="Priority level")
    status: Optional[TaskStatus] = Field(default=TaskStatus.PENDING, description="Initial status")
    project_id: Optional[str] = Field(default=None, description="Optional associated project ID")


class UpdateTaskRequest(BaseModel):
    """Payload for updating an existing task."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=200, description="Updated task title")
    description: Optional[str] = Field(default=None, description="Updated description")
    priority: Optional[TaskPriority] = Field(default=None, description="Updated priority level")
    status: Optional[TaskStatus] = Field(default=None, description="Updated task status")
    project_id: Optional[str] = Field(default=None, description="Updated project ID")


class TaskSummary(BaseModel):
    """Aggregated summary statistics for tasks."""

    total_tasks: int = Field(description="Total number of tasks across all states")
    counts_by_status: dict[str, int] = Field(description="Count of tasks in each status")
    counts_by_priority: dict[str, int] = Field(description="Count of tasks in each priority level")


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str = Field(default="ok", description="Service health indicator")
    service: str = Field(default="demo-task-management-api", description="Service name")
    version: str = Field(default="1.0.0", description="API version")
    timestamp: str = Field(description="Current server timestamp")


class ErrorResponse(BaseModel):
    """Structured error payload."""

    detail: str = Field(description="Error message detailing the failure reason")
