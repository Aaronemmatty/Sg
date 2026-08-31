FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev build-essential && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY database /app/database
COPY sg_security /app/sg_security
COPY market_data_service/pyproject.toml .
COPY market_data_service/app ./app/
RUN pip install --upgrade pip \
    && pip install /app/database /app/sg_security \
    && pip install .

FROM python:3.12-slim AS runtime
RUN groupadd --gid 1001 appgroup && useradd --uid 1001 --gid appgroup --no-create-home appuser
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY market_data_service/app/ ./app/
RUN chown -R appuser:appgroup /app && chmod -R 550 /app
USER appuser
EXPOSE 8002
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/ready')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1", "--loop", "uvloop", "--no-access-log"]
