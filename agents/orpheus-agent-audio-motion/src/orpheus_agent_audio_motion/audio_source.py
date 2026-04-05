"""Audio ingestion interfaces for the Audio Motion Detector agent."""

from __future__ import annotations

import asyncio
import math
import os
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
import sounddevice as sd
from orpheus_common.diagnostics.audio_health import get_audio_health_monitor
from orpheus_common.logging import get_logger

logger = get_logger(__name__)

# Full scale values for dB calculations
INT16_FULL_SCALE = 32768.0
INT32_FULL_SCALE = 2147483648.0

if TYPE_CHECKING:  # pragma: no cover
    from .config import RuntimeSettings


@dataclass(frozen=True)
class AudioFrame:
    """Container for a single multi-channel audio frame."""

    channel_id: str
    payload: bytes
    timestamp: datetime


class AudioSource(ABC):
    """Abstract base class for hardware-specific audio capture backends."""

    def __init__(self, sample_rate: int, frame_duration_ms: int, max_pending_frames: int) -> None:
        self._sample_rate = sample_rate
        self._frame_duration_ms = frame_duration_ms
        self._max_pending_frames = max_pending_frames
        self._running = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start audio acquisition for the source."""
        async with self._lock:
            if self._running:
                logger.debug("Audio source already running")
                return
            await self._start_internal()
            self._running = True
            logger.info(
                "Audio source started",
                sample_rate=self._sample_rate,
                frame_duration_ms=self._frame_duration_ms,
            )

    async def stop(self) -> None:
        """Stop audio acquisition and release resources."""
        async with self._lock:
            if not self._running:
                logger.debug("Audio source already stopped")
                return
            await self._stop_internal()
            self._running = False
            logger.info("Audio source stopped")

    async def stream_frames(self) -> AsyncGenerator[AudioFrame, None]:
        """Yield audio frames asynchronously until the source is stopped."""
        if not self._running:
            raise RuntimeError("Audio source must be started before streaming frames")
        async for frame in self._stream_internal():
            yield frame

    @abstractmethod
    async def _start_internal(self) -> None:
        """Backend-specific start hook."""

    @abstractmethod
    async def _stop_internal(self) -> None:
        """Backend-specific stop hook."""

    @abstractmethod
    async def _stream_internal(self) -> AsyncGenerator[AudioFrame, None]:
        """Backend-specific frame generator."""

    @property
    def sample_rate(self) -> int:
        """Return the configured sample rate."""
        return self._sample_rate

    @property
    def frame_duration_ms(self) -> int:
        """Return the frame length in milliseconds."""
        return self._frame_duration_ms

    @property
    def max_pending_frames(self) -> int:
        """Return the configured pending frame buffer size."""
        return self._max_pending_frames

    def is_running(self) -> bool:
        """Return whether the source has been started."""
        return self._running


class SyntheticAudioSource(AudioSource):
    """Generate synthetic test signals without any hardware."""

    SIGNAL_TYPES = ["silence", "sine", "chirp", "white_noise"]

    def __init__(
        self,
        sample_rate: int,
        frame_duration_ms: int,
        max_pending_frames: int,
        signal_type: str = "sine",
        amplitude: float = 0.1,
        frequency: float = 440.0,
        channel_id: str = "synthetic",
    ) -> None:
        """
        Initialize synthetic audio source.

        Args:
            sample_rate: Sample rate in Hz
            frame_duration_ms: Frame duration in milliseconds
            max_pending_frames: Maximum pending frame buffer size
            signal_type: Type of signal ("silence", "sine", "chirp", "white_noise")
            amplitude: Signal amplitude (0.0 to 1.0)
            frequency: Base frequency for sine/chirp signals in Hz
            channel_id: Channel identifier for frames
        """
        super().__init__(sample_rate, frame_duration_ms, max_pending_frames)

        if signal_type not in self.SIGNAL_TYPES:
            raise ValueError(
                f"Invalid signal_type '{signal_type}'. Must be one of {self.SIGNAL_TYPES}"
            )

        self._signal_type = signal_type
        self._amplitude = amplitude
        self._frequency = frequency
        self._channel_id = channel_id
        self._frame_counter = 0
        self._samples_per_frame = int((sample_rate * frame_duration_ms) / 1000)

        logger.info(
            "SyntheticAudioSource initialized",
            channel_id=channel_id,
            signal_type=signal_type,
            amplitude=amplitude,
            frequency=frequency,
        )

    async def _start_internal(self) -> None:
        """Start synthetic audio generation."""
        self._frame_counter = 0

    async def _stop_internal(self) -> None:
        """Stop synthetic audio generation."""
        pass

    async def _stream_internal(self) -> AsyncGenerator[AudioFrame, None]:
        """Generate synthetic audio frames."""
        while self._running:
            # Generate synthetic audio data
            samples = self._generate_signal()

            # Convert to int32 PCM bytes (24-bit content in 32-bit container)
            samples_int32 = (samples * 2147483647).astype(np.int32)
            payload = samples_int32.tobytes()

            frame = AudioFrame(
                channel_id=self._channel_id,
                payload=payload,
                timestamp=datetime.now(timezone.utc),
            )

            self._frame_counter += 1
            yield frame

            # Simulate real-time audio capture timing
            await asyncio.sleep(self._frame_duration_ms / 1000.0)

    def _generate_signal(self) -> np.ndarray:
        """Generate signal samples based on configured type."""
        t_start = self._frame_counter * self._samples_per_frame / self._sample_rate
        t = np.linspace(
            t_start,
            t_start + (self._samples_per_frame / self._sample_rate),
            self._samples_per_frame,
            endpoint=False,
        )

        if self._signal_type == "silence":
            return np.zeros(self._samples_per_frame)

        elif self._signal_type == "sine":
            return self._amplitude * np.sin(2 * np.pi * self._frequency * t)

        elif self._signal_type == "chirp":
            # Linear chirp from frequency to 2*frequency
            f0 = self._frequency
            f1 = self._frequency * 2
            return self._amplitude * np.sin(2 * np.pi * (f0 * t + (f1 - f0) * t**2 / (2 * t[-1])))

        elif self._signal_type == "white_noise":
            return self._amplitude * np.random.randn(self._samples_per_frame)

        return np.zeros(self._samples_per_frame)


class DefaultAudioInputSource(AudioSource):
    """Capture from system default audio input device."""

    def __init__(
        self,
        sample_rate: int,
        frame_duration_ms: int,
        max_pending_frames: int,
        channel_id: str = "default",
    ) -> None:
        """
        Initialize default audio input source.

        Args:
            sample_rate: Sample rate in Hz
            frame_duration_ms: Frame duration in milliseconds
            max_pending_frames: Maximum pending frame buffer size
            channel_id: Channel identifier for frames produced by this source
        """
        super().__init__(sample_rate, frame_duration_ms, max_pending_frames)

        self._channel_id = channel_id
        self._stream = None  # type: Optional[sd.InputStream]
        self._queue = None  # type: Optional[asyncio.Queue]
        self._samples_per_frame = int((sample_rate * frame_duration_ms) / 1000)

        # Check for available input devices
        try:
            default_device = sd.query_devices(kind="input")
            logger.info(
                "DefaultAudioInputSource will use device",
                device_name=default_device["name"],
            )
        except Exception as e:
            logger.warning("No default input device found", error=str(e))

    async def _start_internal(self) -> None:
        """Start capturing from default input device."""
        self._queue = asyncio.Queue(maxsize=self._max_pending_frames)

        # Capture event loop reference before starting callback thread
        loop = asyncio.get_event_loop()

        # Get the audio health monitor for telemetry
        health_monitor = get_audio_health_monitor()
        health_monitor.set_running(True)
        health_monitor.set_hardware_config(
            sample_rate=self._sample_rate,
            buffer_size=self._samples_per_frame,
            device_name="default",
            num_channels=1,
            audio_format="int32",
        )

        def audio_callback(indata, frames, time_info, status):
            """Sounddevice callback - runs in separate thread."""
            # Record callback timing for health monitoring
            health_monitor.record_callback_timing()

            if status:
                logger.warning("Audio input status", status=str(status))
                # Record XRUNs
                if status.input_overflow:
                    health_monitor.record_xrun(is_input_overflow=True)
                if status.input_underflow:
                    health_monitor.record_xrun(is_input_underflow=True)

            # Calculate peak amplitude level in dB for health monitoring
            # (uses fast peak instead of RMS)
            peak = np.max(np.abs(indata.astype(np.float64)))
            if peak > 0:
                level_db = 20 * math.log10(peak / INT32_FULL_SCALE)
            else:
                level_db = -100.0
            health_monitor.record_channel_level(self._channel_id, level_db)

            # Copy audio data and put in queue
            audio_data = indata.copy()

            # Use call_soon_threadsafe to safely interact with asyncio from callback thread
            # Wrap put_nowait in a lambda to catch QueueFull exception in the asyncio context
            def safe_put():
                try:
                    self._queue.put_nowait(audio_data)
                except asyncio.QueueFull:
                    logger.warning("Audio queue full, dropping frame")

            loop.call_soon_threadsafe(safe_put)

        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int32",
                blocksize=self._samples_per_frame,
                callback=audio_callback,
            )
            self._stream.start()
            logger.info("Started capturing from default audio input")
        except Exception as e:
            health_monitor.set_running(False)
            raise RuntimeError(
                f"Failed to start default audio input: {e}. "
                "Ensure a microphone is connected and accessible."
            ) from e

    async def _stop_internal(self) -> None:
        """Stop capturing from default input device."""
        # Update health monitor
        get_audio_health_monitor().set_running(False)

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._queue = None

    async def _stream_internal(self) -> AsyncGenerator[AudioFrame, None]:
        """Stream audio frames from default input device."""
        while self._running:
            try:
                # Wait for audio data with timeout
                audio_data = await asyncio.wait_for(self._queue.get(), timeout=1.0)

                # Convert to bytes
                payload = audio_data.tobytes()

                frame = AudioFrame(
                    channel_id=self._channel_id,
                    payload=payload,
                    timestamp=datetime.now(timezone.utc),
                )

                yield frame

            except asyncio.TimeoutError:
                # No audio data available, check if still running
                if not self._running:
                    break


class ALSAAudioSource(AudioSource):
    """
    Capture from specific ALSA device with multi-channel support (for Jetson Behringer UMC404HD).
    """

    DEVICE_PATTERN = re.compile(r"alsa://([^?]+)(?:\?channel=(\d+))?")

    def __init__(
        self,
        sample_rate: int,
        frame_duration_ms: int,
        max_pending_frames: int,
        device_configs: list[dict[str, Any]],
    ) -> None:
        """
        Initialize ALSA audio source with multi-channel support.

        Args:
            sample_rate: Sample rate in Hz
            frame_duration_ms: Frame duration in milliseconds
            max_pending_frames: Maximum pending frame buffer size
            device_configs: List of device configuration dicts, each with:
                - id: Channel ID
                - device: ALSA device string (e.g., "alsa://orpheus_umc?channel=1")
                All configs must reference the same base device
        """
        super().__init__(sample_rate, frame_duration_ms, max_pending_frames)

        if not device_configs:
            raise ValueError("At least one device configuration required")

        # Parse all device configs and verify they're for the same device
        self._channel_map = {}  # Maps physical channel index to channel_id
        base_device = None

        for config in device_configs:
            device_string = config.get("device", "")
            channel_id = str(config.get("id", "unknown"))

            device_name, channel_num = self._parse_device_string(device_string)

            if base_device is None:
                base_device = device_name
            elif base_device != device_name:
                raise ValueError(
                    f"All device configs must reference the same device. "
                    f"Got {device_name} and {base_device}"
                )

            # Map 1-indexed channel to 0-indexed array position
            self._channel_map[channel_num - 1] = channel_id

        self._device_name = base_device
        self._num_channels = max(self._channel_map.keys()) + 1
        self._stream = None  # type: Optional[sd.InputStream]
        self._queue = None  # type: Optional[asyncio.Queue]
        self._samples_per_frame = int((sample_rate * frame_duration_ms) / 1000)
        self._callback_count = 0  # Track audio callback invocations for debug logging

        logger.info(
            "ALSAAudioSource initialized",
            device_name=self._device_name,
            num_channels=self._num_channels,
            channel_map=self._channel_map,
        )
        print(
            f"DEBUG: ALSAAudioSource channel_map built: "
            f"{dict(sorted(self._channel_map.items()))} (phys_idx -> channel_id)"
        )

    def _parse_device_string(self, device_string: str) -> tuple:
        """
        Parse ALSA device string.

        Args:
            device_string: ALSA device string

        Returns:
            Tuple of (device_name, channel_number)

        Raises:
            ValueError: If device string format is invalid
        """
        match = self.DEVICE_PATTERN.match(device_string)
        if not match:
            raise ValueError(
                f"Invalid ALSA device string: {device_string}. "
                "Expected format: alsa://device_name?channel=N"
            )

        device_name = match.group(1)
        channel_str = match.group(2)
        channel = int(channel_str) if channel_str else 1

        return device_name, channel

    def _find_alsa_device(self) -> Optional[int]:
        """
        Find sounddevice index for ALSA device.

        Returns:
            Device index or None if not found
        """
        devices = sd.query_devices()

        for idx, device in enumerate(devices):
            if self._device_name.lower() in device["name"].lower():
                if device["max_input_channels"] > 0:
                    logger.info(
                        "Found ALSA device",
                        device_name=device["name"],
                        device_index=idx,
                        max_input_channels=device["max_input_channels"],
                    )
                    return idx

        return None

    async def _start_internal(self) -> None:
        """Start capturing from ALSA device with all configured channels."""
        # Find the ALSA device
        device_idx = self._find_alsa_device()
        if device_idx is None:
            available = "\n".join(
                "  - {}".format(d["name"])
                for d in sd.query_devices()
                if d["max_input_channels"] > 0
            )
            raise RuntimeError(
                f"ALSA device '{self._device_name}' not found. "
                f"Available input devices:\n{available}"
            )

        # Verify we have enough channels
        device_info = sd.query_devices(device_idx)
        max_channels = device_info["max_input_channels"]
        if self._num_channels > max_channels:
            raise RuntimeError(
                f"Device '{self._device_name}' only has {max_channels} input channels, "
                f"but {self._num_channels} channels were requested"
            )

        self._queue = asyncio.Queue(maxsize=self._max_pending_frames * len(self._channel_map))

        # Capture event loop reference before starting callback thread
        loop = asyncio.get_event_loop()

        # Get the audio health monitor for telemetry
        health_monitor = get_audio_health_monitor()
        health_monitor.set_running(True)
        health_monitor.set_hardware_config(
            sample_rate=self._sample_rate,
            buffer_size=self._samples_per_frame,
            device_name=self._device_name,
            num_channels=self._num_channels,
            audio_format="int32",
        )

        # Define factory function OUTSIDE the callback to avoid redefinition
        def make_safe_put(ch_id, data):
            """Factory that creates a closure with ch_id and data captured by value."""

            def safe_put():
                try:
                    self._queue.put_nowait((ch_id, data))
                except asyncio.QueueFull:
                    logger.warning("ALSA audio queue full, dropping frame", channel_id=ch_id)

            return safe_put

        def audio_callback(indata, frames, time_info, status):
            """Sounddevice callback - runs in separate thread."""
            # Record callback timing for health monitoring
            health_monitor.record_callback_timing()

            if status:
                logger.warning("ALSA audio input status", status=str(status))
                # Record XRUNs
                if status.input_overflow:
                    health_monitor.record_xrun(is_input_overflow=True)
                if status.input_underflow:
                    health_monitor.record_xrun(is_input_underflow=True)

            # Debug logging on first callback
            self._callback_count += 1
            if self._callback_count == 1:
                print(
                    f"DEBUG: First audio callback: indata.shape={indata.shape}, "
                    f"channel_map={self._channel_map}"
                )

            # Split multi-channel data and queue frames for each configured channel
            for phys_channel_idx, channel_id in self._channel_map.items():
                if phys_channel_idx < indata.shape[1]:
                    # Extract single channel data
                    channel_data = indata[:, phys_channel_idx].copy()

                    # Calculate peak amplitude level in dB for health monitoring
                    # (uses fast peak instead of RMS)
                    peak = np.max(np.abs(channel_data.astype(np.float64)))
                    if peak > 0:
                        level_db = 20 * math.log10(peak / INT32_FULL_SCALE)
                    else:
                        level_db = -100.0
                    health_monitor.record_channel_level(channel_id, level_db)

                    # Use factory to create closure with current loop values captured
                    loop.call_soon_threadsafe(make_safe_put(channel_id, channel_data))

        try:
            # Open stream with all physical channels
            # Note: Behringer UMC404HD requires int32 format (S32_LE in ALSA)
            self._stream = sd.InputStream(
                device=device_idx,
                samplerate=self._sample_rate,
                channels=self._num_channels,
                dtype="int32",
                blocksize=self._samples_per_frame,
                callback=audio_callback,
            )
            self._stream.start()
            logger.info(
                "Started capturing from ALSA device",
                device_name=self._device_name,
                channel_count=len(self._channel_map),
                channel_ids=list(self._channel_map.values()),
            )
        except Exception as e:
            health_monitor.set_running(False)
            raise RuntimeError(f"Failed to start ALSA device '{self._device_name}': {e}") from e

    async def _stop_internal(self) -> None:
        """Stop capturing from ALSA device."""
        # Update health monitor
        get_audio_health_monitor().set_running(False)

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._queue = None

    async def _stream_internal(self) -> AsyncGenerator[AudioFrame, None]:
        """Stream audio frames from ALSA device for all configured channels."""
        while self._running:
            try:
                # Wait for audio data with timeout (channel_id, audio_data tuple)
                channel_id, audio_data = await asyncio.wait_for(self._queue.get(), timeout=1.0)

                # Convert to bytes
                payload = audio_data.tobytes()

                frame = AudioFrame(
                    channel_id=channel_id,
                    payload=payload,
                    timestamp=datetime.now(timezone.utc),
                )

                yield frame

            except asyncio.TimeoutError:
                # No audio data available, check if still running
                if not self._running:
                    break


async def create_audio_source(settings: RuntimeSettings) -> AudioSource:
    """
    Factory function to create the appropriate audio source implementation.

    Groups channels by device and creates multi-channel sources where appropriate.

    Args:
        settings: Runtime configuration settings

    Returns:
        AudioSource instance based on configuration

    Raises:
        ValueError: If device configuration is invalid
    """
    # Check for synthetic source override (for testing)
    source_type = os.getenv("ORPHEUS_AUDIO_SOURCE_TYPE", "").lower()
    if source_type == "synthetic":
        signal_type = os.getenv("ORPHEUS_AUDIO_SIGNAL_TYPE", "sine")
        amplitude = float(os.getenv("ORPHEUS_AUDIO_AMPLITUDE", "0.1"))
        frequency = float(os.getenv("ORPHEUS_AUDIO_FREQUENCY", "440.0"))
        channel_id = os.getenv("ORPHEUS_AUDIO_CHANNEL_ID", "synthetic")

        logger.info("Creating SyntheticAudioSource", testing_mode=True)
        return SyntheticAudioSource(
            sample_rate=settings.sample_rate,
            frame_duration_ms=settings.frame_duration_ms,
            max_pending_frames=settings.max_pending_frames,
            signal_type=signal_type,
            amplitude=amplitude,
            frequency=frequency,
            channel_id=channel_id,
        )

    # Load audio channel configuration from orpheus_common
    from orpheus_common.config import OrpheusConfig

    try:
        config = OrpheusConfig.get_instance()
        enabled_channels = [ch for ch in config.audio.channels if ch.enabled]

        if not enabled_channels:
            logger.warning("No enabled audio channels in configuration", fallback="default input")
            return DefaultAudioInputSource(
                sample_rate=settings.sample_rate,
                frame_duration_ms=settings.frame_duration_ms,
                max_pending_frames=settings.max_pending_frames,
                channel_id="default",
            )

        # Group channels by device type
        alsa_channels = []
        default_channels = []

        for channel in enabled_channels:
            device = channel.device

            if device is None or device == "":
                default_channels.append(channel)
            elif device.startswith("alsa://"):
                alsa_channels.append(channel)
            else:
                logger.warning(
                    "Unknown device format '%s' for channel %s, treating as default",
                    device,
                    channel.id,
                )
                default_channels.append(channel)

        # Create ALSA multi-channel source if we have ALSA channels
        if alsa_channels:
            # Convert to config dicts for ALSAAudioSource
            device_configs = [{"id": str(ch.id), "device": ch.device} for ch in alsa_channels]

            logger.info(
                "Creating ALSAAudioSource",
                channel_count=len(alsa_channels),
                channel_ids=[ch.id for ch in alsa_channels],
            )
            return ALSAAudioSource(
                sample_rate=settings.sample_rate,
                frame_duration_ms=settings.frame_duration_ms,
                max_pending_frames=settings.max_pending_frames,
                device_configs=device_configs,
            )

        # Fall back to default input for first channel
        if default_channels:
            channel = default_channels[0]
            if len(default_channels) > 1:
                logger.warning(
                    "Multiple default channels configured",
                    used_channel_id=channel.id,
                )

            logger.info("Creating DefaultAudioInputSource", channel_id=channel.id)
            return DefaultAudioInputSource(
                sample_rate=settings.sample_rate,
                frame_duration_ms=settings.frame_duration_ms,
                max_pending_frames=settings.max_pending_frames,
                channel_id=str(channel.id),
            )

        # Should never reach here, but fall back to default
        logger.warning("No valid channels found", fallback="default input")
        return DefaultAudioInputSource(
            sample_rate=settings.sample_rate,
            frame_duration_ms=settings.frame_duration_ms,
            max_pending_frames=settings.max_pending_frames,
            channel_id="default",
        )

    except Exception as e:
        logger.error("Failed to load audio configuration", error=str(e))
        logger.info("Falling back to default audio input")
        return DefaultAudioInputSource(
            sample_rate=settings.sample_rate,
            frame_duration_ms=settings.frame_duration_ms,
            max_pending_frames=settings.max_pending_frames,
        )
