"""Misc small helpers."""
from __future__ import annotations

import uuid


def make_idempotency_key(intent_id: uuid.UUID, attempt: int = 0) -> str:
    """Deterministic per-intent idempotency key. `attempt` is included so a
    deliberate manual re-route (e.g. after a FAILED order) can mint a new key,
    while accidental duplicate delivery of the same intent (attempt always 0
    from the consumer's perspective) collapses onto the same key and is
    rejected by the DB unique constraint / claim_idempotency_key check."""
    if attempt == 0:
        return f"intent:{intent_id}"
    return f"intent:{intent_id}:retry:{attempt}"
