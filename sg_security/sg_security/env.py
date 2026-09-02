"""Environment detection utilities across SG services."""
from __future__ import annotations

import os
from typing import Any


def is_production(settings: Any = None) -> bool:
    """
    Robustly determine whether the running environment is production.

    Inspects:
      1. Provided settings instance attributes:
         - settings.ENV, settings.env
         - settings.APP_ENV, settings.app_env
      2. Process environment variables:
         - os.environ['APP_ENV']
         - os.environ['ENV']

    Recognizes 'prod', 'production', 'live' (case-insensitive).
    """
    if settings is not None:
        for attr in ("ENV", "env", "APP_ENV", "app_env", "ENVIRONMENT", "environment"):
            val = getattr(settings, attr, None)
            if val is not None and str(val).strip().lower() in ("prod", "production", "live"):
                return True

    for var in ("APP_ENV", "ENV", "ENVIRONMENT"):
        val = os.getenv(var)
        if val is not None and val.strip().lower() in ("prod", "production", "live"):
            return True

    return False


def is_staging(settings: Any = None) -> bool:
    """Check if environment is staging."""
    if settings is not None:
        for attr in ("ENV", "env", "APP_ENV", "app_env", "ENVIRONMENT", "environment"):
            val = getattr(settings, attr, None)
            if val is not None and str(val).strip().lower() in ("staging", "stage"):
                return True

    for var in ("APP_ENV", "ENV", "ENVIRONMENT"):
        val = os.getenv(var)
        if val is not None and val.strip().lower() in ("staging", "stage"):
            return True

    return False


def is_development(settings: Any = None) -> bool:
    """Check if environment is development/local."""
    return not is_production(settings) and not is_staging(settings)
