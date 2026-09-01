"""Shared pytest fixtures for orpheus-common tests."""

import pytest

from orpheus_common.config import OrpheusConfig


@pytest.fixture(autouse=True)
def reset_orpheus_config_singleton() -> None:
    """Reset OrpheusConfig singleton between tests.

    Prevents cross-test config pollution. See
    docs/agent-instructions/99-gotchas.md.
    """
    original_instance = OrpheusConfig._instance
    original_dotenv = OrpheusConfig._DOTENV_LOADED
    OrpheusConfig._instance = None
    OrpheusConfig._DOTENV_LOADED = False
    yield
    OrpheusConfig._instance = original_instance
    OrpheusConfig._DOTENV_LOADED = original_dotenv


@pytest.fixture(autouse=True)
def unset_log_level_env(monkeypatch):
    """Remove LOG_LEVEL env var so tests are not affected by the user's shell."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
