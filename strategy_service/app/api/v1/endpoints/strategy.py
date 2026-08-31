"""Strategy management REST endpoints."""
from __future__ import annotations
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_user, require_any_role
from app.core.config import get_settings
from app.core.redis import get_redis
from app.lifecycle.manager import get_lifecycle_manager
from app.registry.registry import get_loader, get_registry
from app.sandbox.executor import SandboxExecutor
from app.schemas.strategy import (
    OkResponse, PerformanceResponse, SignalResponse,
    StartStrategyRequest, StrategyInstanceResponse, StrategyRegistrationResponse,
)
from app.sdk.types import TradingMode

settings = get_settings()
router = APIRouter(prefix="/strategies", tags=["Strategies"])
_sandbox = SandboxExecutor()


# ── Registry ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[StrategyRegistrationResponse], summary="List all registered strategies")
async def list_strategies(_user = Depends(get_current_user)) -> list[StrategyRegistrationResponse]:
    registry = get_registry()
    return [StrategyRegistrationResponse(**r.to_dict()) for r in registry.get_all()]


@router.get("/{name}", response_model=StrategyRegistrationResponse, summary="Get strategy details")
async def get_strategy(name: str, _user = Depends(get_current_user)) -> StrategyRegistrationResponse:
    reg = get_registry().get(name)
    if not reg:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found.")
    return StrategyRegistrationResponse(**reg.to_dict())


@router.post("/reload", response_model=OkResponse, summary="Reload all user strategies from disk")
async def reload_strategies(_user = Depends(require_any_role(["trader", "admin"]))) -> OkResponse:
    loader = get_loader()
    count = await loader.load_directory(settings.USER_STRATEGIES_DIR)
    return OkResponse(message=f"Reloaded {count} user strategies.")


# ── Instances ─────────────────────────────────────────────────────────────────

@router.post("/instances", response_model=StrategyInstanceResponse,
             status_code=status.HTTP_201_CREATED, summary="Start a strategy instance")
async def start_strategy(
    body: StartStrategyRequest,
    _user = Depends(require_any_role(["trader", "admin"])),
) -> StrategyInstanceResponse:
    try:
        mode = TradingMode(body.trading_mode)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid trading_mode: {body.trading_mode}")

    try:
        instance = await get_lifecycle_manager().start(
            strategy_name=body.strategy_name,
            symbol=body.symbol,
            exchange=body.exchange,
            timeframe=body.timeframe,
            params=body.params,
            trading_mode=mode,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return StrategyInstanceResponse(**instance.to_dict())


@router.get("/instances", response_model=list[StrategyInstanceResponse], summary="List running instances")
async def list_instances(_user = Depends(get_current_user)) -> list[StrategyInstanceResponse]:
    return [StrategyInstanceResponse(**i.to_dict())
            for i in get_lifecycle_manager().list_instances()]


@router.get("/instances/{instance_id}", response_model=StrategyInstanceResponse, summary="Get instance details")
async def get_instance(instance_id: str, _user = Depends(get_current_user)) -> StrategyInstanceResponse:
    instance = get_lifecycle_manager().get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found.")
    return StrategyInstanceResponse(**instance.to_dict())


@router.post("/instances/{instance_id}/stop", response_model=OkResponse, summary="Stop a strategy instance")
async def stop_instance(instance_id: str, _user = Depends(require_any_role(["trader", "admin"]))) -> OkResponse:
    ok = await get_lifecycle_manager().stop(instance_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found.")
    return OkResponse(message=f"Instance '{instance_id}' stopped.")


@router.post("/instances/{instance_id}/pause", response_model=OkResponse, summary="Pause a strategy instance")
async def pause_instance(instance_id: str, _user = Depends(require_any_role(["trader", "admin"]))) -> OkResponse:
    ok = await get_lifecycle_manager().pause(instance_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found or not running.")
    return OkResponse(message=f"Instance '{instance_id}' paused.")


@router.post("/instances/{instance_id}/resume", response_model=OkResponse, summary="Resume a paused instance")
async def resume_instance(instance_id: str, _user = Depends(require_any_role(["trader", "admin"]))) -> OkResponse:
    ok = await get_lifecycle_manager().resume(instance_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found or not paused.")
    return OkResponse(message=f"Instance '{instance_id}' resumed.")


# ── Signals ───────────────────────────────────────────────────────────────────

@router.get("/signals/latest", response_model=list[SignalResponse],
            summary="Get latest signals from Redis cache")
async def get_latest_signals(
    symbol: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    timeframe: Optional[str] = Query(None),
    _user = Depends(get_current_user),
) -> list[SignalResponse]:
    r = await get_redis()
    pattern = "signal:*"
    if strategy and symbol and timeframe:
        pattern = f"signal:{strategy}:{symbol}:{timeframe}"
    elif strategy and symbol:
        pattern = f"signal:{strategy}:{symbol}:*"

    signals = []
    async for key in r.scan_iter(pattern):
        raw = await r.get(key)
        if raw:
            data = json.loads(raw)
            signals.append(SignalResponse(**data))

    return signals


# ── Performance ───────────────────────────────────────────────────────────────

@router.get("/instances/{instance_id}/performance",
            response_model=PerformanceResponse, summary="Get instance performance stats")
async def get_performance(instance_id: str, _user = Depends(get_current_user)) -> PerformanceResponse:
    instance = get_lifecycle_manager().get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found.")
    return PerformanceResponse(
        instance_id=instance_id,
        bars_processed=instance.bars_processed,
        signals_emitted=instance.signals_emitted,
        signal_breakdown={},
        latency_stats=_sandbox.get_latency_stats(instance.registration.name),
    )
