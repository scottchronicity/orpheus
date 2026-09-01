"""Tests for the process-wide cached ``DetectionDB`` accessor.

One schema migration per process instead of per request — part of the
UI-sluggishness hardening (the history endpoints used to construct a fresh
``DetectionDB`` on every 30s poll, re-running schema init + ``CREATE INDEX``).
"""

import orpheus_ui.db as db_module
from orpheus_ui.api import entities
from orpheus_ui.db import get_detection_db


class TestCachedDetectionDB:
    """A single shared DetectionDB, constructed once."""

    def test_constructs_once_and_returns_same_instance(self, monkeypatch):
        monkeypatch.setattr(db_module, "_db", None)
        calls = {"n": 0}

        def fake_ctor(**kwargs):
            calls["n"] += 1
            return object()

        monkeypatch.setattr(db_module, "DetectionDB", fake_ctor)

        first = get_detection_db()
        second = get_detection_db()
        assert first is second
        assert calls["n"] == 1  # cached — schema migration runs once, not per call

    def test_entities_get_db_delegates_to_shared_accessor(self, monkeypatch):
        monkeypatch.setattr(db_module, "_db", None)
        sentinel = object()
        monkeypatch.setattr(db_module, "DetectionDB", lambda **kwargs: sentinel)

        # entities._get_db is a thin shim over the shared accessor, so both the
        # entities endpoints and the diagnostics endpoints hit one instance.
        assert entities._get_db() is sentinel
        assert entities._get_db() is get_detection_db()
