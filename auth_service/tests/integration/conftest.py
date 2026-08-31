"""Integration test fixtures — real async DB + TestClient."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import get_db
from app.main import app
from sg_db.base import Base

# ── Test database ─────────────────────────────────────────────────────────────

TEST_DATABASE_URL = "postgresql+asyncpg://sg:sg@localhost:5432/sg_auth_test"

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True)
_TestSession = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_tables():
    """Create all tables before the test session, drop after."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a rolled-back session per test."""
    async with _engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """TestClient with DB dependency overridden."""
    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    # Mock Redis calls globally for integration tests
    import app.core.redis as redis_mod
    redis_mod.is_locked_out = lambda _: False  # type: ignore
    redis_mod.increment_login_attempts = lambda _: 1  # type: ignore
    redis_mod.clear_login_attempts = lambda _: None  # type: ignore
    redis_mod.store_session = lambda *a, **k: None  # type: ignore
    redis_mod.store_mfa_challenge = lambda *a, **k: None  # type: ignore

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    app.dependency_overrides.clear()


# ── Seed helpers ──────────────────────────────────────────────────────────────

async def create_tenant(db: AsyncSession, slug: str = "test-tenant") -> Any:
    from sg_db.models.tenant import Tenant
    tenant = Tenant(slug=slug, name="Test Tenant")
    db.add(tenant)
    await db.flush()
    return tenant


async def create_user(
    db: AsyncSession,
    tenant_id: Any,
    email: str = "trader@sg.local",
    password: str = "ValidP@ssw0rd1234",
    email_verified: bool = True,
) -> Any:
    from app.core.security import hash_password
    from sg_db.models.identity import User

    user = User(
        tenant_id=tenant_id,
        email=email,
        password_hash=hash_password(password),
        display_name="Test Trader",
        is_active=True,
        preferences={"email_verified": email_verified},
    )
    db.add(user)
    await db.flush()
    return user
