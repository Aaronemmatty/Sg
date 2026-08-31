FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev build-essential && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY database /app/database
COPY strategy_service/pyproject.toml .
COPY strategy_service/app ./app/
RUN pip install --upgrade pip \
    && pip install /app/database \
    && pip install .

FROM python:3.12-slim AS runtime
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --no-create-home appuser
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY strategy_service/app/ ./app/
RUN mkdir -p /app/strategies && chown appuser:appgroup /app/strategies
RUN chown -R appuser:appgroup /app && chmod -R 550 /app
RUN chmod 770 /app/strategies
USER appuser
EXPOSE 8004
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8004/health')"
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8004", \
     "--workers", "1", "--loop", "uvloop", "--no-access-log"]
