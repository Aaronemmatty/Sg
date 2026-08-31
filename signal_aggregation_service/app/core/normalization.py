"""
Normalization layer: converts whatever shape a strategy reports into the canonical
SignalVote used by weighting/confidence/conflict resolution. Keeping this isolated means
a strategy that reports e.g. a position size or a -1..+1 score instead of BUY/SELL/HOLD +
confidence only requires a change here, not in the engine.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.models.domain import SignalAction, SignalVote, StrategySignal

ACTION_TO_DIRECTION = {
    SignalAction.BUY: 1,
    SignalAction.SELL: -1,
    SignalAction.HOLD: 0,
}


def normalize_signal(raw: dict, settings: Settings, now: datetime | None = None) -> SignalVote | None:
    """
    Parses a raw payload (from Redis key or pub/sub message) into a StrategySignal, then
    into a SignalVote. Returns None if the payload is malformed or the signal is stale
    beyond `settings.SIGNAL_STALENESS_SECONDS` (callers may still choose to surface stale
    signals for transparency — see `normalize_signal_allow_stale`).
    """
    vote = normalize_signal_allow_stale(raw, settings, now=now)
    if vote is None or vote.is_stale:
        return None
    return vote


def normalize_signal_allow_stale(
    raw: dict, settings: Settings, now: datetime | None = None
) -> SignalVote | None:
    try:
        signal = StrategySignal.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None

    now = now or datetime.now(timezone.utc)
    age = (now - signal.timestamp).total_seconds()
    is_stale = age > settings.SIGNAL_STALENESS_SECONDS

    return SignalVote(
        strategy=signal.strategy,
        direction=ACTION_TO_DIRECTION[signal.action],
        confidence=signal.confidence,
        raw_action=signal.action,
        is_stale=is_stale,
    )


def coerce_action(raw_action: object) -> SignalAction | None:
    """
    Best-effort coercion for strategies that report action in slightly different forms
    (e.g. lowercase, numeric score, 'LONG'/'SHORT'). Extend as new strategy conventions
    are onboarded.
    """
    if isinstance(raw_action, SignalAction):
        return raw_action
    if isinstance(raw_action, str):
        normalized = raw_action.strip().upper()
        aliases = {
            "BUY": SignalAction.BUY, "LONG": SignalAction.BUY, "BULLISH": SignalAction.BUY,
            "SELL": SignalAction.SELL, "SHORT": SignalAction.SELL, "BEARISH": SignalAction.SELL,
            "HOLD": SignalAction.HOLD, "NEUTRAL": SignalAction.HOLD, "FLAT": SignalAction.HOLD,
        }
        return aliases.get(normalized)
    if isinstance(raw_action, (int, float)):
        if raw_action > 0:
            return SignalAction.BUY
        if raw_action < 0:
            return SignalAction.SELL
        return SignalAction.HOLD
    return None
