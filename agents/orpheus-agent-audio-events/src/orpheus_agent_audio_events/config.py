"""Configuration management for the audio-events detection agent."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from orpheus_common.config import OrpheusConfig
from orpheus_inference.protocol import MAX_PAYLOAD

from .model import PANNsCnn14SED


@dataclass(frozen=True)
class GPUWorkerConfig:
    """Opt-in worker policy, independent from CPU concurrency/device selection."""

    python: str = ""
    startup_timeout_seconds: float = 60.0
    request_timeout_seconds: float = 5.0
    clip_ttl_seconds: float | None = None
    max_clip_seconds: float = 40.0
    # Retained for YAML compatibility. Admission no longer rejects on this
    # setting: accepted audio.motion work stays queued until processed.
    max_pending_clips: int = 2
    start_memory_mib: int = 8704
    floor_memory_mib: int = 3800
    restart_backoff_seconds: float = 2.0
    max_starts: int = 3
    restart_window_seconds: float = 300.0

    def __post_init__(self) -> None:
        for value in (
            self.max_pending_clips,
            self.start_memory_mib,
            self.floor_memory_mib,
            self.max_starts,
        ):
            if type(value) is not int:
                raise ValueError("GPU counts and memory limits must be integers")
        for value in (
            self.startup_timeout_seconds,
            self.request_timeout_seconds,
            self.max_clip_seconds,
            self.restart_backoff_seconds,
            self.restart_window_seconds,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("GPU worker timeouts/lengths must be positive and finite")
        ttl = self.clip_ttl_seconds
        if ttl is not None and (not math.isfinite(ttl) or ttl <= 0):
            raise ValueError("GPU clip TTL must be positive and finite when set")
        # Bound allocations by the actual OGW1 frame capacity, not a station's
        # recording length. Allow the proxy's two-frame output tolerance too.
        input_seconds = (MAX_PAYLOAD // 4) / PANNsCnn14SED.PANNS_SAMPLE_RATE
        output_seconds = (
            MAX_PAYLOAD // (PANNsCnn14SED.PANNS_NUM_CLASSES * 4) - 3
        ) * PANNsCnn14SED.PANNS_FRAME_DURATION_SECONDS
        if self.max_clip_seconds > min(input_seconds, output_seconds):
            raise ValueError("GPU max_clip_seconds exceeds IPC payload capacity")
        if self.max_pending_clips < 0 or self.max_starts < 1:
            raise ValueError("invalid legacy GPU pending setting or restart budget")
        if not 0 < self.floor_memory_mib < self.start_memory_mib:
            raise ValueError(
                "GPU memory floor must be positive and start memory must exceed the floor"
            )


@dataclass
class AudioEventsConfig:
    """Configuration for the audio-events detection agent.

    See companion design doc ``docs/designs/audio-events-agent.md`` §4.1 for
    the rationale behind each knob's default value.
    """

    enabled: bool
    model_path: str
    model_variant: str
    sample_rate: int
    clip_threshold: float
    frame_threshold: float
    bridge_ms: int
    min_interval_ms: int
    max_labels_per_clip: int | None
    device: str
    input_topic: str
    output_topic: str
    # Max clips processed concurrently. A new audio.motion tick starts a new clip
    # without cancelling an in-flight one (older instances finish); bounded so SED
    # inference can't thrash the Jetson's unified RAM/GPU. Default small.
    max_concurrent_clips: int
    backend: str = "inprocess"
    gpu_worker: GPUWorkerConfig = field(default_factory=GPUWorkerConfig)

    def __post_init__(self) -> None:
        if self.backend not in {"inprocess", "gpu_worker", "auto"}:
            raise ValueError("audio_events.backend must be inprocess, gpu_worker or auto")
        # panns_inference supports these placements only; its wrapper silently
        # treats other strings (including mps and cuda:1) as CPU.
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("audio_events.device supports only auto, cpu or cuda")
        if self.backend == "gpu_worker" and self.device == "cpu":
            raise ValueError("audio_events.backend=gpu_worker requires device auto or cuda")
        if type(self.max_concurrent_clips) is not int or self.max_concurrent_clips < 1:
            raise ValueError("audio_events.max_concurrent_clips must be a positive integer")

    @classmethod
    def from_orpheus_config(cls, config: OrpheusConfig) -> AudioEventsConfig:
        """Build an ``AudioEventsConfig`` from the unified ``orpheus.yaml``."""
        agent_config = config._raw.get("audio_events", {})

        data_root = os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus")
        default_model_path = f"{data_root}/models/panns_cnn14_decision_level_max.pth"
        worker_raw = dict(agent_config.get("gpu_worker", {}))
        worker_raw.setdefault("python", f"{data_root}/venvs/panns-gpu/bin/python")

        topics = config._raw.get("mqtt", {}).get("topics", {})
        default_input_topic = topics.get("audio_motion_events", "orpheus/audio/motion/events")
        default_output_topic = topics.get(
            "audio_events_detections", "orpheus/detection/audio/events"
        )

        return cls(
            enabled=agent_config.get("enabled", True),
            model_path=agent_config.get("model_path", default_model_path),
            model_variant=agent_config.get("model_variant", "cnn14_sed"),
            sample_rate=int(agent_config.get("sample_rate", 32000)),
            clip_threshold=float(agent_config.get("clip_threshold", 0.3)),
            frame_threshold=float(agent_config.get("frame_threshold", 0.2)),
            bridge_ms=int(agent_config.get("bridge_ms", 100)),
            min_interval_ms=int(agent_config.get("min_interval_ms", 150)),
            max_labels_per_clip=agent_config.get("max_labels_per_clip"),
            device=str(agent_config.get("device", "auto")),
            input_topic=str(agent_config.get("input_topic", default_input_topic)),
            output_topic=str(agent_config.get("output_topic", default_output_topic)),
            max_concurrent_clips=agent_config.get("max_concurrent_clips", 2),
            backend=str(agent_config.get("backend", "inprocess")),
            gpu_worker=GPUWorkerConfig(**worker_raw),
        )


def load_config(config_path: Path | None = None) -> AudioEventsConfig:
    """Load audio-events configuration from the unified ``orpheus.yaml``."""
    orpheus_config = OrpheusConfig.get_instance(config_path=config_path)
    return AudioEventsConfig.from_orpheus_config(orpheus_config)
