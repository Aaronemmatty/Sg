"""FastAPI dependency providers, wiring app.state singletons into request handlers."""
from __future__ import annotations

from fastapi import Request

from app.core.engine import SignalAggregationEngine
from app.services.redis_client import AggregationRedisClient
from app.services.weight_store import WeightStore


def get_engine(request: Request) -> SignalAggregationEngine:
    return request.app.state.engine


def get_redis(request: Request) -> AggregationRedisClient:
    return request.app.state.redis_client


def get_weight_store(request: Request) -> WeightStore:
    return request.app.state.weight_store
