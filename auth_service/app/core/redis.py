"""Redis client — sessions, token blacklist, rate-limit counters."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = await aioredis.from_url(
            str(settings.REDIS_URL),
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
    return _pool


async def close_redis() -> None:
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None


# ── Token blacklist ───────────────────────────────────────────────────────────

async def blacklist_jti(jti: str, ttl_seconds: int) -> None:
    r = await get_redis()
    await r.setex(f"blacklist:{jti}", ttl_seconds, "1")


async def is_jti_blacklisted(jti: str) -> bool:
    r = await get_redis()
    return bool(await r.exists(f"blacklist:{jti}"))


# ── Session store ─────────────────────────────────────────────────────────────

async def store_session(session_id: str, data: dict[str, Any], ttl: int) -> None:
    r = await get_redis()
    await r.setex(f"session:{session_id}", ttl, json.dumps(data, default=str))


async def get_session(session_id: str) -> dict[str, Any] | None:
    r = await get_redis()
    raw = await r.get(f"session:{session_id}")
    return json.loads(raw) if raw else None


async def delete_session(session_id: str) -> None:
    r = await get_redis()
    await r.delete(f"session:{session_id}")


async def delete_all_user_sessions(user_id: str) -> int:
    """Revoke every session for a user (logout everywhere)."""
    r = await get_redis()
    pattern = f"session:*"
    count = 0
    async for key in r.scan_iter(pattern):
        raw = await r.get(key)
        if raw:
            data = json.loads(raw)
            if data.get("user_id") == user_id:
                await r.delete(key)
                count += 1
    log.info("user_sessions_revoked", user_id=user_id, count=count)
    return count


# ── Rate limiting ─────────────────────────────────────────────────────────────

async def increment_login_attempts(key: str) -> int:
    r = await get_redis()
    pipe = r.pipeline()
    pipe.incr(f"login_attempts:{key}")
    pipe.expire(
        f"login_attempts:{key}",
        settings.LOCKOUT_DURATION_MINUTES * 60,
    )
    results = await pipe.execute()
    return int(results[0])


async def get_login_attempts(key: str) -> int:
    r = await get_redis()
    val = await r.get(f"login_attempts:{key}")
    return int(val) if val else 0


async def clear_login_attempts(key: str) -> None:
    r = await get_redis()
    await r.delete(f"login_attempts:{key}")


async def set_lockout(key: str) -> None:
    r = await get_redis()
    await r.setex(
        f"lockout:{key}",
        settings.LOCKOUT_DURATION_MINUTES * 60,
        "1",
    )


async def is_locked_out(key: str) -> bool:
    r = await get_redis()
    return bool(await r.exists(f"lockout:{key}"))


# ── OTP / verification tokens ─────────────────────────────────────────────────

async def store_verification_token(token: str, data: dict[str, Any], ttl_seconds: int) -> None:
    r = await get_redis()
    await r.setex(f"verify:{token}", ttl_seconds, json.dumps(data, default=str))


async def consume_verification_token(token: str) -> dict[str, Any] | None:
    r = await get_redis()
    key = f"verify:{token}"
    raw = await r.get(key)
    if raw:
        await r.delete(key)
        return json.loads(raw)
    return None


# ── MFA pending ───────────────────────────────────────────────────────────────

async def store_mfa_challenge(challenge_id: str, user_id: str, ttl: int = 300) -> None:
    r = await get_redis()
    await r.setex(f"mfa_challenge:{challenge_id}", ttl, user_id)


async def consume_mfa_challenge(challenge_id: str) -> str | None:
    r = await get_redis()
    key = f"mfa_challenge:{challenge_id}"
    user_id = await r.get(key)
    if user_id:
        await r.delete(key)
    return user_id
