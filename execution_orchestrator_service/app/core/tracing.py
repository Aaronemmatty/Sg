"""OpenTelemetry tracing — execution orchestrator."""
from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import get_settings

settings = get_settings()

_tracer: trace.Tracer | None = None


def configure_tracing() -> None:
    global _tracer

    resource = Resource.create(
        {
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.version": settings.APP_VERSION,
            "deployment.environment": settings.APP_ENV,
        }
    )

    provider = TracerProvider(resource=resource)

    if settings.OTEL_ENDPOINT:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except ImportError:
            pass  # OTLP exporter not installed — tracing still works, no export

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(settings.OTEL_SERVICE_NAME, settings.APP_VERSION)


def get_tracer() -> trace.Tracer:
    if _tracer is None:
        return trace.get_tracer(settings.OTEL_SERVICE_NAME)
    return _tracer
