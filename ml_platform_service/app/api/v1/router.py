from fastapi import APIRouter

from app.api.v1.endpoints import (
    experiments,
    health,
    monitoring,
    predictions,
    registry,
    training,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(training.router)
api_router.include_router(registry.router)
api_router.include_router(predictions.router)
api_router.include_router(experiments.router)
api_router.include_router(monitoring.router)
