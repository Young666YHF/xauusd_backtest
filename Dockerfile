# XAUUSD Backtest System - Multi-stage Dockerfile
# Optimized for Python 3.10+ with Numba, Optuna, FastAPI

# =============================================================================
# Stage 1: Builder (compile dependencies)
# =============================================================================
FROM python:3.10-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install wheel && \
    pip install -r requirements.txt

# =============================================================================
# Stage 2: Production Runtime
# =============================================================================
FROM python:3.10-slim-bookworm AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    APP_ENV=production \
    APP_PORT=8000

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r xauusd && useradd -r -g xauusd -s /bin/false xauusd

# Create app directories
WORKDIR /app
RUN mkdir -p /app/data /app/logs /app/results && chown -R xauusd:xauusd /app

# Copy application code
COPY --chown=xauusd:xauusd core/ ./core/
COPY --chown=xauusd:xauusd strategies/ ./strategies/
COPY --chown=xauusd:xauusd engines/ ./engines/
COPY --chown=xauusd:xauusd optimizers/ ./optimizers/
COPY --chown=xauusd:xauusd web/ ./web/
COPY --chown=xauusd:xauusd mt4/ ./mt4/
COPY --chown=xauusd:xauusd pine/ ./pine/
COPY --chown=xauusd:xauusd tests/ ./tests/
COPY --chown=xauusd:xauusd run_*.py ./
COPY --chown=xauusd:xauusd config.yaml ./
COPY --chown=xauusd:xauusd __init__.py ./

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${APP_PORT}/api/health || exit 1

USER xauusd

EXPOSE 8000

# Default: run web server
CMD ["uvicorn", "web.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# =============================================================================
# Stage 3: Development
# =============================================================================
FROM production AS development

USER root

ENV APP_ENV=development

# Install development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    vim \
    htop \
    && rm -rf /var/lib/apt/lists/*

# Install dev Python packages
RUN pip install --no-cache-dir \
    black \
    flake8 \
    pytest \
    pytest-cov \
    bandit \
    mypy

USER xauusd

# Development mode with auto-reload
CMD ["uvicorn", "web.backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# =============================================================================
# Stage 4: Backtest Runner (batch job)
# =============================================================================
FROM production AS backtest

ENV APP_ENV=production \
    NUMBA_CACHE_DIR=/app/.numba_cache

USER xauusd

# Pre-compile Numba functions on build (optional optimization)
# RUN python -c "from engines.tick_engine import TickBacktestEngine; print('Numba warmup done')"

# Default: run backtest (override CMD at runtime)
ENTRYPOINT ["python"]
CMD ["run_backtest.py", "--help"]
