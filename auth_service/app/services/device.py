"""Device fingerprinting and tracking service."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_ua

from app.models.auth import UserDevice
from sg_db.models.identity import User


class DeviceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _fingerprint(self, request: Request | None) -> str:
        if not request:
            return "system_client"
        ua = request.headers.get("user-agent", "")
        ip = request.client.host if request.client else ""
        # Stable fingerprint: hash of UA + /24 subnet
        subnet = ".".join(ip.split(".")[:3]) if "." in ip else ip
        raw = f"{ua}|{subnet}"
        return hashlib.sha256(raw.encode()).hexdigest()[:64]

    async def upsert_device(
        self,
        *,
        user: User,
        request: Request | None,
        device_name: str | None = None,
    ) -> UserDevice:
        fingerprint = self._fingerprint(request)
        ua_string = request.headers.get("user-agent", "") if request else ""
        parsed = parse_ua(ua_string)

        result = await self.db.execute(
            select(UserDevice).where(
                UserDevice.user_id == user.id,
                UserDevice.device_fingerprint == fingerprint,
                UserDevice.deleted_at.is_(None),
            )
        )
        device = result.scalar_one_or_none()

        ip = request.client.host if (request and request.client) else None
        if device:
            device.last_seen_ip = ip
            device.last_seen_at = datetime.now(UTC)
            device.login_count += 1
        else:
            device = UserDevice(
                tenant_id=user.tenant_id,
                user_id=user.id,
                device_fingerprint=fingerprint,
                device_name=device_name or parsed.device.family,
                device_type="mobile" if parsed.is_mobile else "tablet" if parsed.is_tablet else "desktop",
                os=f"{parsed.os.family} {parsed.os.version_string}".strip(),
                browser=f"{parsed.browser.family} {parsed.browser.version_string}".strip(),
                last_seen_ip=ip,
                last_seen_at=datetime.now(UTC),
                login_count=1,
            )
            self.db.add(device)

        await self.db.flush()
        return device
