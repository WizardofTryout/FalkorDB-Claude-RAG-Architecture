# ============================================================
# FalkorDB × Claude — Multi-stage Python Image
# ============================================================
#
# Stage 1 (builder): Install Python dependencies in a venv
# Stage 2 (runtime): Minimal runtime image — no build tools
#
# No source code is BAKED into the image.
# The src/ directory is mounted at runtime via docker-compose
# volumes for hot-reload in development.
#
# Build: docker compose build
# Run:   docker compose up
# ============================================================

# ── Stage 1: Dependency Builder ────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install system build deps (only in builder stage)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for layer caching
COPY requirements.txt .

# Create a virtual environment and install deps
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ── Stage 2: Runtime Image ─────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="FalkorDB Graph RAG Service"
LABEL org.opencontainers.image.description="Sovereign Graph RAG for European Enterprise AI"
LABEL org.opencontainers.image.source="https://github.com/YOUR_ORG/FalkorDB-Claude-RAG-Architecture"
LABEL org.opencontainers.image.licenses="MIT"

# Add a non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Install only runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create src directory (will be overridden by volume mount in dev)
RUN mkdir -p /app/src && chown -R appuser:appuser /app

USER appuser

# Expose FastAPI port
EXPOSE 8000

# Health check endpoint
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default start command (overridden by docker-compose)
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
