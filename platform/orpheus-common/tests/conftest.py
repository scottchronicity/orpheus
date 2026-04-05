"""Shared pytest fixtures for orpheus-common tests."""

import pytest


@pytest.fixture(autouse=True)
def unset_log_level_env(monkeypatch):
    """Remove LOG_LEVEL env var so tests are not affected by the user's shell."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
