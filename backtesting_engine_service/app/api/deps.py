from __future__ import annotations

from fastapi import Request

from app.db.repository import BacktestRepository
from app.services.job_manager import JobManager


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.job_manager


def get_repository(request: Request) -> BacktestRepository:
    return request.app.state.job_manager.repo
