from __future__ import annotations

import os

os.environ.setdefault("ENV", "development")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("AUTH_JWT_PUBLIC_KEY_PATH", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
