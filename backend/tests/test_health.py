"""Tests for FastAPI initialization and health endpoint."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from backend.app.api.routes.health import HealthResponse
from backend.app.main import app, create_app


def test_app_initialization() -> None:
    """Verify application initializes cleanly with expected metadata."""
    instance = create_app()
    assert isinstance(instance, FastAPI)
    assert instance.title == "Anything-to-MCP API"
    assert instance.version == "0.1.0"

    openapi_schema = instance.openapi()
    assert "/health" in openapi_schema["paths"]


def test_health_endpoint_sync() -> None:
    """Verify GET /health returns HTTP 200 and expected payload using TestClient."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "anything-to-mcp"
    assert "version" in data


def test_health_response_structure_validation() -> None:
    """Validate that GET /health response parses strictly into HealthResponse schema."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200

    # Parse and validate with Pydantic model
    health_obj = HealthResponse.model_validate(response.json())
    assert health_obj.status == "ok"
    assert health_obj.service == "anything-to-mcp"
    assert health_obj.version == "0.1.0"


@pytest.mark.asyncio
async def test_health_endpoint_async() -> None:
    """Verify GET /health works asynchronously with AsyncClient."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "anything-to-mcp"
