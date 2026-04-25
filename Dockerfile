# syntax=docker/dockerfile:1.6

# -----------------------------------------------------------------------------
# Builder stage
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# System deps for building wheels (none currently, but kept for future C deps)
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip && \
    pip wheel --no-deps --wheel-dir=/wheels . && \
    pip wheel --wheel-dir=/wheels .

# -----------------------------------------------------------------------------
# Runtime stage
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Non-root user
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels jira-mcp-server && \
    rm -rf /wheels

# Drop privileges
USER app

# Default to HTTP for container deployments. Local stdio runs are typically
# done outside the container (the IDE assistant spawns the process directly).
ENV MCP_TRANSPORT=http \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PORT=8765

EXPOSE 8765

# Lightweight liveness probe: hit the MCP endpoint and accept any response
# under 500. The endpoint speaks JSON-RPC, so a bare GET returns a 4xx,
# which is enough proof that the server is listening.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request as u, sys; \
sys.exit(0 if u.urlopen('http://127.0.0.1:8765/mcp', timeout=3).status < 500 else 1)" \
  || exit 1

ENTRYPOINT ["python", "-m", "jira_mcp"]
