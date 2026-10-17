# ==========================================
# Stage 1: Build the React + Vite Frontend
# ==========================================
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ==========================================
# Stage 2: Production Python Backend Service
# ==========================================
FROM python:3.12-slim AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    GENERATOR_STORAGE_DIR=/app/storage/artifacts \
    DEMO_API_BASE_URL=http://127.0.0.1:8000/demo-target

WORKDIR /app

# Install system utilities needed for runtime and health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject and install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy backend source code, demo API, scripts, examples
COPY backend/ ./backend/
COPY demo_api/ ./demo_api/
COPY agent/ ./agent/
COPY examples/ ./examples/
COPY storage/ ./storage/

# Copy built frontend assets from builder stage
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Ensure storage directory exists and is writable
RUN mkdir -p /app/storage/artifacts

EXPOSE 8000

# Docker Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
