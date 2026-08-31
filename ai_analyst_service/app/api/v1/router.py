from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import admin, analysis, health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(analysis.router)
api_router.include_router(admin.router)
