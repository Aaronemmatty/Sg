from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEYS = {
    "api_key", "api_secret", "access_token", "refresh_token", "password",
    "secret", "token", "prompt", "system_prompt", "jwt", "authorization",
    "kite_api_key", "kite_api_secret", "kite_access_token",
    "private_key", "public_key",
}

_INLINE_PATTERNS = [
    re.compile(r'(?i)("(?:api_key|api_secret|access_token|password|secret|token)"\s*:\s*")[^"]*(")'),
    re.compile(r"(?i)(://[^:/@\s]+:)[^@/\s]+(@)"),
]


def _redact_value(key: str, value: Any) -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return "***REDACTED***"
    if isinstance(value, str):
        redacted = value
        for pattern in _INLINE_PATTERNS:
            redacted = pattern.sub(r"\1***REDACTED***\2", redacted)
        return redacted
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(key, v) for v in value)
    return value


def redact_sensitive_fields(logger: Any, method_name: str, event_dict: dict) -> dict:
    return {k: _redact_value(k, v) for k, v in event_dict.items()}
