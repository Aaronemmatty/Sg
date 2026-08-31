"""Alembic env.py — async migrations for auth service."""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

# Ensure auth_service root is at the front of sys.path and remove other sibling services
service_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
repo_dir = os.path.dirname(service_dir)
sys.path = [p for p in sys.path if not (p.startswith(repo_dir) and ".venv" not in p and p != service_dir and p != os.path.join(repo_dir, "database"))]
if service_dir not in sys.path:
    sys.path.insert(0, service_dir)
for mod in list(sys.modules.keys()):
    if mod == "app" or mod.startswith("app."):
        del sys.modules[mod]


from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models.auth import (  # noqa: F401 — ensure models are registered
    EmailVerificationToken,
    MfaBackupCode,
    OAuthAccount,
    PasswordResetToken,
    UserDevice,
    UserSession,
)
from sg_db.base import Base

settings = get_settings()
config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(settings.DATABASE_URL),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), future=True)
    async with engine.connect() as conn:
        await conn.run_sync(
           lambda sync_conn: context.configure(
                connection=sync_conn,
                target_metadata=target_metadata,
                version_table="alembic_version_auth",
            )
        )
        async with conn.begin():
            await conn.run_sync(lambda _: context.run_migrations())
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
