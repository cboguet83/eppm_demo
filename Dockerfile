# ==============================================================================
# Multi-stage Dockerfile for PPM Studio Pro (Enterprise-grade, non-root, slim)
# ==============================================================================

# Stage 1: Build Dependencies
FROM python:3.14-slim-trixie AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Prepare the canonical browser assets once, without a Node runtime/compiler.
COPY scripts/__init__.py scripts/build_planning_assets.py ./scripts/
COPY LICENSE ./LICENSE
COPY packages/planning-view/ ./packages/planning-view/
COPY packages/streamlit-planning-view/pyproject.toml ./packages/streamlit-planning-view/pyproject.toml
RUN python -m scripts.build_planning_assets --target eppm

# Stage 2: Runtime Image
FROM python:3.14-slim-trixie AS runtime

# Native archives require clients matching the PostgreSQL 18 server generation.
# Official signed repository: https://www.postgresql.org/download/linux/debian/
ARG POSTGRES_CLIENT_VERSION=18.6-*
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl --fail --silent --show-error \
       https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo 'deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main' \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends \
       "postgresql-client-18=${POSTGRES_CLIENT_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

# Set security and performance environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    DATABASE_BACKUP_DIRECTORY=/app/data/backups/postgresql

WORKDIR /app

# Create non-root user and persistent data directory
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app

# Copy installed Python packages from builder stage
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

# Copy application source code and scripts
COPY --chown=appuser:appuser streamlit_app.py asgi_app.py .
COPY --chown=appuser:appuser app/ ./app/
COPY --from=builder --chown=appuser:appuser /build/app/presentation/assets/components/gantt/planning-view/ ./app/presentation/assets/components/gantt/planning-view/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser .streamlit/ ./.streamlit/

USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

ENTRYPOINT ["python", "-m", "scripts.run_app"]
