"""Main entry point for crow detection agent."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import soundfile as sf
from orpheus_common import DetectionDB, OrpheusConfig
from orpheus_common.actor import Actor
from orpheus_common.detection import Detection, TemporalInterval
from orpheus_common.event_sourcing import ensure_domain_stream, shadow_publish
from orpheus_common.logging import get_logger, setup_logging
from pydantic import ValidationError

from .classifier import CrowClassifier, CrowDetectionResult
from .config import load_config
from .embedder import AVESEmbedder

logger = get_logger(__name__)


class CrowDetectionAgent(Actor):
    """Crow detection agent using crow-tools models.

    Lifecycle (bus connect/subscribe, signal handling, heartbeat, graceful
    shutdown) comes from ``Actor``; this fills the crow-specific hooks. ``self.bus``
    is the EventBus, ``self.config`` the crow config (the OrpheusConfig is
    ``self.orpheus_config``, set by the base)."""

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize crow detection agent."""
        self.config = load_config(config_path)
        super().__init__(
            "crow-detection",
            OrpheusConfig.get_instance(config_path=config_path),
        )

        self.embedder: AVESEmbedder | None = None
        self.classifier: CrowClassifier | None = None
        self.detection_db: DetectionDB | None = None

        # Event-sourcing shadow (off by default; nats-only; best-effort). When
        # enabled, each saved detection is also mirrored to the durable domain
        # stream keyed by event_id. Ensured in on_started (after bus connect).
        self._shadow_publish = False

        # Resolved torch device ("cuda"/"cpu"), captured from the loaded embedder
        # in on_setup. Surfaced in health so a silent CPU fallback on the Jetson
        # is visible beyond one startup log line. None until models load.
        self._resolved_device: str | None = None

        # Statistics (crow-specific; the common trio could move to ActorStats later)
        self.events_processed = 0
        self.detections_found = 0
        # Error tracking — surfaced via health publishes so the UI's
        # cross-agent error feed catches failures here too.
        self.errors_count = 0
        self.last_error: str | None = None

        # Dedup: clip_path → last_processed_timestamp. Prevents running
        # AVES + classifier twice on the same clip when both BirdNET and
        # PANNs flag a corvid in it.
        self._recently_processed_clips: dict[str, float] = {}
        # Window over which a clip is considered "recently processed".
        # Tuned to be longer than typical processing latency but shorter
        # than the cluster window so we don't drop legitimate re-processing
        # of a clip in a much later acoustic event.
        self._dedup_window_seconds = 30.0

    def _evict_stale_processed_clips(self) -> None:
        """Remove dedup entries older than ``_dedup_window_seconds``.

        Called from both the check and the mark paths so the dict can't
        grow unboundedly if one path is never exercised (e.g. a
        deployment without orpheus-agent-audio-events running).
        """
        now = time.monotonic()
        stale = [
            k for k, v in self._recently_processed_clips.items()
            if now - v > self._dedup_window_seconds
        ]
        for k in stale:
            del self._recently_processed_clips[k]

    def _is_recently_processed(self, clip_path: str) -> bool:
        """Has this clip been crow-analyzed in the last
        ``_dedup_window_seconds``?"""
        self._evict_stale_processed_clips()
        return clip_path in self._recently_processed_clips

    def _mark_processed(self, clip_path: str) -> None:
        self._evict_stale_processed_clips()
        self._recently_processed_clips[clip_path] = time.monotonic()

    def enabled(self) -> bool:
        return self.config.enabled

    async def on_setup(self) -> None:
        """Load the AVES embedder + crow classifier + the detection DB."""
        logger.info("Starting Crow Detection Agent")

        logger.info(
            "Loading AVES embedder",
            model_path=str(self.config.embedder_model_path),
            sample_rate=self.config.embedder_sample_rate,
        )
        try:
            self.embedder = AVESEmbedder(
                self.config.embedder_model_path,
                sample_rate=self.config.embedder_sample_rate,
                device=self.config.device,
            )
            # The embedder resolved "auto" via select_torch_device — capture the
            # ACTUAL device (not the requested one) for the health payload.
            self._resolved_device = str(self.embedder.device)
            logger.info("AVES embedder loaded successfully", device=self._resolved_device)
        except FileNotFoundError:
            logger.error(  # noqa: TRY400
                "Embedder model file not found",
                path=str(self.config.embedder_model_path),
            )
            logger.info("Place AVES model at specified path or update config")
            raise

        logger.info("Loading crow classifier", model_path=str(self.config.classifier_model_path))
        try:
            self.classifier = CrowClassifier(
                self.config.classifier_model_path, device=self.config.device
            )
            logger.info("Crow classifier loaded successfully")
        except FileNotFoundError:
            logger.error(  # noqa: TRY400
                "Classifier model file not found",
                path=str(self.config.classifier_model_path),
            )
            logger.info("Place classifier model at specified path or update config")
            raise

        self.detection_db = DetectionDB()
        logger.info("DetectionDB initialized")

    async def on_started(self) -> None:
        """Ensure the durable domain stream once the bus is connected (the base
        calls this AFTER connect; on_setup runs too early). Off by default."""
        self._shadow_publish = ensure_domain_stream(self.bus, self.orpheus_config)
        # The base publishes the startup health BEFORE on_started runs, so that
        # payload always said event_sourcing_shadow: false. When the shadow did
        # come up, refresh health once so the true state is visible immediately
        # instead of a heartbeat later (additive re-publish, same startup shape).
        if self._shadow_publish and self.bus is not None:
            if self._health_on_bus:
                self.bus.publish(self.identity.health_topic, self.health_payload("startup"))
            self._health_kv_publish(self.health_payload("startup"), "startup")

    def subscriptions(self) -> list[tuple[str, Any]]:
        # Bird species.detected (corvid filtering) + audio-events AudioSet corvid
        # tags ("Crow"/"Caw") — cross-classifier identity picks up corvid signals
        # from ANY classifier, deduped by clip_path so AVES doesn't run twice on
        # the same clip in a short window.
        return [
            ("orpheus/detection/bird/events", self._on_bird_detection_event),
            ("orpheus/detection/audio/events", self._on_audio_events_event),
        ]

    def health_payload(self, phase: str) -> dict[str, Any]:
        # Per-phase shapes preserved exactly (the e2e oracle pins them): startup
        # announces models_loaded; the heartbeat omits it; shutdown is a subset.
        now = datetime.now(timezone.utc).isoformat()
        if phase == "startup":
            return {
                "status": "online",
                "models_loaded": True,
                "timestamp": now,
                "events_processed": self.events_processed,
                "detections_found": self.detections_found,
                "errors_count": self.errors_count,
                "last_error": self.last_error,
                "event_sourcing_shadow": self._shadow_publish,
                # Resolved torch device (additive; None until models load).
                "device": self._resolved_device,
            }
        if phase == "shutdown":
            return {
                "status": "offline",
                "events_processed": self.events_processed,
                "detections_found": self.detections_found,
                "timestamp": now,
            }
        return {
            "status": "online",
            "timestamp": now,
            "events_processed": self.events_processed,
            "detections_found": self.detections_found,
            "errors_count": self.errors_count,
            "last_error": self.last_error,
            # Whether the event-sourcing shadow is actually recording (off by default).
            "event_sourcing_shadow": self._shadow_publish,
            # Resolved torch device (additive; None until models load).
            "device": self._resolved_device,
        }

    async def on_shutdown(self) -> None:
        logger.info(
            "Agent shutdown complete",
            events_processed=self.events_processed,
            crow_detections=self.detections_found,
        )

    def _on_bird_detection_event(self, _topic: str, payload: dict[str, Any]) -> None:
        """
        Handle bird detection event from MQTT.

        Only processes events where corvids (crows/ravens) were detected.
        Supports both V2 Pydantic payloads (with metadata.detections) and
        legacy payloads (with top-level detections).

        Args:
            _topic: MQTT topic (unused, prefixed with underscore)
            payload: Bird detection event payload
        """
        self.events_processed += 1

        if isinstance(payload, bytes):
            try:
                payload = json.loads(payload.decode("utf-8"))
            except Exception:
                logger.error("Failed to decode MQTT payload", exc_info=True)
                return

        try:
            # Parse using Pydantic Detection model for V2 schema compliance
            source_detection = None
            try:
                source_detection = Detection.model_validate(payload)
            except ValidationError:
                # Known: payload doesn't conform to V2 schema. Fall
                # back to raw dict for legacy publishers.
                logger.debug(
                    "Payload did not match V2 Detection schema, using legacy parsing"
                )
            except Exception as e:
                # Unknown: pydantic internals, TypeError, etc. Surface
                # the actual type so a real bug isn't silently routed
                # into the legacy path.
                logger.exception(
                    "Unexpected error parsing V2 Detection; falling back to legacy",
                    error_type=type(e).__name__,
                    error=str(e),
                )

            if source_detection is not None:
                event_id = source_detection.event_id
                audio_clip_path = source_detection.audio_clip_path
                # V2 payload: detections are nested under metadata
                detections = source_detection.metadata.get("detections", [])
                source_context = source_detection.context
                channel = source_detection.channel
            else:
                event_id = payload.get("event_id")
                audio_clip_path = payload.get("audio_clip_path")
                # Legacy: detections at top level
                detections = payload.get("detections", [])
                source_context = None
                channel = payload.get("channel")

            logger.info(
                "Received bird detection event",
                event_id=event_id,
                num_detections=len(detections),
            )

            if not audio_clip_path:
                logger.warning("Bird detection event missing audio_clip_path", event_id=event_id)
                return

            # Check if any detections are corvids
            corvid_detections = [d for d in detections if d.get("is_corvid", False)]

            if not corvid_detections:
                logger.debug(
                    "No corvid detections in event, skipping crow analysis",
                    event_id=event_id,
                    species=[d.get("species_code") for d in detections],
                )
                return

            logger.info(
                "Corvid detected, running crow-specific analysis",
                event_id=event_id,
                corvid_species=[d.get("species_code") for d in corvid_detections],
            )

            audio_path = Path(audio_clip_path)
            if not audio_path.exists():
                logger.error("Audio file not found", path=str(audio_path), event_id=event_id)
                return

            # Dedup: if audio-events already triggered us on this clip
            # very recently, skip — same guard as ``_on_audio_events_event``.
            # Without this, when audio-events fires before BirdNET on the
            # same clip, both handlers run AVES on it.
            if self._is_recently_processed(str(audio_path)):
                logger.debug(
                    "Clip already crow-analyzed, skipping",
                    event_id=event_id,
                    clip_path=str(audio_path),
                )
                return

            # Build source event dict for downstream processing.
            # Pass along the per-window intervals from BirdNET for the corvid
            # species — these become the emitted crow.analyzed Detection's
            # intervals (ADR 0011 §4.5 — propagate localisation).
            # root_event_id traces back to the originating audio.motion
            # event so downstream consumers can answer "which physical
            # event is this about?" in O(1). Use the canonical helper
            # so this handler agrees with ``_on_audio_events_event``
            # (line ~484); a manual chain that diverges between the
            # two handlers would let the same physical audio.motion
            # event produce crow.analyzed Detections with mismatched
            # roots, breaking Layer-2 clustering by root.
            root_event_id = (
                Detection.derive_root_event_id(source_detection)
                if source_detection is not None
                else event_id
            )
            source_event = {
                "event_id": event_id,
                "channel_id": str(channel) if channel is not None else "unknown",
                "context": source_context,
                "corvid_detections": corvid_detections,
                "root_event_id": root_event_id,
            }

            # Process the audio file for crow-specific detection.
            # Mark the clip as processed so the audio-events handler
            # (which may also fire for the same clip) skips it.
            self._mark_processed(str(audio_path))
            self._process_audio_file(audio_path, source_event)

        except Exception as e:
            self.errors_count += 1
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            logger.error(
                "Error processing bird detection event",
                event_id=payload.get("event_id"),
                error=str(e),
                exc_info=True,
            )

    # AudioSet machine_ids that are corvid-related — when audio-events
    # (PANNs) fires one of these, we treat it as a corvid signal and run
    # crow-tools on the clip. AudioSet's "Crow" + "Caw" — the only mids
    # currently in the AudioSet ontology that map to corvid calls. We
    # could extend via taxonomy_equivalence in the future.
    # Verified against the canonical 527-class PANNs CSV bundled in
    # agents/orpheus-agent-audio-events. Don't guess mids — look them up.
    CORVID_AUDIOSET_MIDS: frozenset = frozenset(
        {
            "/m/04s8yn",   # 117: Crow
            "/m/07r5c2p",  # 118: Caw  (was /m/030d6h which doesn't exist)
        }
    )

    def _on_audio_events_event(self, _topic: str, payload: dict[str, Any]) -> None:
        """Handle audio-events Detections (PANNs SED) for corvid signals.

        Cross-classifier identity: when PANNs flags a clip with the
        AudioSet "Crow" or "Caw" tag, we kick off crow-tools just like
        we would for a BirdNET corvid hit. Deduped by clip_path so we
        don't double-process when BirdNET ALSO fires on the same clip.

        crow.analyzed Detections emitted by this path have their
        source_event_id pointing at the audio.classified event, but
        their root_event_id traces back through the source chain to
        the audio.motion at the root — same physical event identity.
        """
        self.events_processed += 1

        if isinstance(payload, bytes):
            try:
                payload = json.loads(payload.decode("utf-8"))
            except Exception:
                logger.error("Failed to decode MQTT payload", exc_info=True)
                return

        try:
            source_detection = None
            try:
                source_detection = Detection.model_validate(payload)
            except ValidationError:
                logger.debug("audio.classified payload didn't match V2 Detection")
            except Exception as e:
                logger.exception(
                    "Unexpected error parsing audio.classified payload; ignoring",
                    error_type=type(e).__name__,
                    error=str(e),
                )

            if source_detection is None:
                return

            tax = source_detection.taxonomy
            if (
                tax is None
                or tax.namespace != "audioset"
                or tax.id not in self.CORVID_AUDIOSET_MIDS
            ):
                # Not a corvid signal — ignore.
                return

            audio_clip_path = source_detection.audio_clip_path
            if not audio_clip_path:
                logger.warning(
                    "audio.classified corvid event missing clip path",
                    event_id=source_detection.event_id,
                )
                return

            # Dedup: if BirdNET already triggered us on this clip very
            # recently, skip.
            if self._is_recently_processed(audio_clip_path):
                logger.debug(
                    "Clip already crow-analyzed, skipping",
                    event_id=source_detection.event_id,
                    clip_path=audio_clip_path,
                )
                return

            audio_path = Path(audio_clip_path)
            if not audio_path.exists():
                logger.error(
                    "Audio file not found",
                    path=str(audio_path),
                    event_id=source_detection.event_id,
                )
                return

            logger.info(
                "audio-events corvid signal — running crow analysis",
                event_id=source_detection.event_id,
                audioset_id=tax.id,
                audioset_label=tax.common_name,
                clip_path=Path(audio_clip_path).name,
            )

            channel = source_detection.channel
            root_event_id = (
                Detection.derive_root_event_id(source_detection)
                or source_detection.event_id
            )
            # Synthesise a source_event with just enough info for
            # _process_audio_file. The "corvid_detections" list lets the
            # downstream code reuse the same path as BirdNET-driven
            # crow analysis; we synthesize a single corvid_detection
            # carrying the AudioSet ref so intervals/taxonomy propagate.
            corvid_detection = {
                "species_code": f"audioset_{tax.id}",
                "species_common": tax.common_name or "Crow",
                "confidence": source_detection.confidence or 0.0,
                "is_corvid": True,
                "_source": "audio_events",
                # Intervals from PANNs (frame-level) carry through.
                "windows": [
                    {
                        "start_time": iv.start_seconds,
                        "end_time": iv.end_seconds,
                        "confidence": iv.confidence or 0.0,
                    }
                    for iv in (source_detection.intervals or [])
                ],
            }
            source_event = {
                "event_id": source_detection.event_id,
                "channel_id": str(channel) if channel is not None else "unknown",
                "context": source_detection.context,
                "corvid_detections": [corvid_detection],
                "root_event_id": root_event_id,
            }

            self._mark_processed(audio_clip_path)
            self._process_audio_file(audio_path, source_event)
        except Exception as e:
            self.errors_count += 1
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            logger.error(
                "Error processing audio-events corvid signal",
                event_id=payload.get("event_id"),
                error=str(e),
                exc_info=True,
            )

    def _load_and_preprocess(self, audio_path: Path) -> np.ndarray | None:
        """Load audio file and resample to expected rate."""
        try:
            audio, sample_rate = sf.read(audio_path)
        except Exception:
            logger.exception("Failed to load audio file", path=str(audio_path))
            return None

        # Convert to mono if stereo
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)

        # Resample for embedder (16kHz)
        if sample_rate != self.config.embedder_sample_rate:
            audio = librosa.resample(
                audio,
                orig_sr=sample_rate,
                target_sr=self.config.embedder_sample_rate,
                res_type="kaiser_fast",
            )

        return audio

    def _scan_audio(self, audio: np.ndarray) -> CrowDetectionResult:
        """Scan audio using sliding windows to find best crow detection."""
        if not self.embedder or not self.classifier:
            logger.error("Models not initialized")
            return CrowDetectionResult(
                is_crow=False, quality_score=0.0, species="unknown", call_type=None, attributes={}
            )

        # Window settings: 3.0 seconds width, 1.5 second stride
        # AVES works well with 3-5s chunks
        window_samples = int(3.0 * self.config.embedder_sample_rate)
        stride_samples = int(1.5 * self.config.embedder_sample_rate)

        # Prepare list of windows
        if len(audio) <= window_samples:
            windows = [audio]
        else:
            windows = []
            for i in range(0, len(audio) - window_samples + 1, stride_samples):
                windows.append(audio[i : i + window_samples])
            # Capture the tail if significant
            if len(audio) > window_samples and (len(audio) - window_samples) % stride_samples != 0:
                windows.append(audio[-window_samples:])

        best_result = None
        best_score = -1.0

        for window in windows:
            if len(window) == 0:
                continue

            # Normalize window (Zero Mean, Unit Variance)
            mean = np.mean(window)
            std = np.std(window)
            if std == 0:
                continue
            norm_window = (window - mean) / std

            try:
                # Ensure float32 for model
                embedding = self.embedder.generate_embedding(norm_window.astype(np.float32))
                result = self.classifier.classify(embedding, self.config.quality_threshold)

                if result.quality_score > best_score:
                    best_score = result.quality_score
                    best_result = result
                    # Optimization: stop early on high confidence
                    if best_score > 0.95:
                        break
            except Exception as e:
                logger.warning(f"Window processing failed: {e}")
                continue

        if best_result:
            return best_result

        # Fallback if no valid windows
        return CrowDetectionResult(
            is_crow=False, quality_score=0.0, species="unknown", call_type=None, attributes={}
        )

    def _process_audio_file(self, audio_path: Path, source_event: dict[str, Any]) -> None:
        """
        Process audio file for crow detection.
        """
        start_time = time.time()
        logger.debug("Loading audio for crow analysis", path=str(audio_path))

        # 1. Load and Preprocess
        audio_data = self._load_and_preprocess(audio_path)
        if audio_data is None:
            return

        # 2. Scan audio (Sliding Window + Classification)
        result = self._scan_audio(audio_data)
        inference_time_ms = int((time.time() - start_time) * 1000)

        # 3. Publish and Store
        event_id = self._generate_event_id(source_event.get("channel_id", "unknown"))

        # Only increment "detections found" if it actually passes the threshold
        if result.is_crow:
            self.detections_found += 1

        # Build metadata with inference results and attributes
        metadata: dict[str, Any] = {
            "call_type": result.call_type,
            "confirmed_crow": result.is_crow,
            "quality_score": float(result.quality_score),
            "attributes": result.attributes,
            "channel_id": source_event.get("channel_id"),
            "inference_time_ms": inference_time_ms,
        }

        # Only include full/raw results for debugging failed confirmations
        if not result.is_crow:
            metadata["debug_results"] = asdict(result)

        source_context = source_event.get("context")
        species_common = "Crow" if result.is_crow else None

        # Propagate BirdNET's per-window intervals for the corvid species into
        # the emitted Detection (ADR 0011 §4.5). Collect intervals across all
        # corvid_detections passed in by the bird-detection event.
        intervals = self._intervals_from_corvid_detections(
            source_event.get("corvid_detections", [])
        )

        # NOTE on cross-classifier identity (Layer 1):
        # crow-tools deliberately does NOT populate Detection.taxonomy. It is
        # a call-type analyzer (alert / contact / territory / age / quality)
        # on top of an upstream corvid detection — its species field is
        # binary ("crow"/"unknown"), not a species-level claim. The actual
        # species identity (American Crow vs Common Raven vs Fish Crow)
        # lives on the upstream species.detected event from BirdNET, which
        # under Layer 2 event-based clustering will appear as sibling
        # evidence on the same Entity. See
        # docs/designs/cross-classifier-identity.md §3 for rationale.
        detection = Detection(
            event_id=event_id,
            timestamp=datetime.now(timezone.utc),
            detection_type="crow.analyzed",
            species_code=result.species,
            species_common=species_common,
            confidence=result.quality_score,
            audio_clip_path=str(audio_path),
            context=source_context,
            source_event_id=source_event.get("event_id"),
            # Chain root — the audio.motion event that started this chain.
            # See docs/designs/cross-classifier-identity.md §1.1.
            root_event_id=source_event.get("root_event_id"),
            intervals=intervals if intervals else None,
            taxonomy=None,  # see NOTE above — deliberate
            metadata=metadata,
        )

        # Restoring your custom logging format exactly as requested
        logger.info(
            "Crow analysis complete",
            result=result,
            event_id=event_id,
            confirmed=result.is_crow,
            quality=f"{result.quality_score:.2f}",
            call_type=result.call_type,
        )

        # Publish to the bus using the standardised Detection model
        if self.bus:
            self.bus.publish(
                "orpheus/detection/crow/events",
                detection.model_dump(mode="json"),
            )
        else:
            logger.error("MQTT client not initialized, cannot publish detection event")

        # Store in DetectionDB
        if self.detection_db is None:
            logger.error("DetectionDB not initialized, cannot store detection")
            return

        self.detection_db.save(detection)

        # Event-sourcing shadow: mirror to the durable domain stream keyed by
        # event_id (best-effort; off by default; never raises). After the save.
        if self._shadow_publish:
            shadow_publish(self.bus, "orpheus/detection/crow/events", detection)

    def _generate_event_id(self, channel_id: str) -> str:
        """Generate unique event ID."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"crow_det_{timestamp}_ch{channel_id}_{self.detections_found:03d}"

    @staticmethod
    def _intervals_from_corvid_detections(
        corvid_detections: list[dict[str, Any]],
    ) -> list[TemporalInterval]:
        """Build a list of TemporalIntervals from the corvid_detections passed
        in by the bird-detection event.

        Reads each corvid_detection's ``windows`` list when present (from
        BirdNET's sliding-window output), falling back to a single
        ``start_time``/``end_time`` span when only legacy single-window data
        is available. Returns an empty list when no temporal data is present
        at all — caller should pass ``None`` rather than ``[]`` in that case
        so the emitted Detection has ``intervals=None`` (i.e. no localisation).
        """
        intervals: list[TemporalInterval] = []
        for det in corvid_detections:
            windows = det.get("windows")
            if windows:
                for w in windows:
                    if "start_time" not in w or "end_time" not in w:
                        continue
                    # NB: `float(x) or None` would silently collapse a
                    # legitimate 0.0 confidence to None. Use explicit
                    # None check so "zero confidence" survives intact.
                    raw_conf = w.get("confidence")
                    intervals.append(
                        TemporalInterval(
                            start_seconds=float(w["start_time"]),
                            end_seconds=float(w["end_time"]),
                            confidence=float(raw_conf) if raw_conf is not None else None,
                        )
                    )
            elif "start_time" in det and "end_time" in det:
                raw_conf = det.get("confidence")
                intervals.append(
                    TemporalInterval(
                        start_seconds=float(det["start_time"]),
                        end_seconds=float(det["end_time"]),
                        confidence=float(raw_conf) if raw_conf is not None else None,
                    )
                )
        intervals.sort(key=lambda i: i.start_seconds)
        return intervals


def main() -> None:
    """Main entry point."""
    # Configure logging BEFORE the Actor's enabled() gate: a disabled agent never
    # runs on_setup, but its "disabled in configuration; not starting" warning
    # must still go through the configured handlers.
    setup_logging("orpheus-agent-crow-detection", level="INFO")
    agent = CrowDetectionAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
