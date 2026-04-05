"""Pytest configuration and fixtures for crow detection agent tests."""

import pytest
from orpheus_common.config import OrpheusConfig


@pytest.fixture(autouse=True)
def reset_orpheus_config_singleton() -> None:
    """Reset OrpheusConfig singleton between tests."""
    # Store original values
    original_instance = OrpheusConfig._instance
    original_dotenv = OrpheusConfig._DOTENV_LOADED

    # Clear singleton before test
    OrpheusConfig._instance = None
    OrpheusConfig._DOTENV_LOADED = False

    yield

    # Restore original state after test
    OrpheusConfig._instance = original_instance
    OrpheusConfig._DOTENV_LOADED = original_dotenv
