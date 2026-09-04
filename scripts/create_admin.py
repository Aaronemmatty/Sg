#!/usr/bin/env python3
"""
SG Trading Platform — Admin User Provisioning CLI.

Creates or resets an administrator account in the PostgreSQL identity database.
Uses the platform's standard bcrypt password hashing (12 rounds) and associates
the user with the default tenant and admin/risk_officer/trader roles.

Usage:
    python scripts/create_admin.py
    python scripts/create_admin.py --email admin@sg-trading.com --password "YourSecurePassword123!" --name "Lead Administrator"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import string
import sys
import uuid
from typing import Optional

import bcrypt
from dotenv import dotenv_values
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Ensure project paths are imported
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

DEFAULT_TENANT_SLUG = "default"
DEFAULT_EMAIL = "admin@sg-trading.com"
DEFAULT_NAME = "Lead Administrator"


def generate_nist_password(length: int = 24) -> str:
    """Generate a cryptographically secure, NIST 800-63B compliant password."""
    upper = secrets.choice(string.ascii_uppercase)
    lower = secrets.choice(string.ascii_lowercase)
    digit = secrets.choice(string.digits)
    special = secrets.choice("!@#$%^&*()-_=+")
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    remaining = [secrets.choice(alphabet) for _ in range(max(12, length) - 4)]
    pwd_list = [upper, lower, digit, special] + remaining
    secrets.SystemRandom().shuffle(pwd_list)
    return "".join(pwd_list)


def hash_password(plain: str) -> str:
    """Hash password using bcrypt with 12 rounds (matching auth_service)."""
    return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt(12)).decode("utf-8")


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password against NIST 800-63B standards (matching auth_service)."""
    if len(password) < 12:
        return False, "Password must be at least 12 characters."
    if len(password) > 128:
        return False, "Password must not exceed 128 characters."
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)
    if not (has_upper and has_lower and has_digit and has_special):
        return False, "Password must contain uppercase, lowercase, digit, and special character."
    return True, ""


async def provision_admin(
    email: str = DEFAULT_EMAIL,
    password: Optional[str] = None,
    display_name: str = DEFAULT_NAME,
    tenant_slug: str = DEFAULT_TENANT_SLUG,
    db_url_override: Optional[str] = None,
) -> dict[str, str]:
    # 1. Resolve or generate password and validate strength
    if not password:
        password = generate_nist_password()

    ok, err = validate_password_strength(password)
    if not ok:
        raise ValueError(f"Password rejected: {err}")

    # 2. Resolve database connection URL
    if not db_url_override:
        auth_env = dotenv_values(os.path.join(REPO_ROOT, "auth_service", ".env"))
        root_env = dotenv_values(os.path.join(REPO_ROOT, ".env"))
        db_url_override = (
            auth_env.get("DATABASE_URL")
            or root_env.get("DATABASE_URL")
            or os.environ.get("DATABASE_URL")
        )

    if not db_url_override:
        raise RuntimeError("DATABASE_URL not found in auth_service/.env, .env, or environment.")

    # Normalize asyncpg dialect for SQLAlchemy and ensure IPv4 on Windows
    if db_url_override.startswith("postgresql://"):
        db_url_override = db_url_override.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "@localhost:" in db_url_override:
        db_url_override = db_url_override.replace("@localhost:", "@127.0.0.1:")

    engine = create_async_engine(db_url_override, echo=False)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    email_clean = email.strip().lower()
    pw_hash = hash_password(password)

    async with async_session() as session:
        async with session.begin():
            # 3. Ensure Default Tenant exists
            res_t = await session.execute(
                text("SELECT id, name FROM tenants WHERE slug = :slug;"),
                {"slug": tenant_slug},
            )
            tenant_row = res_t.fetchone()
            if not tenant_row:
                tenant_id = uuid.uuid4()
                await session.execute(
                    text(
                        "INSERT INTO tenants (id, name, slug, status, settings, created_at, updated_at) "
                        "VALUES (:id, :name, :slug, 'ACTIVE', '{}', NOW(), NOW());"
                    ),
                    {"id": tenant_id, "name": "Default Tenant", "slug": tenant_slug},
                )
                print(f"[+] Created tenant '{tenant_slug}' ({tenant_id})")
            else:
                tenant_id = tenant_row[0]

            # 4. Ensure System Roles exist
            required_roles = {
                "admin": "Platform Administrator",
                "risk_officer": "Risk Management Officer",
                "trader": "Trading Operator",
                "viewer": "Read-only Viewer",
            }
            role_map = {}
            for role_name, role_desc in required_roles.items():
                res_r = await session.execute(
                    text("SELECT id FROM roles WHERE tenant_id = :tid AND name = :name;"),
                    {"tid": tenant_id, "name": role_name},
                )
                r_row = res_r.fetchone()
                if not r_row:
                    r_id = uuid.uuid4()
                    await session.execute(
                        text(
                            "INSERT INTO roles (id, tenant_id, name, description, is_system, created_at, updated_at) "
                            "VALUES (:id, :tid, :name, :desc, true, NOW(), NOW());"
                        ),
                        {"id": r_id, "tid": tenant_id, "name": role_name, "desc": role_desc},
                    )
                    role_map[role_name] = r_id
                    print(f"[+] Created system role '{role_name}'")
                else:
                    role_map[role_name] = r_row[0]

            # 5. Check if User exists
            res_u = await session.execute(
                text("SELECT id FROM users WHERE tenant_id = :tid AND email = :email;"),
                {"tid": tenant_id, "email": email_clean},
            )
            u_row = res_u.fetchone()

            if u_row:
                user_id = u_row[0]
                await session.execute(
                    text(
                        "UPDATE users SET "
                        "  password_hash = :hash, "
                        "  display_name = :name, "
                        "  is_active = true, "
                        "  mfa_enabled = false, "
                        "  preferences = jsonb_set(COALESCE(preferences, '{}'), '{email_verified}', 'true'::jsonb), "
                        "  updated_at = NOW() "
                        "WHERE id = :uid;"
                    ),
                    {"hash": pw_hash, "name": display_name, "uid": user_id},
                )
                action = "UPDATED (Password Reset)"
            else:
                user_id = uuid.uuid4()
                await session.execute(
                    text(
                        "INSERT INTO users (id, tenant_id, email, password_hash, display_name, is_active, mfa_enabled, preferences, created_at, updated_at) "
                        "VALUES (:id, :tid, :email, :hash, :name, true, false, '{\"email_verified\": true}', NOW(), NOW());"
                    ),
                    {
                        "id": user_id,
                        "tid": tenant_id,
                        "email": email_clean,
                        "hash": pw_hash,
                        "name": display_name,
                    },
                )
                action = "CREATED"

            # 6. Assign Roles (admin, risk_officer, trader)
            assigned = ["admin", "risk_officer", "trader"]
            for r_name in assigned:
                r_id = role_map[r_name]
                await session.execute(
                    text(
                        "INSERT INTO user_roles (tenant_id, user_id, role_id, created_at, updated_at) "
                        "VALUES (:tid, :uid, :rid, NOW(), NOW()) "
                        "ON CONFLICT DO NOTHING;"
                    ),
                    {"tid": tenant_id, "uid": user_id, "rid": r_id},
                )

    await engine.dispose()
    print(f"[OK] Admin account {email_clean} successfully {action}!")
    return {
        "action": action,
        "email": email_clean,
        "password": password,
        "roles": ", ".join(assigned),
        "tenant": tenant_slug,
    }


def main():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    parser = argparse.ArgumentParser(description="Provision an administrator account in SG Trading Platform.")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help=f"Admin email (default: {DEFAULT_EMAIL})")
    parser.add_argument("--password", default=None, help="Admin password (generated automatically if omitted)")
    parser.add_argument("--name", default=DEFAULT_NAME, help=f"Display name (default: {DEFAULT_NAME})")
    parser.add_argument("--tenant", default=DEFAULT_TENANT_SLUG, help=f"Tenant slug (default: {DEFAULT_TENANT_SLUG})")
    args = parser.parse_args()

    result = asyncio.run(
        provision_admin(
            email=args.email,
            password=args.password,
            display_name=args.name,
            tenant_slug=args.tenant,
        )
    )
    print("=" * 60)
    print("SG TRADING PLATFORM — ADMIN CREDENTIALS")
    print("=" * 60)
    print(f"  Action:   {result['action']}")
    print(f"  Email:    {result['email']}")
    print(f"  Password: {result['password']}")
    print(f"  Roles:    {result['roles']}")
    print(f"  Tenant:   {result['tenant']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
