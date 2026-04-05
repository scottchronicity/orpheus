"""Main entry point for crow detection agent."""

from __future__ import annotations

import asyncio
import json
import signal
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import soundfile as sf
from orpheus_common import DetectionDB, OrpheusConfig
from orpheus_common.detection import Detection
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.mqtt import MQTTClient
from pydantic import ValidationError

from .classifier import CrowClassifier, CrowDetectionResult
from .config import load_config
from .embedder import AVESEmbedder

logger = get_logger(__name__)


class CrowDetectionAgent:
    """Crow detection agent using crow-tools models."""

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize crow detection agent."""
        self.config = load_config(config_path)
        self.orpheus_config = OrpheusConfig.get_instance(config_path=config_path)

        self.mqtt_client: MQTTClient | None = None
        self.embedder: AVESEmbedder | None = None
        self.classifier: CrowClassifier | None = None
        self.detection_db: DetectionDB | None = None
        self.stop_event = None

        # Statistics
        self.events_processed = 0
        self.detections_found = 0

    async def start(self) -> None:
        """Start the agent."""
        setup_logging("orpheus-agent-crow-detection", level="INFO")
        logger.info("Starting Crow Detection Agent")
        if self.stop_event is None:
            self.stop_event = asyncio.Event()

        if not self.config.enabled:
            logger.warning("Crow detection is disabled in configuration")
            return

        # Load models
        logger.info(
            "Loading AVES embedder",
            model_path=str(self.config.embedder_model_path),
            sample_rate=self.config.embedder_sample_rate,
        )
        try:
            self.embedder = AVESEmbedder(
                self.config.embedder_model_path,
                sample_rate=self.config.embedder_sample_rate,
            )
            logger.info("AVES embedder loaded successfully")
        except FileNotFoundError:
            logger.error(  # noqa: TRY400
                "Embedder model file not found",
                path=str(self.config.embedder_model_path),
            )
            logger.info("Place AVES model at specified path or update config")
            raise

        logger.info("Loading crow classifier", model_path=str(self.config.classifier_model_path))
        try:
            self.classifier = CrowClassifier(self.config.classifier_model_path)
            logger.info("Crow classifier loaded successfully")
        except FileNotFoundError:
            logger.error(  # noqa: TRY400
                "Classifier model file not found",
                path=str(self.config.classifier_model_path),
            )
            logger.info("Place classifier model at specified path or update config")
            raise

        # Initialize DetectionDB
        self.detection_db = DetectionDB()
        logger.info("DetectionDB initialized")

        # Connect to MQTT
        logger.info("Initializing MQTT client")
        self.mqtt_client = MQTTClient(
            broker_host=self.orpheus_config.mqtt.broker_host,
            broker_port=self.orpheus_config.mqtt.broker_port,
            client_id="orpheus-agent-crow-detection",
            will_topic="orpheus/system/crow-detection/health",
            will_payload={"status": "offline"},
        )

        # Subscribe to bird detection events (not audio motion events)
        # Only process when corvids (crows/ravens) are detected
        logger.info("Subscribing to bird detection events for corvid filtering")
        self.mqtt_client.subscribe(
            "orpheus/detection/bird/events",
            self._on_bird_detection_event,
        )

        # Connect and start
        self.mqtt_client.connect()
        logger.info("Connected to MQTT broker successfully")

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        if self.stop_event is None:
            logger.error("Stop event not initialized")
            return

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop_event.set)

        # Publish startup health message
        self.mqtt_client.publish(
            "orpheus/system/crow-detection/health",
            {
                "status": "online",
                "models_loaded": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Wait for stop signal
        await self.stop_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        """Shutdown the agent."""
        logger.info("Shutting down Crow Detection Agent")

        if self.mqtt_client:
            self.mqtt_client.publish(
                "orpheus/system/crow-detection/health",
                {
                    "status": "offline",
                    "events_processed": self.events_processed,
                    "detections_found": self.detections_found,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.mqtt_client.disconnect()

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
            except (ValidationError, Exception):
                # Fall back to raw dict for legacy payloads
                logger.debug("Payload did not match V2 Detection schema, using legacy parsing")

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

            # Build source event dict for downstream processing
            source_event = {
                "event_id": event_id,
                "channel_id": str(channel) if channel is not None else "unknown",
                "context": source_context,
            }

            # Process the audio file for crow-specific detection
            self._process_audio_file(audio_path, source_event)

        except Exception as e:
            logger.error(
                "Error processing bird detection event",
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

        # Publish to MQTT using the standardised Detection model
        if self.mqtt_client:
            self.mqtt_client.publish(
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

    def _generate_event_id(self, channel_id: str) -> str:
        """Generate unique event ID."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"crow_det_{timestamp}_ch{channel_id}_{self.detections_found:03d}"


def main() -> None:
    """Main entry point."""
    agent = CrowDetectionAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
