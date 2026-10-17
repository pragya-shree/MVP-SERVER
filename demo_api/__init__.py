"""Demo API service for end-to-end OpenAPI and MCP validation demonstrations."""

from demo_api.app import app
from demo_api.repository import repository

__all__ = ["app", "repository"]
