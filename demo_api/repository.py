"""Thread-safe in-memory repository with deterministic seed data for Demo Task API."""

from copy import deepcopy
from datetime import datetime, timezone
import threading
from typing import Optional

from demo_api.models import (
    CreateTaskRequest,
    Project,
    Task,
    TaskPriority,
    TaskStatus,
    TaskSummary,
    UpdateTaskRequest,
)

INITIAL_PROJECTS = [
    Project(
        id="proj-1",
        name="Website Redesign",
        description="Overhaul public landing page and documentation portal",
        created_at="2026-01-10T09:00:00Z",
    ),
    Project(
        id="proj-2",
        name="Mobile App",
        description="Cross-platform mobile client for iOS and Android",
        created_at="2026-01-15T10:30:00Z",
    ),
]

INITIAL_TASKS = [
    Task(
        id="t-1",
        title="Prepare hackathon demo",
        description="Build complete end-to-end OpenAPI to MCP agent demonstration",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.URGENT,
        project_id="proj-1",
        created_at="2026-02-01T08:00:00Z",
        updated_at="2026-02-01T08:00:00Z",
    ),
    Task(
        id="t-2",
        title="Write API documentation",
        description="Document OpenAPI endpoints, authentication, and schemas",
        status=TaskStatus.PENDING,
        priority=TaskPriority.HIGH,
        project_id="proj-1",
        created_at="2026-02-01T08:30:00Z",
        updated_at="2026-02-01T08:30:00Z",
    ),
    Task(
        id="t-3",
        title="Fix navigation bar bug",
        description="Responsive menu collapses prematurely on tablet viewports",
        status=TaskStatus.PENDING,
        priority=TaskPriority.MEDIUM,
        project_id="proj-1",
        created_at="2026-02-01T09:00:00Z",
        updated_at="2026-02-01T09:00:00Z",
    ),
    Task(
        id="t-4",
        title="Set up CI/CD pipeline",
        description="GitHub actions workflow for linting, security scanning, and automated tests",
        status=TaskStatus.COMPLETED,
        priority=TaskPriority.LOW,
        project_id="proj-2",
        created_at="2026-02-01T09:30:00Z",
        updated_at="2026-02-01T09:30:00Z",
    ),
]


class InMemoryTaskRepository:
    """In-memory data store for tasks and projects."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}
        self._projects: dict[str, Project] = {}
        self._next_id: int = 5
        self.reset()

    def reset(self) -> None:
        """Reset repository state to deterministic initial seed data."""
        with self._lock:
            self._projects = {p.id: deepcopy(p) for p in INITIAL_PROJECTS}
            self._tasks = {t.id: deepcopy(t) for t in INITIAL_TASKS}
            self._next_id = 5

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        priority: Optional[TaskPriority] = None,
        project_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks with optional filtering and pagination."""
        with self._lock:
            tasks = list(self._tasks.values())

            if status is not None:
                tasks = [t for t in tasks if t.status == status]
            if priority is not None:
                tasks = [t for t in tasks if t.priority == priority]
            if project_id is not None:
                tasks = [t for t in tasks if t.project_id == project_id]

            # Deterministic sorting by ID
            tasks.sort(key=lambda t: t.id)
            return [deepcopy(t) for t in tasks[offset : offset + limit]]

    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve task by unique identifier."""
        with self._lock:
            task = self._tasks.get(task_id)
            return deepcopy(task) if task else None

    def create_task(self, req: CreateTaskRequest) -> Task:
        """Create a new task with auto-assigned ID."""
        with self._lock:
            task_id = f"t-{self._next_id}"
            self._next_id += 1
            now = datetime.now(timezone.utc).isoformat()

            task = Task(
                id=task_id,
                title=req.title,
                description=req.description,
                status=req.status or TaskStatus.PENDING,
                priority=req.priority or TaskPriority.MEDIUM,
                project_id=req.project_id,
                created_at=now,
                updated_at=now,
            )
            self._tasks[task_id] = task
            return deepcopy(task)

    def update_task(self, task_id: str, req: UpdateTaskRequest) -> Optional[Task]:
        """Update fields of an existing task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            now = datetime.now(timezone.utc).isoformat()
            data = task.model_dump()
            updates = req.model_dump(exclude_unset=True)

            for key, val in updates.items():
                if val is not None:
                    data[key] = val
            data["updated_at"] = now

            updated_task = Task(**data)
            self._tasks[task_id] = updated_task
            return deepcopy(updated_task)

    def delete_task(self, task_id: str) -> bool:
        """Delete task by ID. Returns True if found and deleted, False otherwise."""
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False

    def get_summary(self) -> TaskSummary:
        """Compute summary metrics over all tasks."""
        with self._lock:
            tasks = list(self._tasks.values())
            counts_by_status = {s.value: 0 for s in TaskStatus}
            counts_by_priority = {p.value: 0 for p in TaskPriority}

            for t in tasks:
                counts_by_status[t.status.value] = counts_by_status.get(t.status.value, 0) + 1
                counts_by_priority[t.priority.value] = counts_by_priority.get(t.priority.value, 0) + 1

            return TaskSummary(
                total_tasks=len(tasks),
                counts_by_status=counts_by_status,
                counts_by_priority=counts_by_priority,
            )

    def list_projects(self) -> list[Project]:
        """List all registered projects."""
        with self._lock:
            projects = list(self._projects.values())
            projects.sort(key=lambda p: p.id)
            return [deepcopy(p) for p in projects]

    def get_project(self, project_id: str) -> Optional[Project]:
        """Retrieve project by ID."""
        with self._lock:
            p = self._projects.get(project_id)
            return deepcopy(p) if p else None

    def list_project_tasks(self, project_id: str) -> Optional[list[Task]]:
        """List tasks belonging to a specific project. Returns None if project does not exist."""
        with self._lock:
            if project_id not in self._projects:
                return None
            tasks = [t for t in self._tasks.values() if t.project_id == project_id]
            tasks.sort(key=lambda t: t.id)
            return [deepcopy(t) for t in tasks]


# Global singleton repository instance
repository = InMemoryTaskRepository()
