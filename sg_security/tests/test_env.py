"""Unit tests for environment detection."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from sg_security.env import is_development, is_production, is_staging


def test_is_production_from_settings():
    assert is_production(SimpleNamespace(ENV="prod")) is True
    assert is_production(SimpleNamespace(env="production")) is True
    assert is_production(SimpleNamespace(APP_ENV="production")) is True
    assert is_production(SimpleNamespace(app_env="prod")) is True
    assert is_production(SimpleNamespace(ENV="dev")) is False
    assert is_production(SimpleNamespace(ENV="staging")) is False


def test_is_staging_and_development():
    assert is_staging(SimpleNamespace(ENV="staging")) is True
    assert is_staging(SimpleNamespace(APP_ENV="stage")) is True
    assert is_staging(SimpleNamespace(ENV="dev")) is False

    assert is_development(SimpleNamespace(ENV="dev")) is True
    assert is_development(SimpleNamespace(ENV="prod")) is False
    assert is_development(SimpleNamespace(ENV="staging")) is False


def test_is_production_from_os_environ(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert is_production() is True

    monkeypatch.setenv("APP_ENV", "dev")
    assert is_production() is False

    monkeypatch.setenv("ENV", "prod")
    assert is_production() is True
