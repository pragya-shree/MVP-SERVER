"""Health check route."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check response payload schema."""

    status: str = Field(default="ok", description="Current service health status")
    service: str = Field(default="anything-to-mcp", description="Service identifier")
    version: str = Field(default="0.1.0", description="Service semantic version")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns service availability and version metadata.",
)
async def get_health() -> HealthResponse:
    """Health check endpoint returning operational status."""
    return HealthResponse(
        status="ok",
        service="anything-to-mcp",
        version="0.1.0",
    )
