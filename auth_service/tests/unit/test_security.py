"""Unit tests — security.py (no I/O, fully isolated)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_code,
    hash_password,
    make_api_key,
    password_strength_ok,
    verify_password,
    verify_totp,
    totp_provisioning_uri,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def token_payload():
    return dict(
        sub="user-uuid-123",
        tenant_id="tenant-uuid-456",
        roles=["trader"],
        permissions=["order:create", "portfolio:read"],
        session_id="session-abc",
    )


# ── Password ──────────────────────────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self):
        plain = "MyS3cure!Pass#2024"
        h = hash_password(plain)
        assert h != plain
        assert verify_password(plain, h)

    def test_wrong_password_fails(self):
        h = hash_password("correct-horse-battery-staple-99!")
        assert not verify_password("wrong", h)

    def test_unique_hashes(self):
        plain = "SamePassword1!"
        assert hash_password(plain) != hash_password(plain)  # bcrypt salts differ

    @pytest.mark.parametrize("pw,expected_ok", [
        ("short1!", False),
        ("alllowercasenodigits!longpassword", False),
        ("ALLUPPERCASENODIGITS!123456789", False),
        ("ValidP@ssw0rd1234", True),
        ("a" * 129 + "A1!", False),
    ])
    def test_password_strength(self, pw, expected_ok):
        ok, reason = password_strength_ok(pw)
        assert ok is expected_ok
        if not ok:
            assert len(reason) > 0


# ── JWT ───────────────────────────────────────────────────────────────────────

class TestJWT:
    def test_access_token_decode(self, token_payload):
        token = create_access_token(**token_payload)
        decoded = decode_token(token)
        assert decoded["sub"] == token_payload["sub"]
        assert decoded["type"] == "access"
        assert decoded["roles"] == ["trader"]
        assert "jti" in decoded
        assert "exp" in decoded

    def test_refresh_token_decode(self, token_payload):
        token = create_refresh_token(
            sub=token_payload["sub"],
            tenant_id=token_payload["tenant_id"],
            session_id=token_payload["session_id"],
        )
        decoded = decode_token(token)
        assert decoded["type"] == "refresh"
        assert decoded["sub"] == token_payload["sub"]

    def test_expired_token_raises(self, token_payload):
        from unittest.mock import patch
        from datetime import UTC, datetime, timedelta

        with patch("app.core.security._now", return_value=datetime(2000, 1, 1, tzinfo=UTC)):
            token = create_access_token(**token_payload)

        from jose import JWTError
        with pytest.raises(JWTError):
            decode_token(token)

    def test_tampered_token_raises(self, token_payload):
        from jose import JWTError
        token = create_access_token(**token_payload)
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(JWTError):
            decode_token(tampered)

    def test_access_and_refresh_different(self, token_payload):
        access = create_access_token(**token_payload)
        refresh = create_refresh_token(
            sub=token_payload["sub"],
            tenant_id=token_payload["tenant_id"],
            session_id=token_payload["session_id"],
        )
        assert access != refresh


# ── TOTP / MFA ────────────────────────────────────────────────────────────────

class TestTOTP:
    def test_secret_generation(self):
        secret = generate_totp_secret()
        assert len(secret) >= 32
        assert secret.isalpha() or secret.isalnum()

    def test_valid_totp(self):
        import pyotp
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        assert verify_totp(secret, code)

    def test_invalid_totp(self):
        secret = generate_totp_secret()
        assert not verify_totp(secret, "000000")

    def test_provisioning_uri_format(self):
        secret = generate_totp_secret()
        uri = totp_provisioning_uri(secret, "trader@sg.local")
        assert uri.startswith("otpauth://totp/")
        assert "SG%20Trading" in uri or "SG Trading" in uri
        assert "trader%40sg.local" in uri or "trader@sg.local" in uri


# ── Backup codes ──────────────────────────────────────────────────────────────

class TestBackupCodes:
    def test_generates_10_codes(self):
        codes = generate_backup_codes(10)
        assert len(codes) == 10
        assert all(len(c) == 32 for c in codes)  # token_hex(16).upper() = 32 chars

    def test_all_unique(self):
        codes = generate_backup_codes(10)
        assert len(set(codes)) == 10

    def test_hash_deterministic(self):
        code = "ABCD1234"
        assert hash_backup_code(code) == hash_backup_code(code)

    def test_hash_differs_for_different_codes(self):
        assert hash_backup_code("AAAA1111") != hash_backup_code("BBBB2222")


# ── API keys ──────────────────────────────────────────────────────────────────

class TestApiKeys:
    def test_make_api_key_structure(self):
        raw, prefix, digest = make_api_key()
        assert raw.startswith("sk_")
        assert len(raw) > 40
        assert prefix == raw[:12]
        assert len(digest) == 64  # sha256 hex

    def test_make_api_key_unique(self):
        raw1, _, _ = make_api_key()
        raw2, _, _ = make_api_key()
        assert raw1 != raw2
