"""Pytest configuration and fixtures for audio motion detector tests."""

import os

import pytest
from orpheus_common.config import OrpheusConfig


@pytest.fixture(autouse=True)
def reset_orpheus_config_singleton():
    """
    Reset OrpheusConfig singleton and clean up environment variables between tests.

    This prevents test pollution when previous tests set environment variables
    or load dotenv files that persist across test runs.

    Note: We access private attributes (_instance, _DOTENV_LOADED) because
    OrpheusConfig is a singleton that doesn't expose public reset methods.
    This is a deliberate trade-off for test isolation vs. encapsulation.
    """
    # Store original values
    original_instance = OrpheusConfig._instance
    original_dotenv = OrpheusConfig._DOTENV_LOADED

    # Clear singleton before test
    OrpheusConfig._instance = None
    OrpheusConfig._DOTENV_LOADED = False

    # Clean up any pollution from dotenv files
    env_vars_to_clean = [
        "ORPHEUS_MQTT__BROKER_PORT",
        "ORPHEUS_STORAGE__BASE_PATH",
        "ORPHEUS_MQTT__BROKER_HOST",
    ]
    original_env = {}
    for var in env_vars_to_clean:
        if var in os.environ:
            original_env[var] = os.environ.pop(var)

    yield

    # Restore original state after test
    OrpheusConfig._instance = original_instance
    OrpheusConfig._DOTENV_LOADED = original_dotenv

    # Restore environment variables
    for var, value in original_env.items():
        os.environ[var] = value
