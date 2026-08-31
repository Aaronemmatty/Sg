"""pytest configuration — execution orchestrator tests."""
import pytest


# Force all async tests to use the same event loop policy
pytest_plugins = ["anyio"]
