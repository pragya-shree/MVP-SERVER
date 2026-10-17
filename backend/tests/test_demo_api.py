"""Unit and integration tests for the Demo Task Management API."""

import pytest
from fastapi.testclient import TestClient

from demo_api.app import app
from demo_api.repository import repository


@pytest.fixture(autouse=True)
def reset_demo_repo():
    """Ensure every test runs against a fresh repository seed state."""
    repository.reset()
    yield
    repository.reset()


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return TestClient(app)


def test_health_check(client: TestClient) -> None:
    """Verify /health returns 200 and expected metadata."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "demo-task-management-api"
    assert data["version"] == "1.0.0"
    assert "timestamp" in data


def test_get_task_summary(client: TestClient) -> None:
    """Verify aggregated task metrics endpoint."""
    resp = client.get("/tasks/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_tasks"] == 4
    assert data["counts_by_status"]["pending"] == 2
    assert data["counts_by_status"]["in_progress"] == 1
    assert data["counts_by_status"]["completed"] == 1
    assert data["counts_by_priority"]["urgent"] == 1
    assert data["counts_by_priority"]["high"] == 1
    assert data["counts_by_priority"]["medium"] == 1
    assert data["counts_by_priority"]["low"] == 1


def test_list_tasks_unfiltered(client: TestClient) -> None:
    """Verify listing all tasks returns default seed tasks."""
    resp = client.get("/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 4
    ids = [t["id"] for t in data]
    assert ids == ["t-1", "t-2", "t-3", "t-4"]


def test_list_tasks_filtering(client: TestClient) -> None:
    """Verify filtering tasks by status, priority, and project."""
    # Filter by status
    resp = client.get("/tasks?status=pending")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(t["status"] == "pending" for t in data)

    # Filter by priority
    resp = client.get("/tasks?priority=urgent")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "t-1"

    # Filter by project
    resp = client.get("/tasks?project_id=proj-2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "t-4"


def test_list_tasks_pagination(client: TestClient) -> None:
    """Verify limit and offset pagination parameters."""
    resp = client.get("/tasks?limit=2&offset=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["id"] == "t-2"
    assert data[1]["id"] == "t-3"


def test_get_task_by_id_success(client: TestClient) -> None:
    """Verify retrieving a single task by ID."""
    resp = client.get("/tasks/t-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "t-1"
    assert data["title"] == "Prepare hackathon demo"
    assert data["status"] == "in_progress"
    assert data["priority"] == "urgent"


def test_get_task_by_id_not_found(client: TestClient) -> None:
    """Verify 404 when task ID does not exist."""
    resp = client.get("/tasks/nonexistent-99")
    assert resp.status_code == 404
    data = resp.json()
    assert "not found" in data["detail"].lower()


def test_create_task_success(client: TestClient) -> None:
    """Verify creating a new task with 201 status code and assigned ID."""
    payload = {
        "title": "Build Agent Demo",
        "description": "Construct deterministic agent planner",
        "priority": "high",
        "status": "pending",
        "project_id": "proj-1",
    }
    resp = client.post("/tasks", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "t-5"
    assert data["title"] == "Build Agent Demo"
    assert data["priority"] == "high"
    assert data["project_id"] == "proj-1"

    # Verify task is present in list
    list_resp = client.get("/tasks")
    assert len(list_resp.json()) == 5


def test_create_task_validation_error(client: TestClient) -> None:
    """Verify 422 validation error when title is missing."""
    resp = client.post("/tasks", json={"description": "No title"})
    assert resp.status_code == 422


def test_create_task_nonexistent_project(client: TestClient) -> None:
    """Verify 404 error when referencing nonexistent project_id."""
    resp = client.post("/tasks", json={"title": "Orphan Task", "project_id": "proj-invalid"})
    assert resp.status_code == 404
    assert "proj-invalid" in resp.json()["detail"]


def test_update_task_success(client: TestClient) -> None:
    """Verify updating task status and title with PATCH."""
    resp = client.patch(
        "/tasks/t-2",
        json={"status": "completed", "priority": "urgent"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "t-2"
    assert data["status"] == "completed"
    assert data["priority"] == "urgent"
    assert data["title"] == "Write API documentation"  # Unchanged field preserved


def test_update_task_not_found(client: TestClient) -> None:
    """Verify 404 when updating nonexistent task."""
    resp = client.patch("/tasks/nonexistent", json={"status": "completed"})
    assert resp.status_code == 404


def test_delete_task_success(client: TestClient) -> None:
    """Verify deleting a task returns 204 and removes task."""
    resp = client.delete("/tasks/t-3")
    assert resp.status_code == 204

    # Subsequent GET returns 404
    get_resp = client.get("/tasks/t-3")
    assert get_resp.status_code == 404

    # Total tasks decreased
    summary_resp = client.get("/tasks/summary")
    assert summary_resp.json()["total_tasks"] == 3


def test_delete_task_not_found(client: TestClient) -> None:
    """Verify 404 when deleting nonexistent task."""
    resp = client.delete("/tasks/nonexistent")
    assert resp.status_code == 404


def test_list_projects(client: TestClient) -> None:
    """Verify listing all projects."""
    resp = client.get("/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert [p["id"] for p in data] == ["proj-1", "proj-2"]


def test_list_project_tasks(client: TestClient) -> None:
    """Verify listing tasks belonging to a project."""
    resp = client.get("/projects/proj-1/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert all(t["project_id"] == "proj-1" for t in data)


def test_list_project_tasks_not_found(client: TestClient) -> None:
    """Verify 404 when querying tasks of a nonexistent project."""
    resp = client.get("/projects/nonexistent-proj/tasks")
    assert resp.status_code == 404


def test_reset_endpoint(client: TestClient) -> None:
    """Verify /reset endpoint restores database to seed state."""
    # Delete t-1
    client.delete("/tasks/t-1")
    assert client.get("/tasks/t-1").status_code == 404

    # Reset
    reset_resp = client.post("/reset")
    assert reset_resp.status_code == 200

    # t-1 restored
    assert client.get("/tasks/t-1").status_code == 200
