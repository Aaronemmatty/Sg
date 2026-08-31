"""FastAPI dependency providers. Engine/redis/classifier are created once at startup in
app.main's lifespan and stored on app.state; these helpers expose them to route handlers."""
from __future__ import annotations

from fastapi import Request

from app.core.classifier import HybridClassifier
from app.core.engine import RegimeDetectionEngine
from app.services.redis_client import RegimeRedisClient


def get_engine(request: Request) -> RegimeDetectionEngine:
    return request.app.state.engine


def get_redis(request: Request) -> RegimeRedisClient:
    return request.app.state.redis_client


def get_classifier(request: Request) -> HybridClassifier:
    return request.app.state.classifier
