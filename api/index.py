"""
Vercel serverless entry point for Anything-to-MCP FastAPI backend.

CAPABILITY MATRIX — Vercel serverless runtime:

WORKS (stateless, pure-Python, or /tmp filesystem):
  GET  /health                          - Health check
  GET  /api/v1/health                   - Generator health
  POST /api/v1/specs/validate           - OpenAPI parsing & validation (no I/O)
  POST /api/v1/servers/generate         - Code generation, writes ZIP to /tmp
  GET  /api/v1/servers/{id}/tools       - Tool metadata (reads /tmp)
  GET  /api/v1/servers/{id}/download    - Streams ZIP from /tmp
  GET  /api/v1/demo/spec                - Bundled spec (file read-only)
  GET  /docs, /redoc                    - Swagger / ReDoc UI
  GET  /demo-target/*                   - In-memory demo Task API (resets on cold-start)
  GET  /api/v1/security/*               - Security policy & audit (in-memory singleton)
  POST /api/v1/security/*               - Policy updates (in-memory; reset on cold-start)
  GET  /api/v1/servers/{id}/integrations - Integration config (static, no subprocess)

DOES NOT WORK (requires spawning stdio subprocesses - Vercel blocks this):
  GET  /api/v1/agent/tools              - Needs MCP stdio subprocess
  GET  /api/v1/agent/status             - Needs MCP stdio subprocess
  POST /api/v1/agent/execute            - Needs MCP stdio subprocess
  POST /api/v1/servers/{id}/execute-tool - Needs server.py subprocess
  POST /api/v1/servers/{id}/test-connection - Needs server.py subprocess

These endpoints return HTTP 503 with a clear explanation. They are NOT
silently mocked. Use Docker / Railway / Fly.io for the full experience.

Storage note: /tmp on Vercel is ~500 MB, ephemeral per-instance.
Generated ZIPs survive within a request chain but disappear on instance recycle.
"""

import os
import re
import sys
from pathlib import Path

# Ensure repo root is on the Python path so all existing module imports work
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

# Redirect artifact storage to writable /tmp on Vercel
os.environ.setdefault("GENERATOR_STORAGE_DIR", "/tmp/anything-to-mcp/artifacts")
Path("/tmp/anything-to-mcp/artifacts").mkdir(parents=True, exist_ok=True)

# Build ALLOWED_ORIGINS: pick up the Vercel deployment URL automatically
_vercel_url = os.environ.get("VERCEL_URL", "")
_custom_domain = os.environ.get("CUSTOM_DOMAIN", "")
_configured_origins = os.environ.get("ALLOWED_ORIGINS", "")

_origins = [o.strip() for o in _configured_origins.split(",") if o.strip()]
if _vercel_url and f"https://{_vercel_url}" not in _origins:
    _origins.append(f"https://{_vercel_url}")
if _custom_domain and f"https://{_custom_domain}" not in _origins:
    _origins.append(f"https://{_custom_domain}")
# Always allow localhost for development
for _local in ("http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"):
    if _local not in _origins:
        _origins.append(_local)

os.environ["ALLOWED_ORIGINS"] = ",".join(_origins)

# Import and instantiate the existing FastAPI app
from backend.app.main import create_app  # noqa: E402

app = create_app()

# ---------------------------------------------------------------------------
# Middleware: intercept subprocess-dependent endpoints with honest 503 responses
# ---------------------------------------------------------------------------
from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

_SUBPROCESS_UNAVAILABLE_RESPONSE = {
    "error": "VERCEL_SUBPROCESS_UNAVAILABLE",
    "detail": (
        "This endpoint requires spawning a Python subprocess for MCP stdio communication. "
        "Vercel serverless functions cannot create persistent child processes. "
        "Deploy the backend on a persistent runtime (Docker, Railway, or Fly.io) "
        "to use the Agent Playground and real-time MCP tool execution."
    ),
    "docs": "https://github.com/pragya-shree/MVP-SERVER#deployment",
    "affected_features": [
        "Agent Playground (natural language -> MCP tool execution)",
        "Multi-API Workspace tool execution runner",
        "MCP server connection testing",
    ],
}

# Exact paths that require subprocesses
_SUBPROCESS_EXACT_PATHS = {
    "/api/v1/agent/tools",
    "/api/v1/agent/execute",
    "/api/v1/agent/status",
}

# Regex patterns for parameterised subprocess-dependent paths (POST only)
_SUBPROCESS_PATH_PATTERNS = [
    re.compile(r"^/api/v1/servers/[^/]+/execute-tool$"),
    re.compile(r"^/api/v1/servers/[^/]+/test-connection$"),
]


@app.middleware("http")
async def intercept_subprocess_endpoints(request: Request, call_next):
    """Return 503 for endpoints that require stdio subprocess spawning on Vercel."""
    path = request.url.path

    if path in _SUBPROCESS_EXACT_PATHS:
        return JSONResponse(status_code=503, content=_SUBPROCESS_UNAVAILABLE_RESPONSE)

    if request.method == "POST":
        for pattern in _SUBPROCESS_PATH_PATTERNS:
            if pattern.match(path):
                return JSONResponse(status_code=503, content=_SUBPROCESS_UNAVAILABLE_RESPONSE)

    return await call_next(request)

