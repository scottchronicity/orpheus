"""Main entry point for the event correlator agent."""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone
from typing import Any

from orpheus_common import OrpheusConfig
from orpheus_common.detection import Detection, DetectionDB, Entity
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.mqtt import MQTTClient
from pydantic import ValidationError

from .cluster_manager import ClusterManager, Observation

logger = get_logger(__name__)

# Detection types to ignore (raw triggers, not entities)
IGNORED_DETECTION_TYPES = {"audio.motion"}

# Detection types to process
PROCESSED_DETECTION_TYPES = {"species.detected", "crow.analyzed"}


class EventCorrelatorAgent:
    """Event correlator agent that fuses detection events into EntityEvents."""

    def __init__(
        self,
        window_seconds: float = 3.0,
        config_path: str | None = None,
    ) -> None:
        """Initialize event correlator agent."""
        self.orpheus_config = OrpheusConfig.get_instance(config_path=config_path)
        self.window_seconds = window_seconds

        self.mqtt_client: MQTTClient | None = None
        self.cluster_manager: ClusterManager | None = None
        self.stop_event: asyncio.Event | None = None
        self.db: DetectionDB | None = None

        # Statistics
        self.events_received = 0
        self.events_ignored = 0
        self.entities_emitted = 0

    async def start(self) -> None:
        """Start the agent."""
        setup_logging("orpheus-agent-event-correlator", level="INFO")
        logger.info("Starting Event Correlator Agent", window_seconds=self.window_seconds)
        self.stop_event = asyncio.Event()

        # Initialize database for entity persistence
        self.db = DetectionDB()
        logger.info("Initialized entity database", db_path=str(self.db.db_path))

        loop = asyncio.get_running_loop()

        # Initialize cluster manager
        self.cluster_manager = ClusterManager(
            window_seconds=self.window_seconds,
            on_entity_ready=self._on_entity_ready,
        )
        self.cluster_manager.set_loop(loop)

        # Connect to MQTT
        self.mqtt_client = MQTTClient(
            broker_host=self.orpheus_config.mqtt.broker_host,
            broker_port=self.orpheus_config.mqtt.broker_port,
            client_id="orpheus-agent-event-correlator",
            will_topic="orpheus/system/event-correlator/health",
            will_payload={"status": "offline"},
        )

        # Subscribe to detection topics from config
        for topic in self.orpheus_config.correlation.input_topics:
            self.mqtt_client.subscribe(
                topic,
                self._on_detection_event,
            )
            logger.info("Subscribed to detection topic", topic=topic)

        self.mqtt_client.connect()
        logger.info("Connected to MQTT broker")

        # Set up signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop_event.set)

        # Publish startup health
        self.mqtt_client.publish(
            "orpheus/system/event-correlator/health",
            {
                "status": "online",
                "window_seconds": self.window_seconds,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Wait for stop signal
        await self.stop_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        """Shut down the agent."""
        logger.info("Shutting down Event Correlator Agent")

        # Flush remaining clusters
        if self.cluster_manager is not None:
            remaining = self.cluster_manager.flush_all()
            for entity_event in remaining:
                self._publish_entity(entity_event)

        if self.mqtt_client:
            self.mqtt_client.publish(
                "orpheus/system/event-correlator/health",
                {
                    "status": "offline",
                    "events_received": self.events_received,
                    "entities_emitted": self.entities_emitted,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.mqtt_client.disconnect()

        logger.info(
            "Agent shutdown complete",
            events_received=self.events_received,
            events_ignored=self.events_ignored,
            entities_emitted=self.entities_emitted,
        )

    def _on_detection_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Handle incoming detection event from MQTT."""
        self.events_received += 1

        logger.info(
            "Received detection event",
            topic=topic,
            event_id=payload.get("event_id"),
            detection_type=payload.get("detection_type"),
        )

        # Parse the detection
        try:
            detection = Detection.model_validate(payload)
        except ValidationError:
            # Try from_dict for backward compat
            try:
                detection = Detection.from_dict(payload)
            except Exception as e:
                logger.warning(
                    "Failed to parse detection event",
                    topic=topic,
                    event_id=payload.get("event_id"),
                    error=e,
                    payload=payload,
                )
                self.events_ignored += 1
                return

        # Filter by detection type
        if detection.detection_type in IGNORED_DETECTION_TYPES:
            self.events_ignored += 1
            return

        if detection.detection_type not in PROCESSED_DETECTION_TYPES:
            self.events_ignored += 1
            return

        # Extract context as dict for storage
        context_dict = None
        if detection.context is not None:
            context_dict = detection.context.model_dump(mode="json")

        # Extract sensor_id
        sensor_id = ""
        if detection.context is not None:
            sensor_id = detection.context.sensor_id

        # Unpack observations, passing raw payload for legacy schema support
        try:
            observations = self._unpack_observations(
                detection,
                sensor_id,
                context_dict,
                raw_payload=payload,
            )
        except Exception as e:
            logger.error(
                "Error unpacking observations from detection",
                event_id=detection.event_id,
                error=str(e),
                exc_info=True,
            )
            self.events_ignored += 1
            return

        for obs in observations:
            if self.cluster_manager is not None:
                self.cluster_manager.process_observation(obs)

    def _unpack_observations(
        self,
        detection: Detection,
        sensor_id: str,
        context_dict: dict[str, Any] | None,
        raw_payload: dict[str, Any] | None = None,
    ) -> list[Observation]:
        """Unpack a Detection into individual Observations.

        Checks for sub-detections in two places to support both V2 and legacy
        schemas:
          1. ``detection.metadata["detections"]`` — V2 standard
          2. ``raw_payload["detections"]`` — Legacy BirdNET (root-level list)

        If neither contains sub-detections, the top-level species_code is used
        as a single Observation.
        """
        observations = []

        # V2 schema: detections nested under metadata
        sub_detections = detection.metadata.get("detections")

        # Legacy BirdNET schema: detections at root level of the raw payload
        if (not sub_detections or not isinstance(sub_detections, list)) and raw_payload:
            legacy = raw_payload.get("detections")
            if legacy and isinstance(legacy, list):
                sub_detections = legacy

        if sub_detections and isinstance(sub_detections, list):
            # BirdNET / multi-detection style: iterate sub-detections
            for sub in sub_detections:
                species_code = sub.get("species_code", "")
                common_name = sub.get("species_common", "")
                confidence = float(sub.get("confidence", 0.0))

                if not species_code:
                    continue

                obs = Observation(
                    species_code=species_code,
                    common_name=common_name,
                    confidence=confidence,
                    event_id=detection.event_id,
                    source_event_id=detection.source_event_id,
                    sensor_id=sensor_id,
                    clip_path=detection.audio_clip_path,
                    context=context_dict,
                )
                observations.append(obs)
        # Single detection style (e.g., crow.analyzed)
        elif detection.species_code:
            obs = Observation(
                species_code=detection.species_code,
                common_name=detection.species_common or "",
                confidence=float(detection.confidence or 0.0),
                event_id=detection.event_id,
                source_event_id=detection.source_event_id,
                sensor_id=sensor_id,
                clip_path=detection.audio_clip_path,
                context=context_dict,
            )
            observations.append(obs)

        return observations

    def _on_entity_ready(self, entity_event: dict[str, Any]) -> None:
        """Callback invoked when a cluster expires and an EntityEvent is ready."""
        self._persist_entity(entity_event)
        self._publish_entity(entity_event)

    def _persist_entity(self, entity_event: dict[str, Any]) -> None:
        """Save an EntityEvent to the local SQLite database."""
        if self.db is None:
            return
        try:
            entity = Entity.from_entity_event(entity_event)
            self.db.save_entity(entity)
            logger.debug(
                "Persisted entity to DB",
                entity_id=entity.entity_id,
            )
        except Exception as e:
            logger.warning(
                "Failed to persist entity to DB",
                entity_id=entity_event.get("entity_id"),
                error=str(e),
            )

    def _publish_entity(self, entity_event: dict[str, Any]) -> None:
        """Publish an EntityEvent to MQTT."""
        self.entities_emitted += 1

        logger.info(
            "Publishing EntityEvent",
            entity_id=entity_event["entity_id"],
            species_code=entity_event["species_code"],
            common_name=entity_event["common_name"],
            confidence=entity_event["confidence"],
            evidence_count=len(entity_event["evidence"]),
        )

        if self.mqtt_client is not None:
            self.mqtt_client.publish(
                "orpheus/entities/animal",
                entity_event,
            )


def main() -> None:
    """Main entry point."""
    agent = EventCorrelatorAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
