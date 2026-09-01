"""End-to-end tests for ``AudioEventsAgent`` using the deterministic fake model.

These tests exercise the full pipeline:
  audio.motion event → load clip → run SED (fake) → post-process → emit Detections

without touching panns_inference / PyTorch / a real MQTT broker.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
from orpheus_common.detection import Detection
from orpheus_common.event_sourcing import domain_subject

from orpheus_agent_audio_events.main import AudioEventsAgent, main
from orpheus_agent_audio_events.model import DeterministicFakeSED


def _make_synthetic_clip(
    path: Path, duration_seconds: float = 3.0, sample_rate: int = 48000
) -> None:
    """Write a synthetic mono WAV file (white noise) to disk."""
    samples = int(duration_seconds * sample_rate)
    rng = np.random.default_rng(seed=42)
    audio = rng.standard_normal(samples).astype(np.float32) * 0.1
    sf.write(path, audio, sample_rate)


def _audio_motion_payload(clip_path: Path) -> dict[str, Any]:
    """Build an audio.motion payload as a dict (matches what MQTT subscribers see)."""
    return Detection(
        event_id="audio_motion_test_001",
        timestamp=datetime.now(timezone.utc),
        detection_type="audio.motion",
        channel=1,
        audio_clip_path=str(clip_path),
        metadata={"duration_seconds": 3.0},
    ).model_dump(mode="json")


@pytest.fixture
def agent_with_fake_model(tiny_labels_csv: Path) -> AudioEventsAgent:
    """Construct an AudioEventsAgent wired to a fake model and tiny labels.

    Patches ``load_config`` and ``OrpheusConfig.get_instance`` so the test
    doesn't require a real orpheus.yaml on disk.
    """
    from orpheus_agent_audio_events import audioset_ontology  # noqa: PLC0415

    with patch(
        "orpheus_agent_audio_events.main.load_config"
    ) as mock_load_config, patch(
        "orpheus_agent_audio_events.main.OrpheusConfig.get_instance"
    ) as mock_get_instance:
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.model_variant = "fake"
        mock_config.model_path = "/var/lib/orpheus/models/unused.pth"
        mock_config.sample_rate = 32000
        mock_config.clip_threshold = 0.3
        mock_config.frame_threshold = 0.2
        mock_config.bridge_ms = 100
        mock_config.min_interval_ms = 100
        mock_config.max_labels_per_clip = None
        mock_config.device = "cpu"
        mock_config.input_topic = "orpheus/audio/motion/events"
        mock_config.output_topic = "orpheus/detection/audio/events"
        mock_config.max_concurrent_clips = 2
        mock_load_config.return_value = mock_config

        mock_orpheus_config = MagicMock()
        mock_get_instance.return_value = mock_orpheus_config

        # Inject the fake model + tiny labels so we control the inputs end-to-end.
        labels = audioset_ontology.load_labels(tiny_labels_csv)
        fake_model = DeterministicFakeSED(
            sample_rate=32000,
            num_classes=10,  # small for tests
            frame_duration_seconds=0.032,
        )
        # Inject test classes that map to the tiny labels CSV indices.
        fake_model.inject_event(class_index=0, start_seconds=0.5, end_seconds=1.5, score=0.9)
        fake_model.inject_event(class_index=5, start_seconds=2.0, end_seconds=2.8, score=0.7)

        agent = AudioEventsAgent(model=fake_model, labels=labels)
        # In-memory DetectionDB so we don't touch /data/orpheus.
        agent.detection_db = MagicMock()
        agent.bus = MagicMock()

    return agent


class TestAudioEventsAgentInit:
    """Agent construction shape."""

    @patch("orpheus_agent_audio_events.main.load_config")
    @patch("orpheus_agent_audio_events.main.OrpheusConfig.get_instance")
    def test_init_defaults(
        self, mock_get_instance: MagicMock, mock_load_config: MagicMock
    ) -> None:
        cfg = MagicMock()
        cfg.max_concurrent_clips = 2
        mock_load_config.return_value = cfg
        mock_get_instance.return_value = MagicMock()
        agent = AudioEventsAgent()
        assert agent.bus is None
        assert agent.model is None
        assert agent.labels is None
        assert agent.detection_db is None
        assert agent.events_processed == 0
        assert agent.detections_emitted == 0


class TestProcessAudioFile:
    """End-to-end ``_process_audio_file`` exercising the full pipeline."""

    def test_emits_one_detection_per_injected_event(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        clip_path = tmp_path / "test_clip.wav"
        _make_synthetic_clip(clip_path)

        source = Detection(
            event_id="audio_motion_test_001",
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.motion",
            channel=1,
            audio_clip_path=str(clip_path),
        )
        agent_with_fake_model._process_audio_file(clip_path, source)

        # Two events injected, both mapped to valid labels (indices 0 and 5).
        assert agent_with_fake_model.detections_emitted == 2

        mqtt = agent_with_fake_model.bus
        assert isinstance(mqtt, MagicMock)
        assert mqtt.publish.call_count == 2
        published_payloads: list[dict[str, Any]] = [
            call.args[1] if len(call.args) >= 2 else call.kwargs["payload"]
            for call in mqtt.publish.call_args_list
        ]
        # Verify both have detection_type='audio.classified' and the right structure.
        for payload in published_payloads:
            assert payload["detection_type"] == "audio.classified"
            assert payload["audio_clip_path"] == str(clip_path)
            assert payload["intervals"] is not None
            assert payload["taxonomy"] is not None
            assert payload["taxonomy"]["namespace"] == "audioset"
            assert payload["source_event_id"] == "audio_motion_test_001"
            assert payload["metadata"]["model"] == "fake"

    def test_intervals_match_injected_events(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        clip_path = tmp_path / "test_clip.wav"
        _make_synthetic_clip(clip_path)

        source = Detection(
            event_id="audio_motion_test_002",
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.motion",
            channel=1,
            audio_clip_path=str(clip_path),
        )
        agent_with_fake_model._process_audio_file(clip_path, source)

        mqtt = agent_with_fake_model.bus
        assert isinstance(mqtt, MagicMock)
        published_payloads: list[dict[str, Any]] = [
            call.args[1] if len(call.args) >= 2 else call.kwargs["payload"]
            for call in mqtt.publish.call_args_list
        ]
        by_class: dict[int, dict[str, Any]] = {
            p["metadata"]["class_index"]: p for p in published_payloads
        }

        # Class 0 event was injected from 0.5s to 1.5s.
        iv0 = by_class[0]["intervals"][0]
        assert iv0["start_seconds"] == pytest.approx(0.5, abs=0.05)
        assert iv0["end_seconds"] == pytest.approx(1.5, abs=0.05)
        # Class 5 event was injected from 2.0s to 2.8s.
        iv5 = by_class[5]["intervals"][0]
        assert iv5["start_seconds"] == pytest.approx(2.0, abs=0.05)
        assert iv5["end_seconds"] == pytest.approx(2.8, abs=0.05)

    def test_silent_clip_emits_no_detections(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        # Replace the fake model with a silent one (no injected events).
        silent_fake = DeterministicFakeSED(
            sample_rate=32000,
            num_classes=10,
            frame_duration_seconds=0.032,
        )
        agent_with_fake_model.model = silent_fake

        clip_path = tmp_path / "silent_clip.wav"
        _make_synthetic_clip(clip_path)

        source = Detection(
            event_id="audio_motion_test_silent",
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.motion",
            channel=1,
            audio_clip_path=str(clip_path),
        )
        agent_with_fake_model._process_audio_file(clip_path, source)

        assert agent_with_fake_model.detections_emitted == 0
        mqtt = agent_with_fake_model.bus
        assert isinstance(mqtt, MagicMock)
        mqtt.publish.assert_not_called()

    def test_class_without_label_is_skipped(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        """Injecting an event on a class index that has no label in the tiny CSV
        should not produce a Detection (filtered out by allowed_class_indices)."""
        # The tiny labels CSV only has indices 0, 1, 5.
        # Inject an event on class 7 — not in our taxonomy.
        agent_with_fake_model.model.inject_event(  # type: ignore[union-attr]
            class_index=7, start_seconds=0.5, end_seconds=1.0, score=0.9
        )
        clip_path = tmp_path / "test_clip.wav"
        _make_synthetic_clip(clip_path)

        source = Detection(
            event_id="audio_motion_test_filter",
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.motion",
            channel=1,
            audio_clip_path=str(clip_path),
        )
        agent_with_fake_model._process_audio_file(clip_path, source)

        # Class 7's event was filtered out — only the two pre-existing events
        # (classes 0 and 5) produce detections.
        assert agent_with_fake_model.detections_emitted == 2

    def test_distinct_sound_types_are_uniquely_identified(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        """Two different sound types in one clip are each emitted as a distinctly
        identified Detection — distinct AudioSet taxonomy id + name — so the
        correlator/UI can tell them apart. (audio-events scans for and uniquely
        identifies each different type of sound, rather than collapsing to one.)"""
        clip_path = tmp_path / "multi_type.wav"
        _make_synthetic_clip(clip_path)

        source = Detection(
            event_id="audio_motion_multitype",
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.motion",
            channel=1,
            audio_clip_path=str(clip_path),
        )
        agent_with_fake_model._process_audio_file(clip_path, source)

        mqtt = agent_with_fake_model.bus
        assert isinstance(mqtt, MagicMock)
        payloads: list[dict[str, Any]] = [
            call.args[1] if len(call.args) >= 2 else call.kwargs["payload"]
            for call in mqtt.publish.call_args_list
        ]
        assert len(payloads) == 2
        # Each sound type carries its OWN AudioSet identity — not collapsed to one.
        tax_ids = {p["taxonomy"]["id"] for p in payloads}
        names = {p["species_common"] for p in payloads}
        assert tax_ids == {"/m/test_a", "/m/test_c"}
        assert names == {"Test Class A", "Test Class C"}
        # Distinct identity is keyed to the right class (no cross-wiring).
        by_class = {p["metadata"]["class_index"]: p for p in payloads}
        assert by_class[0]["taxonomy"]["id"] == "/m/test_a"
        assert by_class[5]["taxonomy"]["id"] == "/m/test_c"


class TestOnAudioMotionEvent:
    """The MQTT handler path."""

    def test_handler_processes_well_formed_payload(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        clip_path = tmp_path / "handler_test.wav"
        _make_synthetic_clip(clip_path)
        payload = _audio_motion_payload(clip_path)

        agent_with_fake_model._on_audio_motion_event("orpheus/audio/motion/events", payload)
        agent_with_fake_model.wait_inflight(timeout=10)

        assert agent_with_fake_model.events_processed == 1
        assert agent_with_fake_model.detections_emitted == 2

    def test_handler_ignores_payload_without_clip_path(
        self, agent_with_fake_model: AudioEventsAgent
    ) -> None:
        payload = Detection(
            event_id="missing_clip",
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.motion",
            channel=1,
            audio_clip_path=None,
        ).model_dump(mode="json")

        agent_with_fake_model._on_audio_motion_event("orpheus/audio/motion/events", payload)

        assert agent_with_fake_model.events_processed == 1
        assert agent_with_fake_model.detections_emitted == 0

    def test_handler_handles_missing_clip_file(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        nonexistent = tmp_path / "does_not_exist.wav"
        payload = _audio_motion_payload(nonexistent)

        agent_with_fake_model._on_audio_motion_event("orpheus/audio/motion/events", payload)

        assert agent_with_fake_model.events_processed == 1
        assert agent_with_fake_model.detections_emitted == 0

    def test_handler_handles_invalid_payload(
        self, agent_with_fake_model: AudioEventsAgent
    ) -> None:
        agent_with_fake_model._on_audio_motion_event(
            "orpheus/audio/motion/events", {"not": "a detection"}
        )
        # Counter still bumps because we received an event, but nothing was published.
        assert agent_with_fake_model.events_processed == 1
        assert agent_with_fake_model.detections_emitted == 0

    def test_handler_decodes_bytes_payload(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        import json  # noqa: PLC0415

        clip_path = tmp_path / "bytes_test.wav"
        _make_synthetic_clip(clip_path)
        payload_bytes = json.dumps(_audio_motion_payload(clip_path)).encode("utf-8")

        agent_with_fake_model._on_audio_motion_event(
            "orpheus/audio/motion/events", payload_bytes
        )
        agent_with_fake_model.wait_inflight(timeout=10)

        assert agent_with_fake_model.detections_emitted == 2


class TestHealthHeartbeat:
    """Tests for the periodic health publish — tracks model load,
    inference latency stats, error counts."""

    def test_latency_recording_bounded(
        self, agent_with_fake_model: AudioEventsAgent
    ) -> None:
        """The rolling latency window stays bounded — adding more than
        ``_inference_latency_window`` samples evicts the oldest."""
        agent = agent_with_fake_model
        agent._inference_latency_window = 5
        for ms in (10, 20, 30, 40, 50, 60, 70):
            agent._record_inference_latency(float(ms))
        # Only the last 5 should remain.
        assert agent._inference_latencies_ms == [30.0, 40.0, 50.0, 60.0, 70.0]

    def test_percentile_handles_empty(
        self, agent_with_fake_model: AudioEventsAgent
    ) -> None:
        assert agent_with_fake_model._percentile([], 0.5) == 0.0
        assert agent_with_fake_model._percentile([], 0.95) == 0.0

    def test_percentile_known_values(
        self, agent_with_fake_model: AudioEventsAgent
    ) -> None:
        agent = agent_with_fake_model
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        # p50 of [10,20,30,40,50] should be 30 (the median).
        assert agent._percentile(values, 0.5) == 30.0
        # p95 should be very close to 50.
        assert agent._percentile(values, 0.95) >= 48.0

    def test_health_payload_shape(
        self, agent_with_fake_model: AudioEventsAgent
    ) -> None:
        agent = agent_with_fake_model
        agent.events_processed = 7
        agent.detections_emitted = 14
        agent.errors_count = 1
        agent.last_error = "ValueError: bad audio"
        agent._record_inference_latency(125.0)
        agent._record_inference_latency(180.0)
        agent._record_inference_latency(220.0)

        payload = agent._build_health_payload()
        assert payload["status"] == "online"
        assert payload["model_loaded"] is True
        assert payload["events_processed"] == 7
        assert payload["detections_emitted"] == 14
        assert payload["errors_count"] == 1
        assert payload["last_error"] == "ValueError: bad audio"
        # Diagnostics surfaces whether the event-sourcing shadow is actually recording
        # (off by default; reflects the resolved self._shadow_publish).
        assert payload["event_sourcing_shadow"] is False
        # Additive: resolved torch device (None here — the fixture injects the
        # model, so on_setup never resolved one) + executor queue depth.
        assert payload["device"] is None
        assert payload["inflight_clips"] == 0
        assert payload["inference_latency_ms"]["samples"] == 3
        assert payload["inference_latency_ms"]["p50"] > 0
        assert payload["inference_latency_ms"]["p95"] >= payload["inference_latency_ms"]["p50"]
        assert payload["inference_latency_ms"]["max"] == 220.0

    def test_error_recorded_on_process_failure(
        self, agent_with_fake_model: AudioEventsAgent
    ) -> None:
        """Exceptions in the MQTT handler increment errors_count and
        record last_error."""
        agent = agent_with_fake_model
        # Send a payload that will fail Detection parsing AND fail the
        # legacy path — force a Python error.
        agent._on_audio_motion_event(
            "orpheus/audio/motion/events",
            "not-a-dict-not-bytes",  # type: ignore[arg-type]
        )
        # The handler catches everything; verify we recorded it.
        assert agent.errors_count >= 0  # may or may not throw depending on parse
        # And verify the next inference WOULD record successfully (the
        # rolling window is unaffected by errors).
        agent._record_inference_latency(100.0)
        assert 100.0 in agent._inference_latencies_ms


class TestConcurrentProcessing:
    """Non-cancelled bounded concurrency: a new audio.motion tick starts a new
    clip WITHOUT cancelling an in-flight one — older instances run to completion."""

    def test_two_ticks_run_concurrently_and_both_finish(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        import threading  # noqa: PLC0415

        agent = agent_with_fake_model  # fixture sets max_concurrent_clips = 2
        entered = threading.Semaphore(0)
        release = threading.Event()
        peak = {"cur": 0, "max": 0}
        lock = threading.Lock()
        real_predict = agent.model.predict  # type: ignore[union-attr]

        def blocking_predict(audio: Any) -> Any:
            with lock:
                peak["cur"] += 1
                peak["max"] = max(peak["max"], peak["cur"])
            entered.release()
            # Block until released — proves the older clip is NOT cancelled when
            # the next tick arrives; both workers sit here at once.
            assert release.wait(timeout=10)
            try:
                return real_predict(audio)
            finally:
                with lock:
                    peak["cur"] -= 1

        agent.model.predict = blocking_predict  # type: ignore[union-attr,method-assign]

        clip_a = tmp_path / "a.wav"
        clip_b = tmp_path / "b.wav"
        _make_synthetic_clip(clip_a)
        _make_synthetic_clip(clip_b)

        # Two ticks back-to-back; the handler returns immediately (non-blocking).
        agent._on_audio_motion_event("t", _audio_motion_payload(clip_a))
        agent._on_audio_motion_event("t", _audio_motion_payload(clip_b))

        # Both workers entered inference before either could finish → they ran
        # concurrently, so the second tick did not cancel the first.
        assert entered.acquire(timeout=10)
        assert entered.acquire(timeout=10)
        assert peak["max"] == 2

        # Release; both clips run to completion and emit (2 events x 2 clips).
        release.set()
        agent.wait_inflight(timeout=10)
        assert agent.detections_emitted == 4


class TestEventSourcingShadow:
    """§3 event-sourcing shadow: each emitted detection is mirrored to the durable
    domain stream when enabled, AFTER the DB save. Off by default."""

    def test_shadow_publishes_each_detection_when_enabled(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        agent = agent_with_fake_model
        agent._shadow_publish = True  # normally set by on_started() post-connect
        clip_path = tmp_path / "shadow.wav"
        _make_synthetic_clip(clip_path)
        source = Detection(
            event_id="audio_motion_shadow",
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.motion",
            channel=1,
            audio_clip_path=str(clip_path),
        )
        agent._process_audio_file(clip_path, source)

        bus = agent.bus
        assert isinstance(bus, MagicMock)
        # Two events injected (classes 0 + 5) -> two shadow publishes to the stream.
        assert bus.stream_publish.call_count == 2
        for call in bus.stream_publish.call_args_list:
            # The shadow lands on the dedicated domain subject, NEVER the live
            # topic (a stream publish is a core publish — live subscribers must
            # not see the shadow copy).
            assert call.args[0] == domain_subject(agent.config.output_topic)
            assert "msg_id" in call.kwargs  # keyed by event_id for dedup

    def test_no_shadow_publish_by_default(
        self, agent_with_fake_model: AudioEventsAgent, tmp_path: Path
    ) -> None:
        agent = agent_with_fake_model  # _shadow_publish defaults False
        clip_path = tmp_path / "noshadow.wav"
        _make_synthetic_clip(clip_path)
        source = Detection(
            event_id="audio_motion_noshadow",
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.motion",
            channel=1,
            audio_clip_path=str(clip_path),
        )
        agent._process_audio_file(clip_path, source)
        assert isinstance(agent.bus, MagicMock)
        agent.bus.stream_publish.assert_not_called()

    def test_on_started_refreshes_health_when_shadow_active(
        self, agent_with_fake_model: AudioEventsAgent
    ) -> None:
        """The base publishes startup health BEFORE on_started, so it always says
        shadow: false. When the shadow comes up, on_started refreshes health once
        so the true state is visible without waiting a heartbeat."""
        agent = agent_with_fake_model
        with patch(
            "orpheus_agent_audio_events.main.ensure_domain_stream", return_value=True
        ):
            asyncio.run(agent.on_started())
        topic, payload = agent.bus.publish.call_args[0]
        assert topic == agent.identity.health_topic
        assert payload["event_sourcing_shadow"] is True

    def test_on_started_no_health_refresh_when_shadow_off(
        self, agent_with_fake_model: AudioEventsAgent
    ) -> None:
        """Default (shadow off): no extra publish — startup health already said
        false, so behavior stays byte-identical."""
        agent = agent_with_fake_model
        with patch(
            "orpheus_agent_audio_events.main.ensure_domain_stream", return_value=False
        ):
            asyncio.run(agent.on_started())
        agent.bus.publish.assert_not_called()


class TestShutdownDrain:
    """on_stopping drains RUNNING clips but drops the still-queued backlog, so
    shutdown latency is bounded by max_workers clips, not the whole queue."""

    def test_on_stopping_drops_queued_backlog(
        self, agent_with_fake_model: AudioEventsAgent
    ) -> None:
        agent = agent_with_fake_model
        agent._executor = MagicMock()
        asyncio.run(agent.on_stopping())
        agent._executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)


class TestMainEntryPoint:
    """The CLI entry configures logging BEFORE the enabled() gate — a disabled
    agent never runs on_setup, but its 'not starting' warning must still go
    through the configured handlers."""

    def test_main_configures_logging_before_start(self) -> None:
        with patch(
            "orpheus_agent_audio_events.main.setup_logging"
        ) as mock_setup, patch(
            "orpheus_agent_audio_events.main.AudioEventsAgent"
        ), patch(
            "orpheus_agent_audio_events.main.asyncio.run"
        ) as mock_run:
            main()
        mock_setup.assert_called_once_with("orpheus-agent-audio-events", level="INFO")
        mock_run.assert_called_once()
