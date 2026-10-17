import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.health import router as health_router
from backend.app.api.v1.agent import router as agent_router
from backend.app.api.v1.router import router as v1_router
from demo_api.app import app as demo_fastapi_app


def create_app() -> FastAPI:
    """Create and configure an instance of the FastAPI application."""
    application = FastAPI(
        title="Anything-to-MCP API",
        description="Production-minded OpenAPI-to-MCP generator service",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Configure CORS for frontend access
    allowed_origins_env = os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
    )
    allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]

    frontend_url = os.environ.get("FRONTEND_URL", "").strip()
    if frontend_url and frontend_url not in allowed_origins:
        allowed_origins.append(frontend_url)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=r"^https://.*\.vercel\.app$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Core health & generator routers
    application.include_router(health_router)
    application.include_router(v1_router)
    application.include_router(agent_router)

    # Mount demo target API so MCP server tools can execute against local endpoints
    application.mount("/demo-target", demo_fastapi_app)

    # Mount prebuilt frontend static files if available
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[2]
    frontend_dist = repo_root / "frontend" / "dist"
    if frontend_dist.exists() and (frontend_dist / "index.html").exists():
        from fastapi.staticfiles import StaticFiles
        application.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, reload=True)
