# ============================================================
# StockSignalAnalyzer — Multi-stage Dockerfile
# Base: python:3.12-slim-bookworm (minimal attack surface)
# User: nonroot (never runs as root in production)
# Reference: docs/23_SECURITY_BASELINE.md (Section 8)
# ============================================================

# -----------------------------------------------------------
# Stage 1: builder — install dependencies with Poetry
# -----------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.4 \
    POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

# Install Poetry
RUN pip install "poetry==$POETRY_VERSION"

WORKDIR /app

# Copy dependency manifests first (cache layer)
COPY pyproject.toml ./

# Install runtime dependencies only (no dev tools in production image)
RUN /opt/poetry/bin/poetry install --only main --no-root

# -----------------------------------------------------------
# Stage 2: runtime — lean production image
# -----------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH"

# Create non-root user — never run as root in production
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy virtualenv from builder stage
COPY --from=builder /app/.venv .venv

# Copy application source
COPY src/ ./src/
COPY config/ ./config/

# Ownership — appuser owns everything
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"

CMD ["python", "src/main.py"]
