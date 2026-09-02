"""Unit tests for shared CORS origins parser."""
from __future__ import annotations

import pytest

from sg_security.cors import parse_cors_origins


def test_parse_cors_single_origin():
    assert parse_cors_origins("http://localhost:3000") == ["http://localhost:3000"]


def test_parse_cors_multiple_origins_comma_separated():
    res = parse_cors_origins("http://localhost:3000,http://localhost:8000,https://app.sgtrading.in")
    assert res == ["http://localhost:3000", "http://localhost:8000", "https://app.sgtrading.in"]


def test_parse_cors_with_whitespace_and_trailing_commas():
    res = parse_cors_origins("  http://localhost:3000 ,  http://localhost:8000/ , , ")
    assert res == ["http://localhost:3000", "http://localhost:8000/"]


def test_parse_cors_deduplication():
    res = parse_cors_origins("http://localhost:3000, http://localhost:3000, http://localhost:8000")
    assert res == ["http://localhost:3000", "http://localhost:8000"]


def test_parse_cors_empty_or_none_returns_default():
    assert parse_cors_origins(None) == ["http://localhost"]
    assert parse_cors_origins("") == ["http://localhost"]
    assert parse_cors_origins("   ") == ["http://localhost"]
    assert parse_cors_origins([], default=["https://trusted.domain"]) == ["https://trusted.domain"]


def test_parse_cors_from_list_or_sequence():
    res = parse_cors_origins(["http://localhost:3000", "http://localhost:8000, http://localhost:9000"])
    assert res == ["http://localhost:3000", "http://localhost:8000", "http://localhost:9000"]
