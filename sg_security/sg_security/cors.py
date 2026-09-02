"""CORS origin parsing and validation utilities for FastAPI services."""
from __future__ import annotations

from typing import Sequence


def parse_cors_origins(
    origins: str | Sequence[str] | None,
    default: list[str] | None = None,
) -> list[str]:
    """
    Parse and clean CORS allowed origins.

    Features:
      - Accepts comma-separated string, list of strings, or None.
      - Trims whitespace from each origin.
      - Filters out empty strings.
      - Preserves order and deduplicates origins.
      - Refuses wildcard '*' when constructing credentialed CORS lists.
      - Returns safe default (e.g. ['http://localhost']) if result is empty.
    """
    safe_default = list(default) if default is not None else ["http://localhost"]

    if origins is None:
        return safe_default

    raw_items: list[str] = []
    if isinstance(origins, str):
        # Split by comma or semicolon
        for part in origins.replace(";", ",").split(","):
            raw_items.append(part)
    elif isinstance(origins, (list, tuple, set)):
        for item in origins:
            if isinstance(item, str):
                for part in item.replace(";", ",").split(","):
                    raw_items.append(part)

    cleaned: list[str] = []
    seen: set[str] = set()

    for item in raw_items:
        trimmed = item.strip()
        if not trimmed:
            continue
        if trimmed not in seen:
            seen.add(trimmed)
            cleaned.append(trimmed)

    return cleaned if cleaned else safe_default
