# ──────────────────────────────────────────────────────────────────────
# InMarket — single image used by BOTH services (mcp_server and web).
# docker-compose overrides the command for the MCP service; the default
# CMD below runs the Flask frontend under gunicorn.
#
# Security notes (OWASP A05 / LLM03):
#   - pinned slim base image (pin by digest for stricter supply-chain control)
#   - runs as a non-root user
#   - no secrets baked in — keys are passed at runtime via env (see compose)
# ──────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Predictable, log-friendly Python behaviour
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Non-root runtime user
RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

# Install dependencies first so this layer caches across code changes
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Application code (only what we need — no .env, .git, .venv; see .dockerignore)
COPY mcp_server/ ./mcp_server/
COPY agent/ ./agent/
COPY frontend/ ./frontend/

# Drop privileges
USER appuser

# Frontend port (the MCP service binds 8000 but is not published — see compose)
EXPOSE 5000

# Default: run the web app under gunicorn (settings in frontend/gunicorn_conf.py,
# which also logs a clickable http://localhost:5000 once the server is ready).
CMD ["gunicorn", "-c", "frontend/gunicorn_conf.py", "frontend.app:app"]
