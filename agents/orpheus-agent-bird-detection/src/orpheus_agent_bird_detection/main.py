"""Main entry point for bird detection agent."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from math import gcd
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf
from orpheus_common import DetectionDB, OrpheusConfig
from orpheus_common.actor import Actor
from orpheus_common.detection import Detection, TemporalInterval
from orpheus_common.detection.species import is_corvid
from orpheus_common.event_sourcing import ensure_domain_stream, shadow_publish
from orpheus_common.events import SpatiotemporalContext
from orpheus_common.logging import get_logger, setup_logging
from pydantic import ValidationError
from scipy.signal import resample_poly

from .birdnet import CORVID_SPECIES, BirdNETModel  # noqa: F401 — keep export for back-compat
from .config import load_config
from .taxonomy_mapping import parts_to_taxonomy_ref

logger = get_logger(__name__)


class BirdDetectionAgent(Actor):
    """Bird detection agent using BirdNET.

    Lifecycle comes from ``Actor``; this fills the hooks. ``self.bus`` is the
    EventBus; ``self.config`` the bird config (OrpheusConfig is
    ``self.orpheus_config``, set by the base)."""

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize bird detection agent."""
        orpheus_config = OrpheusConfig.get_instance(config_path=config_path)
        self.config = load_config(orpheus_config)
        super().__init__("bird-detection", orpheus_config)

        self.model: BirdNETModel | None = None
        self.detection_db: DetectionDB | None = None

        # §3 event-sourcing shadow: ensured at startup (on_started, post-connect).
        # Off by default; no-op on mqtt. Gates whether each persisted detection is
        # mirrored to the durable domain stream. The DB stays the source of truth.
        self._shadow_publish = False

        # Statistics (crow/bird keep their own; the common trio could move to
        # ActorStats later).
        self.events_processed = 0
        self.detections_found = 0
        # Error tracking — surfaced via health publishes so the UI
        # error feed catches failures across the system.
        self.errors_count = 0
        self.last_error: str | None = None

    async def on_setup(self) -> None:
        """Load the BirdNET model + open the detection DB."""
        setup_logging("orpheus-agent-bird-detection", level="INFO")
        logger.info("Starting Bird Detection Agent")

        logger.info("Loading BirdNET model", model_path=self.config.model_path)
        try:
            self.model = BirdNETModel(
                self.config.model_path,
                geo_filter_min_prob=self.config.geo_filter_min_prob,
                geo_filter_weak_admit_prob=self.config.geo_filter_weak_admit_prob,
                geo_filter_weak_admit_conf=self.config.geo_filter_weak_admit_conf,
                site_species_whitelist=self.config.site_species_whitelist,
            )
        except FileNotFoundError:
            logger.exception("Model file not found", model_path=self.config.model_path)
            logger.info(
                "Fetch the model with: make -C agents/orpheus-agent-bird-detection "
                "download-models (or `git lfs pull` if you have the repo's artifacts)"
            )
            raise
        except Exception as e:
            logger.exception("Failed to load BirdNET model", error=str(e))
            raise

        self.detection_db = DetectionDB()
        logger.info("DetectionDB initialized")

    async def on_started(self) -> None:
        """Post-connect: ensure the bounded durable domain stream once (shared helper).
        Off by default; no-op on mqtt. Returns whether to shadow-publish each persisted
        bird detection to the stream — the DB stays the source of truth."""
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
        return [("orpheus/audio/motion/events", self._on_audio_motion_event)]

    def health_payload(self, phase: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        if phase == "shutdown":
            return {"status": "offline", "timestamp": now}
        # startup announces models loaded; the heartbeat reports live model state —
        # both INCLUDE model_loaded (bird's shape; the inverse of crow's heartbeat).
        return {
            "status": "online",
            "model_loaded": True if phase == "startup" else self.model is not None,
            "timestamp": now,
            "events_processed": self.events_processed,
            "detections_found": self.detections_found,
            "errors_count": self.errors_count,
            "last_error": self.last_error,
            # Whether the event-sourcing shadow is actually recording (off by default;
            # a silent self-disable on mqtt / stream_ensure error is otherwise invisible).
            "event_sourcing_shadow": self._shadow_publish,
        }

    async def on_shutdown(self) -> None:
        logger.info(
            "Processed %d events, found %d detections",
            self.events_processed,
            self.detections_found,
        )

    def _on_audio_motion_event(self, _topic: str, payload: dict[str, Any]) -> None:
        """Handle audio motion event."""
        # Initialise upfront so the outer ``except`` log handler can
        # reference these names even if construction below raises before
        # they're bound. Otherwise an unrelated exception (e.g. bytes
        # payload, AttributeError) gets masked by an UnboundLocalError
        # in the error handler itself.
        source_event_id: Optional[str] = None
        source_detection: Optional[Detection] = None
        clip_path: Optional[str] = None
        channel_id: Any = None
        try:
            self.events_processed += 1

            # Parse incoming event using Detection model for schema compliance
            try:
                source_detection = Detection.model_validate(payload)
            except ValidationError:
                # Fall back to raw dict for backward compatibility
                source_detection = None

            clip_path = (
                source_detection.audio_clip_path if source_detection else payload.get("clip_path")
            )
            # Also check metadata for clip_path (new schema stores it there too)
            if not clip_path and source_detection and source_detection.metadata:
                clip_path = source_detection.metadata.get("clip_path")
            channel_id = payload.get("channel_id")
            if source_detection and source_detection.channel is not None:
                channel_id = str(source_detection.channel)
            source_event_id = (
                source_detection.event_id if source_detection else payload.get("event_id")
            )
            source_context = source_detection.context if source_detection else None

            if not clip_path:
                logger.warning("Audio motion event missing clip_path", event_id=source_event_id)
                return

            logger.info(
                "Received audio motion event",
                event_id=source_event_id,
                channel_id=channel_id,
                clip_path=Path(clip_path).name,
            )

            # Load audio file
            logger.debug("Loading audio file", path=clip_path)
            audio, sample_rate = self._load_audio(clip_path)

            if audio is None:
                logger.error("Failed to load audio file", path=clip_path)
                return

            duration_seconds = len(audio) / sample_rate
            logger.info(
                "Running BirdNET inference",
                duration_seconds=f"{duration_seconds:.1f}",
                sample_rate=sample_rate,
            )

            # Run detection
            start_time = time.time()

            if self.model is None:
                logger.error("BirdNET model is not loaded")
                return

            detections = self.model.predict(
                audio,
                sample_rate=sample_rate,
                min_confidence=self.config.confidence_threshold,
                lat=self.config.location_lat,
                lon=self.config.location_lon,
            )
            inference_time_ms = int((time.time() - start_time) * 1000)

            if detections:
                self.detections_found += len(detections)

                # Log each detection.
                # is_corvid uses the scientific name when available (Layer
                # 1, captures all Corvidae genera robustly) and falls back
                # to the 6-char slug for legacy paths. See
                # orpheus_common.detection.species.is_corvid.
                for det in detections:
                    detected_is_corvid = is_corvid(
                        scientific_name=det.get("species_scientific"),
                        species_code=det.get("species_code"),
                    )
                    logger.info(
                        "Detected species",
                        species_code=det["species_code"],
                        species_common=det["species_common"],
                        confidence=f"{det['confidence']:.2f}",
                        is_corvid=detected_is_corvid,
                    )

                # Create event. Compute the chain root: if the source
                # audio.motion already has a root_event_id, inherit it;
                # otherwise the audio.motion event_id IS the root (this
                # detector is one hop downstream).
                # See docs/designs/cross-classifier-identity.md §1.1.
                root_event_id = Detection.derive_root_event_id(source_detection)
                event = self._create_detection_event(
                    detections=detections,
                    source_event_id=source_event_id,
                    channel_id=channel_id,
                    clip_path=clip_path,
                    inference_time_ms=inference_time_ms,
                    source_context=source_context,
                    root_event_id=root_event_id,
                )

                # Publish to MQTT
                logger.info(
                    "Publishing bird detection event",
                    topic="orpheus/detection/bird/events",
                    event_id=event.event_id,
                    num_detections=len(detections),
                )
                self.bus.publish(
                    "orpheus/detection/bird/events",
                    event.model_dump(mode="json"),
                )

                # Store in database
                self._store_detections(event, detections)
            else:
                logger.debug(
                    "No detections above threshold",
                    clip_path=Path(clip_path).name,
                    threshold=self.config.confidence_threshold,
                )

        except Exception as e:
            self.errors_count += 1
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            logger.error(
                "Error processing audio motion event",
                event_id=source_event_id,
                error=str(e),
                exc_info=True,
            )

    def _load_audio(self, clip_path: str) -> tuple[np.ndarray | None, int]:
        """Load audio file, mono, resampled to BirdNET's required 48kHz."""
        try:
            audio, sample_rate = sf.read(clip_path)

            # Convert to mono if stereo
            if len(audio.shape) > 1:
                audio = np.mean(audio, axis=1)

            # BirdNET requires 48kHz; the capture/clip rate may differ (e.g. a
            # 22.05kHz file), so resample rather than reject. scipy polyphase
            # (anti-aliased) needs no extra backend — librosa.resample's default
            # types pull resampy/soxr, which aren't in every agent image.
            if sample_rate != 48000:
                g = gcd(48000, int(sample_rate))
                audio = resample_poly(audio, 48000 // g, int(sample_rate) // g)
                sample_rate = 48000
        except Exception as e:
            logger.error("Error loading audio file", path=clip_path, error=str(e), exc_info=True)
            return None, 0
        else:
            return audio, sample_rate

    def _create_detection_event(
        self,
        detections: list[dict[str, Any]],
        source_event_id: str | None,
        channel_id: str | None,
        clip_path: str,
        inference_time_ms: int,
        source_context: SpatiotemporalContext | None = None,
        root_event_id: str | None = None,
    ) -> Detection:
        """Create bird detection event as a Detection model."""
        timestamp = datetime.now(timezone.utc)

        # Add is_corvid flag to each detection. Uses scientific-name-
        # based check (Corvidae family membership) when available, falls
        # back to the 6-char slug. Catches ALL corvid genera (American
        # Crow + Common Raven + Fish Crow + Blue Jay + Black-billed
        # Magpie + Pinyon Jay + Canada Jay + …), not just the slugs
        # BirdNET's parser happens to emit. See species.is_corvid.
        for det in detections:
            det["is_corvid"] = is_corvid(
                scientific_name=det.get("species_scientific"),
                species_code=det.get("species_code"),
            )

        return Detection(
            timestamp=timestamp,
            detection_type="species.detected",
            # str() coercion: legacy publishers may send channel_id as
            # int. `int.isdigit` doesn't exist; str.isdigit does. Round-
            # tripping through str makes both paths safe.
            channel=(
                int(channel_id)
                if channel_id is not None and str(channel_id).isdigit()
                else None
            ),
            audio_clip_path=clip_path,
            source_event_id=source_event_id,
            root_event_id=root_event_id,
            context=source_context,
            metadata={
                "detections": detections,
                "model_version": "BirdNET_V2.4",
                "inference_time_ms": inference_time_ms,
            },
        )

    def _store_detections(self, event: Detection, detections: list[dict[str, Any]]) -> None:
        """Store detections in database."""
        try:
            for det in detections:
                # Build per-window intervals from the BirdNET sliding windows
                # where this species cleared threshold (ADR 0011 §4.5 cross-
                # cutting). Fall back to a single span from the top-level
                # start/end_time for legacy detection dicts that have not been
                # plumbed through _merge_detections.
                windows = det.get("windows")
                if windows:
                    intervals = [
                        TemporalInterval(
                            start_seconds=float(w["start_time"]),
                            end_seconds=float(w["end_time"]),
                            confidence=float(w["confidence"]),
                        )
                        for w in windows
                    ]
                else:
                    intervals = [
                        TemporalInterval(
                            start_seconds=float(det["start_time"]),
                            end_seconds=float(det["end_time"]),
                            confidence=float(det["confidence"]),
                        )
                    ]

                # Layer 1 — canonical TaxonomyRef in the ioc namespace,
                # built from BirdNET's natively-emitted scientific name.
                taxonomy = parts_to_taxonomy_ref(
                    scientific=det.get("species_scientific"),
                    common=det.get("species_common"),
                )
                # Composite event_id: use the (collision-free) scientific
                # name slug. species_code is BirdNET's 6-char prefix which
                # collides — two different species labels sharing the
                # prefix (e.g. "corvus" covers ~32 crow/raven species,
                # "antros" covers ~10 Antrostomus nightjars) would
                # produce identical composite event_ids and hit a UNIQUE
                # constraint on the second db.save(). Falling back to
                # species_code only if scientific is missing.
                scientific = det.get("species_scientific") or ""
                code_for_eid = (
                    scientific.replace(" ", "_").lower()
                    if scientific
                    else det["species_code"]
                )
                detection = Detection(
                    event_id=f"{event.event_id}_{code_for_eid}",
                    timestamp=event.timestamp,
                    detection_type="species.detected",
                    channel=event.channel,
                    species_code=det["species_code"],
                    species_common=det["species_common"],
                    confidence=det["confidence"],
                    audio_clip_path=event.audio_clip_path,
                    context=event.context,
                    intervals=intervals,
                    taxonomy=taxonomy,
                    metadata={
                        "start_time": det["start_time"],
                        "end_time": det["end_time"],
                        "species_scientific": det.get("species_scientific"),
                        "model_version": event.metadata.get("model_version", "BirdNET_V2.4"),
                        "inference_time_ms": event.metadata.get("inference_time_ms", 0),
                        "is_corvid": det.get("is_corvid", False),
                    },
                    # Per-species detection is one hop downstream of the
                    # bird-detection event itself, so source_event_id
                    # points at event.event_id (the parent), NOT
                    # event.source_event_id (the grandparent — the
                    # audio.motion). The audio.motion is still reachable
                    # via root_event_id, preserved across the chain.
                    source_event_id=event.event_id,
                    # Use Detection.derive_root_event_id rather than
                    # passing event.root_event_id directly: if the
                    # parent's root_event_id is None (legacy upstream
                    # that hasn't been migrated, or an audio.motion
                    # publisher that didn't set its own root), the
                    # helper falls back to parent.event_id, keeping the
                    # chain queryable. Passing the raw value would
                    # propagate None and orphan the row.
                    root_event_id=Detection.derive_root_event_id(event),
                )
                self.detection_db.save(detection)
                # §3 event-sourcing shadow: mirror the just-saved detection to the
                # durable domain stream, keyed by event_id (dedup-able). Off by
                # default; best-effort (never raises); the DB stays source of truth.
                if self._shadow_publish:
                    shadow_publish(
                        self.bus, "orpheus/detection/bird/events", detection
                    )
            logger.debug("Stored detections in database", num_detections=len(detections))
        except Exception as e:
            logger.error("Error storing detections in database", error=str(e), exc_info=True)
            # A storage failure (disk full, UNIQUE collision) was invisible to the
            # cross-agent error feed — the inner except swallowed it before the handler's
            # counter (line ~256) could see it. Count it here, matching crow-detection.
            self.errors_count += 1
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"


def main() -> None:
    """Main entry point."""
    agent = BirdDetectionAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
