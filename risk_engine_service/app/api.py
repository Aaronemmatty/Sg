from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.auth import CurrentUser, get_current_user, require_role
from app.kill_switch import KillSwitchState

router = APIRouter()


# ---------------------------------------------------------------------------
# Dashboard / read APIs
# ---------------------------------------------------------------------------


@router.get("/risk/decisions")
async def list_decisions(
    request: Request,
    symbol: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=500),
):
    db = request.app.state.db
    rows = await db.recent_decisions(symbol=symbol, status=status, limit=limit)
    return {"count": len(rows), "decisions": rows}


@router.get("/risk/score/{symbol}")
async def get_symbol_score(symbol: str, request: Request):
    db = request.app.state.db
    rows = await db.recent_decisions(symbol=symbol, status=None, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="No risk decisions yet for symbol")
    row = rows[0]
    return {
        "symbol": symbol,
        "risk_score": float(row["risk_score"]),
        "risk_band": row["risk_band"],
        "evaluated_at": row["evaluated_at"],
    }


@router.get("/risk/portfolio/exposure")
async def portfolio_exposure(request: Request):
    portfolio_client = request.app.state.portfolio_client
    snapshot = await portfolio_client.get_portfolio_snapshot()
    return snapshot.model_dump()


@router.get("/risk/policies")
async def get_policies(request: Request):
    db = request.app.state.db
    return {"policies": await db.get_all_policies()}


class PolicyUpdate(BaseModel):
    enabled: bool
    params: dict[str, Any]


@router.put("/risk/policies/{policy_name}")
async def update_policy(
    policy_name: str,
    body: PolicyUpdate,
    request: Request,
    user: CurrentUser = Depends(require_role("risk_officer")),
):
    db = request.app.state.db
    await db.upsert_policy(policy_name, body.enabled, body.params, updated_by=user.sub)
    await db.insert_audit_log(None, "POLICY_UPDATE", {"policy": policy_name, "by": user.sub, **body.model_dump()})
    return {"policy_name": policy_name, "updated": True}


# ---------------------------------------------------------------------------
# Kill switch / emergency stop APIs
# ---------------------------------------------------------------------------


class KillSwitchRequest(BaseModel):
    reason: str


@router.get("/risk/kill-switch/status")
async def kill_switch_status(request: Request):
    ks = request.app.state.kill_switch
    return {"state": ks.state.value, "reason": ks.reason, "is_halted": ks.state.is_halted}


@router.post("/risk/kill-switch/activate")
async def activate_kill_switch(
    body: KillSwitchRequest, request: Request, user: CurrentUser = Depends(get_current_user)
):
    ks = request.app.state.kill_switch
    new_state = await ks.activate_manual(reason=body.reason, actor=user.sub)
    return {"state": new_state.value}


@router.post("/risk/kill-switch/deactivate")
async def deactivate_kill_switch(request: Request, user: CurrentUser = Depends(get_current_user)):
    ks = request.app.state.kill_switch
    try:
        new_state = await ks.deactivate_manual(actor=user.sub)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"state": new_state.value}


@router.post("/risk/kill-switch/reset")
async def reset_kill_switch(request: Request, user: CurrentUser = Depends(get_current_user)):
    """Clears an AUTOMATIC halt (drawdown / daily loss / circuit breaker /
    emergency stop). Requires the configured elevated role."""
    ks = request.app.state.kill_switch
    try:
        new_state = await ks.reset_automatic(actor=user.sub, actor_roles=user.roles)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"state": new_state.value}


@router.post("/risk/emergency-stop")
async def emergency_stop(body: KillSwitchRequest, request: Request, user: CurrentUser = Depends(get_current_user)):
    ks = request.app.state.kill_switch
    new_state = await ks.emergency_stop(reason=body.reason, actor=user.sub)
    return {"state": new_state.value}


# ---------------------------------------------------------------------------
# Circuit breaker APIs
# ---------------------------------------------------------------------------


@router.get("/risk/circuit-breaker/status")
async def circuit_breaker_status(request: Request, symbols: str = Query(..., description="comma-separated symbols")):
    registry = request.app.state.circuit_breakers
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    return await registry.status_all(symbol_list)


@router.post("/risk/circuit-breaker/{symbol}/trigger")
async def trigger_circuit_breaker(
    symbol: str, request: Request, user: CurrentUser = Depends(require_role("risk_officer"))
):
    registry = request.app.state.circuit_breakers
    await registry.trip(symbol, reason=f"manual_trigger_by_{user.sub}", metric_value=None, threshold=None)
    return {"symbol": symbol, "tripped": True}


@router.post("/risk/circuit-breaker/{symbol}/reset")
async def reset_circuit_breaker(
    symbol: str, request: Request, user: CurrentUser = Depends(require_role("risk_officer"))
):
    registry = request.app.state.circuit_breakers
    await registry.reset(symbol, reason=f"manual_reset_by_{user.sub}")
    return {"symbol": symbol, "tripped": False}


# ---------------------------------------------------------------------------
# Live event stream (SSE) for dashboard
# ---------------------------------------------------------------------------


@router.get("/risk/stream")
async def risk_event_stream(request: Request):
    redis_bus = request.app.state.redis_bus

    async def event_generator():
        client = redis_bus.client
        pubsub = client.pubsub()
        await pubsub.subscribe("sg:risk:events")
        try:
            async for message in pubsub.listen():
                if await request.is_disconnected():
                    break
                if message.get("type") != "message":
                    continue
                yield {"event": "risk_event", "data": message["data"]}
        finally:
            await pubsub.unsubscribe("sg:risk:events")
            await pubsub.close()

    return EventSourceResponse(event_generator())
