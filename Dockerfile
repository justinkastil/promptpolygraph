# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage — install the package (with the [service] extra) into a venv.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Create an isolated virtualenv we can copy wholesale into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only what the build backend needs first, to keep the layer cache warm.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# Install the package plus the service extra (fastapi, uvicorn, sqlalchemy,
# apscheduler, pydantic-settings, psycopg[binary]).
RUN pip install ".[service]"

# ---------------------------------------------------------------------------
# Runtime stage — venv + app code, with PDF support on by default.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# PDF export (docx -> pdf) needs LibreOffice's `soffice` on PATH. It is
# included by default so reports render out of the box. Build a slim image
# without it via:  docker build --build-arg INCLUDE_PDF=false .
# (html / md / docx all work regardless.)
ARG INCLUDE_PDF=true

ENV PATH="/opt/venv/bin:$PATH" \
    HOME=/home/appuser \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POLYGRAPH_HOST=0.0.0.0 \
    POLYGRAPH_PORT=8080 \
    POLYGRAPH_OUT_DIR=/data/out \
    POLYGRAPH_CONFIG_DIR=/app/configs

# curl powers the HEALTHCHECK; libreoffice-writer (+ a base font) powers PDF.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && if [ "$INCLUDE_PDF" = "true" ]; then \
         apt-get install -y --no-install-recommends libreoffice-writer fonts-dejavu-core; \
       fi \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

# Bring over the prebuilt virtualenv and the application files.
COPY --from=build /opt/venv /opt/venv
COPY examples ./examples
COPY configs ./configs

# Shared artifact directory (mounted as a volume in compose / cloud).
RUN mkdir -p /data/out && chown -R appuser:appuser /app /data /home/appuser

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${POLYGRAPH_PORT}/healthz" || exit 1

# Default role is the API server. Override with `polygraph-worker` for workers.
CMD ["polygraph-server"]
