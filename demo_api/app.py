"""FastAPI application for the Demo Task Management API."""

from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Path, Query, status

from demo_api.models import (
    CreateTaskRequest,
    ErrorResponse,
    HealthResponse,
    Project,
    Task,
    TaskPriority,
    TaskStatus,
    TaskSummary,
    UpdateTaskRequest,
)
from demo_api.repository import repository

app = FastAPI(
    title="Demo Task Management API",
    description="Deterministic Task and Project Management API for OpenAPI-to-MCP generation and agent testing.",
    version="1.0.0",
)


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check endpoint",
    operation_id="get_health",
    tags=["system"],
)
def get_health() -> HealthResponse:
    """Return service health status and timestamp."""
    return HealthResponse(
        status="ok",
        service="demo-task-management-api",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get(
    "/tasks/summary",
    response_model=TaskSummary,
    summary="Get aggregated task metrics",
    description="Retrieve task counts grouped by status and priority.",
    operation_id="get_task_summary",
    tags=["tasks"],
)
def get_task_summary() -> TaskSummary:
    """Retrieve high-level summary statistics of all tasks."""
    return repository.get_summary()


@app.get(
    "/tasks",
    response_model=list[Task],
    summary="List all tasks",
    description="Retrieve a paginated list of tasks with optional filtering by status, priority, or project.",
    operation_id="list_tasks",
    tags=["tasks"],
)
def list_tasks(
    status: Optional[TaskStatus] = Query(default=None, description="Filter tasks by status (pending, in_progress, completed, cancelled)"),
    priority: Optional[TaskPriority] = Query(default=None, description="Filter tasks by priority (low, medium, high, urgent)"),
    project_id: Optional[str] = Query(default=None, description="Filter tasks by associated project ID"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum number of items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
) -> list[Task]:
    """Retrieve tasks according to filters and pagination parameters."""
    return repository.list_tasks(
        status=status,
        priority=priority,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/tasks/{task_id}",
    response_model=Task,
    responses={404: {"model": ErrorResponse, "description": "Task not found"}},
    summary="Get task by identifier",
    description="Retrieve details of a single task by its unique ID (e.g., 't-1').",
    operation_id="get_task_by_id",
    tags=["tasks"],
)
def get_task_by_id(
    task_id: str = Path(..., description="Unique ID of the task to retrieve, e.g. 't-1'"),
) -> Task:
    """Fetch task details by ID."""
    task = repository.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )
    return task


@app.post(
    "/tasks",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorResponse, "description": "Validation error"}},
    summary="Create a new task",
    description="Create a new task with specified title, description, priority, and optional project ID.",
    operation_id="create_task",
    tags=["tasks"],
)
def create_task(req: CreateTaskRequest) -> Task:
    """Create a new task."""
    if req.project_id:
        proj = repository.get_project(req.project_id)
        if not proj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project '{req.project_id}' not found",
            )
    return repository.create_task(req)


@app.patch(
    "/tasks/{task_id}",
    response_model=Task,
    responses={404: {"model": ErrorResponse, "description": "Task not found"}},
    summary="Update an existing task",
    description="Update fields of an existing task by ID (title, status, priority, description).",
    operation_id="update_task",
    tags=["tasks"],
)
def update_task(
    task_id: str = Path(..., description="Unique ID of the task to update"),
    req: UpdateTaskRequest = ...,
) -> Task:
    """Update fields of an existing task."""
    if req.project_id:
        proj = repository.get_project(req.project_id)
        if not proj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project '{req.project_id}' not found",
            )

    updated = repository.update_task(task_id, req)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )
    return updated


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse, "description": "Task not found"}},
    summary="Delete a task",
    description="Permanently delete a task by ID.",
    operation_id="delete_task",
    tags=["tasks"],
)
def delete_task(
    task_id: str = Path(..., description="Unique ID of the task to delete"),
) -> None:
    """Delete a task."""
    deleted = repository.delete_task(task_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )
    return None


@app.get(
    "/projects",
    response_model=list[Project],
    summary="List all projects",
    description="Retrieve all available projects.",
    operation_id="list_projects",
    tags=["projects"],
)
def list_projects() -> list[Project]:
    """Retrieve all projects."""
    return repository.list_projects()


@app.get(
    "/projects/{project_id}/tasks",
    response_model=list[Task],
    responses={404: {"model": ErrorResponse, "description": "Project not found"}},
    summary="List tasks for a project",
    description="Retrieve all tasks assigned to a specific project ID.",
    operation_id="list_project_tasks",
    tags=["projects"],
)
def list_project_tasks(
    project_id: str = Path(..., description="Unique identifier of the project"),
) -> list[Task]:
    """List tasks belonging to a specific project."""
    tasks = repository.list_project_tasks(project_id)
    if tasks is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    return tasks


@app.post(
    "/reset",
    summary="Reset database to seed state",
    description="Reset in-memory data store to deterministic initial sample tasks and projects.",
    operation_id="reset_database",
    tags=["system"],
)
def reset_database() -> dict[str, str]:
    """Reset repository state to initial deterministic sample data."""
    repository.reset()
    return {"status": "reset", "message": "Demo database successfully reset to seed state"}
