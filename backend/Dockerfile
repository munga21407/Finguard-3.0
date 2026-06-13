FROM python:3.12-slim AS base

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN pip install uv

FROM base AS dev
COPY pyproject.toml .
RUN uv sync --all-extras
COPY . .
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production
# Migrations are needed at deploy time (alembic upgrade head runs as a separate
# step), so ship them alongside src/.
COPY pyproject.toml .
RUN uv sync --no-dev
COPY src/ src/
COPY alembic/ alembic/

# Run as an unprivileged user — never root in production.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness probe for orchestrators / compose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["uv", "run", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live').status==200 else 1)"]

# --proxy-headers + --forwarded-allow-ips so the app trusts X-Forwarded-* from
# the nginx reverse proxy (correct client IP for rate limiting and audit logs).
CMD ["uv", "run", "uvicorn", "src.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "4", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
