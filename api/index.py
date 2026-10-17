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
_frontend_url = os.environ.get("FRONTEND_URL", "")
_configured_origins = os.environ.get("ALLOWED_ORIGINS", "")

_origins = [o.strip() for o in _configured_origins.split(",") if o.strip()]
if _vercel_url and f"https://{_vercel_url}" not in _origins:
    _origins.append(f"https://{_vercel_url}")
if _custom_domain and f"https://{_custom_domain}" not in _origins:
    _origins.append(f"https://{_custom_domain}")
if _frontend_url and _frontend_url not in _origins:
    _origins.append(_frontend_url)
# Always allow localhost for development
for _local in ("http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://127.0.0.1:3000"):
    if _local not in _origins:
        _origins.append(_local)

os.environ["ALLOWED_ORIGINS"] = ",".join(_origins)

# Configure DEMO_API_BASE_URL for Vercel if not already explicitly set
if "DEMO_API_BASE_URL" not in os.environ and _vercel_url:
    os.environ["DEMO_API_BASE_URL"] = f"https://{_vercel_url}/demo-target"

# Import and instantiate the existing FastAPI app
from backend.app.main import create_app  # noqa: E402

app = create_app()


