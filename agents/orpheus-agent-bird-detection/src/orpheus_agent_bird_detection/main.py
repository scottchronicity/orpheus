"""Main entry point for bird detection agent."""

from __future__ import annotations

import asyncio
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from orpheus_common import DetectionDB, OrpheusConfig
from orpheus_common.detection import Detection
from orpheus_common.events import SpatiotemporalContext
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.mqtt import MQTTClient
from pydantic import ValidationError

from .birdnet import CORVID_SPECIES, BirdNETModel
from .config import load_config

logger = get_logger(__name__)


class BirdDetectionAgent:
    """Bird detection agent using BirdNET."""

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize bird detection agent."""
        self.orpheus_config = OrpheusConfig.get_instance(config_path=config_path)
        self.config = load_config(self.orpheus_config)

        self.mqtt_client: MQTTClient | None = None
        self.model: BirdNETModel | None = None
        self.detection_db: DetectionDB | None = None
        self.stop_event = None

        # Statistics
        self.events_processed = 0
        self.detections_found = 0

    async def start(self) -> None:
        """Start the agent."""
        setup_logging("orpheus-agent-bird-detection", level="INFO")
        logger.info("Starting Bird Detection Agent")
        self.stop_event = asyncio.Event()

        # Load model
        logger.info("Loading BirdNET model", model_path=self.config.model_path)
        try:
            self.model = BirdNETModel(self.config.model_path)
        except FileNotFoundError:
            logger.exception("Model file not found", model_path=self.config.model_path)
            logger.info(
                "Download model with: python -m orpheus_agent_bird_detection.birdnet --download"
            )
            raise
        except Exception as e:
            logger.exception("Failed to load BirdNET model", error=str(e))
            raise

        # Initialize DetectionDB
        self.detection_db = DetectionDB()
        logger.info("DetectionDB initialized")

        # Connect to MQTT
        self.mqtt_client = MQTTClient(
            broker_host=self.orpheus_config.mqtt.broker_host,
            broker_port=self.orpheus_config.mqtt.broker_port,
            client_id="orpheus-agent-bird-detection",
            will_topic="orpheus/system/bird-detection/health",
            will_payload={"status": "offline"},
        )

        # Subscribe to audio motion events
        self.mqtt_client.subscribe(
            "orpheus/audio/motion/events",
            self._on_audio_motion_event,
        )

        # Connect and start
        self.mqtt_client.connect()
        logger.info("Connected to MQTT broker")

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop_event.set)

        # Publish startup health message
        self.mqtt_client.publish(
            "orpheus/system/bird-detection/health",
            {
                "status": "online",
                "model_loaded": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Wait for stop signal
        await self.stop_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        """Shut down the agent."""
        logger.info("Shutting down Bird Detection Agent")

        if self.mqtt_client:
            self.mqtt_client.publish(
                "orpheus/system/bird-detection/health",
                {"status": "offline", "timestamp": datetime.now(timezone.utc).isoformat()},
            )
            self.mqtt_client.disconnect()

        logger.info(
            "Processed %d events, found %d detections",
            self.events_processed,
            self.detections_found,
        )

    def _on_audio_motion_event(self, _topic: str, payload: dict[str, Any]) -> None:
        """Handle audio motion event."""
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

                # Log each detection
                for det in detections:
                    is_corvid = det["species_code"] in CORVID_SPECIES
                    logger.info(
                        "Detected species",
                        species_code=det["species_code"],
                        species_common=det["species_common"],
                        confidence=f"{det['confidence']:.2f}",
                        is_corvid=is_corvid,
                    )

                # Create event
                event = self._create_detection_event(
                    detections=detections,
                    source_event_id=source_event_id,
                    channel_id=channel_id,
                    clip_path=clip_path,
                    inference_time_ms=inference_time_ms,
                    source_context=source_context,
                )

                # Publish to MQTT
                logger.info(
                    "Publishing bird detection event",
                    topic="orpheus/detection/bird/events",
                    event_id=event.event_id,
                    num_detections=len(detections),
                )
                self.mqtt_client.publish(
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
            logger.error(
                "Error processing audio motion event",
                event_id=source_event_id,
                error=str(e),
                exc_info=True,
            )

    def _load_audio(self, clip_path: str) -> tuple[np.ndarray | None, int]:
        """Load audio file."""
        try:
            audio, sample_rate = sf.read(clip_path)

            # Convert to mono if stereo
            if len(audio.shape) > 1:
                audio = np.mean(audio, axis=1)
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
    ) -> Detection:
        """Create bird detection event as a Detection model."""
        timestamp = datetime.now(timezone.utc)

        # Add is_corvid flag to each detection
        for det in detections:
            det["is_corvid"] = det["species_code"] in CORVID_SPECIES

        return Detection(
            timestamp=timestamp,
            detection_type="species.detected",
            channel=int(channel_id) if channel_id and channel_id.isdigit() else None,
            audio_clip_path=clip_path,
            source_event_id=source_event_id,
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
                detection = Detection(
                    event_id=f"{event.event_id}_{det['species_code']}",
                    timestamp=event.timestamp,
                    detection_type="species.detected",
                    channel=event.channel,
                    species_code=det["species_code"],
                    species_common=det["species_common"],
                    confidence=det["confidence"],
                    audio_clip_path=event.audio_clip_path,
                    context=event.context,
                    metadata={
                        "start_time": det["start_time"],
                        "end_time": det["end_time"],
                        "model_version": event.metadata.get("model_version", "BirdNET_V2.4"),
                        "inference_time_ms": event.metadata.get("inference_time_ms", 0),
                        "is_corvid": det.get("is_corvid", False),
                    },
                    source_event_id=event.source_event_id,
                )
                self.detection_db.save(detection)
            logger.debug("Stored detections in database", num_detections=len(detections))
        except Exception as e:
            logger.error("Error storing detections in database", error=str(e), exc_info=True)


def main() -> None:
    """Main entry point."""
    agent = BirdDetectionAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
