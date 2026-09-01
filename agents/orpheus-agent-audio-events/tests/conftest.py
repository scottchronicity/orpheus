"""Pytest configuration and shared fixtures for audio-events agent tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from orpheus_common.config import OrpheusConfig

from orpheus_agent_audio_events import audioset_ontology
from orpheus_agent_audio_events.audioset_ontology import AudioSetLabel


@pytest.fixture(autouse=True)
def reset_orpheus_config_singleton() -> None:
    """Reset OrpheusConfig singleton between tests.

    Without this, tests that read config see whatever state a previous
    test installed — and tests that mutate config can pollute the
    rest of the suite. See docs/agent-instructions/99-gotchas.md.
    """
    original_instance = OrpheusConfig._instance
    original_dotenv = OrpheusConfig._DOTENV_LOADED
    OrpheusConfig._instance = None
    OrpheusConfig._DOTENV_LOADED = False
    yield
    OrpheusConfig._instance = original_instance
    OrpheusConfig._DOTENV_LOADED = original_dotenv


@pytest.fixture(autouse=True)
def _reset_ontology_cache() -> None:
    """Ensure the audioset_ontology module cache is fresh per test."""
    audioset_ontology.reset_cache()


@pytest.fixture
def tiny_labels_csv(tmp_path: Path) -> Path:
    """A controlled small AudioSet-style CSV for unit tests."""
    csv_path = tmp_path / "tiny_audioset.csv"
    csv_path.write_text(
        "index,mid,display_name\n"
        "0,/m/test_a,Test Class A\n"
        "1,/m/test_b,Test Class B\n"
        "5,/m/test_c,Test Class C\n"
    )
    return csv_path


@pytest.fixture
def tiny_labels(tiny_labels_csv: Path) -> dict[int, AudioSetLabel]:
    """Loaded form of the tiny labels CSV."""
    return audioset_ontology.load_labels(tiny_labels_csv)
