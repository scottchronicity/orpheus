"""Fixtures for the crow-detection e2e bus-contract oracle.

These stand up the REAL ``CrowDetectionAgent`` against a REAL nats-server with its
ML models + DB stubbed, so the tests exercise the genuine lifecycle/bus code
(connect → subscribe → publish → heartbeat → shutdown) — the code an actor-model
refactor will touch — and assert observable bus behavior. No production code is
modified; the model attributes are replaced exactly as the unit tests do.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from orpheus_common.testing import (
    DEFAULT_NATS_URL,
    nats_config,
    require_broker,
    reset_orpheus_config_singleton,
)

from orpheus_agent_crow_detection import main as crow_main
from orpheus_agent_crow_detection.classifier import CrowDetectionResult

NATS_URL = DEFAULT_NATS_URL


# Shared body from orpheus_common.testing — one definition, every suite.
_reset_orpheus_config_singleton = pytest.fixture(autouse=True)(
    reset_orpheus_config_singleton
)


@pytest.fixture(scope="session")
def nats_url() -> str:
    return require_broker(NATS_URL)


@pytest.fixture
def make_crow_agent(nats_url, monkeypatch):
    """Build a CrowDetectionAgent wired to NATS with stubbed models/DB/audio.

    Returns a builder ``make(is_crow: bool)`` so a test picks whether the (fake)
    classifier confirms a crow — driving the publish-vs-silence contract."""
    cfg = nats_config(nats_url)
    # The agent reads orpheus_config (for the bus) and a crow-specific config.
    monkeypatch.setattr(crow_main.OrpheusConfig, "get_instance", MagicMock(return_value=cfg))
    crow_cfg = SimpleNamespace(
        enabled=True,
        embedder_model_path="<stub>",
        embedder_sample_rate=16000,
        classifier_model_path="<stub>",
        quality_threshold=0.5,
    )
    monkeypatch.setattr(crow_main, "load_config", MagicMock(return_value=crow_cfg))

    # Audio with non-zero variance (a zero array is skipped by _scan_audio's
    # std==0 guard) at the embedder rate so no resample is needed.
    audio = np.random.default_rng(0).standard_normal(48000).astype(np.float32)
    monkeypatch.setattr(crow_main.sf, "read", MagicMock(return_value=(audio, 16000)))

    # No SQLite side effects: DetectionDB() yields a mock that absorbs any call.
    monkeypatch.setattr(crow_main, "DetectionDB", MagicMock(return_value=MagicMock()))

    def _build(is_crow: bool):
        # Patch the model constructors so start()'s load block yields fakes.
        fake_embedder = MagicMock()
        fake_embedder.generate_embedding.return_value = np.zeros((1, 768), np.float32)
        monkeypatch.setattr(crow_main, "AVESEmbedder", MagicMock(return_value=fake_embedder))

        fake_classifier = MagicMock()
        fake_classifier.classify.return_value = CrowDetectionResult(
            is_crow=is_crow,
            quality_score=0.9 if is_crow else 0.1,
            species="american_crow" if is_crow else "unknown",
            call_type="caw" if is_crow else None,
            attributes={},
        )
        monkeypatch.setattr(crow_main, "CrowClassifier", MagicMock(return_value=fake_classifier))

        return crow_main.CrowDetectionAgent()

    return _build
