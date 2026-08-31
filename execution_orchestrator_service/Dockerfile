FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY execution_orchestrator_service/pyproject.toml .
COPY execution_orchestrator_service/app ./app/
RUN pip install --upgrade pip && pip install .

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home appuser
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY execution_orchestrator_service/app/ ./app/
COPY execution_orchestrator_service/alembic/ ./alembic/
COPY execution_orchestrator_service/alembic.ini .
RUN chown -R appuser:appgroup /app && chmod -R 550 /app
USER appuser
EXPOSE 8006
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8006/ready')"
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8006 --workers 1 --loop uvloop --no-access-log"]
