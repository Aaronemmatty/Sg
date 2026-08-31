FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY database /app/database
COPY signal_aggregation_service/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install /app/database \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime

LABEL service="signal_aggregation_service" \
      platform="sg-trading-platform"

RUN groupadd --gid 1001 sgapp \
    && useradd --uid 1001 --gid sgapp --shell /usr/sbin/nologin --create-home sgapp

WORKDIR /app

COPY --from=builder /install /usr/local
COPY signal_aggregation_service/app ./app
COPY signal_aggregation_service/alembic.ini ./alembic.ini
COPY signal_aggregation_service/app/db/migrations ./app/db/migrations

RUN chown -R sgapp:sgapp /app

USER sgapp

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

EXPOSE 8013

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://localhost:8013/health', timeout=3).status==200 else sys.exit(1)"

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8013"]
