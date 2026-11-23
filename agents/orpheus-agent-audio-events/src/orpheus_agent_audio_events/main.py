"""Main entry point for the audio-events detection agent."""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import soundfile as sf
from orpheus_common import DetectionDB, OrpheusConfig
from orpheus_common.actor import Actor
from orpheus_common.detection import Detection, TaxonomyRef, TemporalInterval
from orpheus_common.event_sourcing import ensure_domain_stream, shadow_publish
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.utils import select_torch_device
from pydantic import ValidationError

from . import audioset_ontology
from .audioset_ontology import AudioSetLabel
from .config import AudioEventsConfig, load_config
from .model import SEDModel, build_model
from .post_processing import ClassifiedClip, post_process
from .worker_model import WorkerSEDModel, auto_worker_available

logger = get_logger(__name__)

# A clip whose worker exchange fails on two separately started workers is the
# cause of the failure (WorkerClient restarts the worker after every failed
# exchange). It is then accounted under clips_rejected["worker_error"] instead of
# being retried, which would reload the model indefinitely.
_WORKER_ATTEMPTS_PER_CLIP = 2


class AudioEventsAgent(Actor):
    """Audio-events detection agent.

    Subscribes to ``orpheus/audio/motion/events`` clips, runs PANNs SED, and
    emits one ``audio.classified`` ``Detection`` per surviving (class, clip)
    with intra-clip ``intervals`` populated.

    Lifecycle (bus connect/subscribe, signal handling, the 30s heartbeat, graceful
    shutdown) comes from ``Actor``; this fills the audio-events hooks. ``self.bus``
    is the EventBus; ``self.config`` the audio-events config (the OrpheusConfig is
    ``self.orpheus_config``, set by the base). See ``docs/designs/audio-events-agent.md``
    and ADR 0011.
    """

    def __init__(
        self,
        config_path: Path | None = None,
        *,
        model: SEDModel | None = None,
        labels: dict[int, AudioSetLabel] | None = None,
        detection_db: DetectionDB | None = None,
        orpheus_config: OrpheusConfig | None = None,
    ) -> None:
        """Initialise the agent.

        Args:
            config_path: Optional path override for ``orpheus.yaml``.
            model: Inject a SEDModel (typically a ``DeterministicFakeSED``
                in tests). When ``None`` the agent builds one from config in
                ``on_setup()``.
            labels: Inject the AudioSet labels dict (loaded from CSV by default).
            detection_db: Inject a ``DetectionDB`` (in-memory in tests).
            orpheus_config: Inject an already-resolved configuration (e.g. an isolated experiment).
        """
        self.config: AudioEventsConfig = (
            AudioEventsConfig.from_orpheus_config(orpheus_config)
            if orpheus_config is not None
            else load_config(config_path)
        )
        super().__init__(
            "audio-events",
            orpheus_config
            if orpheus_config is not None
            else OrpheusConfig.get_instance(config_path=config_path),
        )

        self.model: SEDModel | None = model
        self.labels: dict[int, AudioSetLabel] | None = labels
        self.detection_db: DetectionDB | None = detection_db

        # §3 event-sourcing shadow: whether to mirror each emitted detection to
        # the bounded durable domain stream IN ADDITION to the DB save. Resolved
        # in on_started() (post-connect). Off by default; no-op on mqtt; the DB
        # stays the source of truth. See docs/designs/event-sourcing-determinism-contract.md.
        self._shadow_publish = False

        # Resolved torch device ("cuda"/"cpu"), set in on_setup when the agent
        # builds its own model. Surfaced in health so a silent CPU fallback on
        # the Jetson is visible beyond one startup log line. None when a model
        # is injected (tests) — no resolution happened.
        self._resolved_device: str | None = None

        # Statistics (audio-events-specific; richer than ActorStats — surfaced via
        # the health payload so the UI can show p50/p95 latency + error info).
        self.events_processed = 0
        self.detections_emitted = 0
        self._inference_latencies_ms: list[float] = []
        self._inference_latency_window = 100
        self.errors_count = 0
        self.last_error: str | None = None
        self.last_inference_at: str | None = None
        self.started_at: str | None = None
        self._worker_backend = self.config.backend == "gpu_worker"
        if self.config.backend == "auto":
            self._worker_backend = (
                self.config.device != "cpu"
                and self.config.model_variant == "cnn14_sed"
                and auto_worker_available(self.config.gpu_worker)
            )
        self._accepting = True
        self._force_shutdown = threading.Event()
        self._submission_lock = threading.Lock()
        self._queued_at: dict[object, float] = {}
        self.clips_rejected = {
            "overload": 0,
            "expired": 0,
            "unavailable": 0,
            "memory": 0,
            "too_long": 0,
            "shutdown": 0,
            "worker_error": 0,
        }
        self._admission = (
            threading.BoundedSemaphore(1 + self.config.gpu_worker.max_pending_clips)
            if self._worker_backend
            else None
        )
        # Bounded concurrent clip processing. A new audio.motion tick submits a new
        # clip WITHOUT cancelling an in-flight one — older instances run to
        # completion. The pool is small so SED inference
        # can't thrash the Jetson's shared RAM/GPU; excess ticks queue. _stats_lock
        # guards the counters/window mutated from these worker threads.
        self._executor = ThreadPoolExecutor(
            max_workers=1 if self._worker_backend else self.config.max_concurrent_clips,
            thread_name_prefix="audio-events-sed",
        )
        self._inflight: set[Future] = set()
        self._stats_lock = threading.Lock()

    def _record_inference_latency(self, latency_ms: float) -> None:
        """Append to the rolling window. Bounded by ``_inference_latency_window``
        to keep memory flat regardless of uptime. Called from worker threads, so
        the window + ``last_inference_at`` are mutated under ``_stats_lock``."""
        with self._stats_lock:
            self._inference_latencies_ms.append(latency_ms)
            if len(self._inference_latencies_ms) > self._inference_latency_window:
                # Drop from the front — simple sliding window.
                self._inference_latencies_ms.pop(0)
            self.last_inference_at = datetime.now(timezone.utc).isoformat()

    def _percentile(self, values: list[float], p: float) -> float:
        """Linear-interpolation percentile (numpy-free for Jetson deps)."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        k = (len(sorted_values) - 1) * p
        f = int(k)
        c = min(f + 1, len(sorted_values) - 1)
        if f == c:
            return sorted_values[f]
        return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])

    def _build_health_payload(self) -> dict[str, Any]:
        """The startup + heartbeat payload: uptime, model load status, processed
        counts, rolling latency percentiles, recent error info. Cheap to compute."""
        worker = self.model.health() if isinstance(self.model, WorkerSEDModel) else None
        with self._stats_lock:
            pending = len(self._queued_at)
            oldest = min(self._queued_at.values(), default=None)
        queue_age = time.monotonic() - oldest if oldest is not None else 0.0
        payload = {
            "status": "online",
            "model_loaded": worker["ready"] if worker is not None else self.model is not None,
            "backend": "gpu_worker" if self._worker_backend else "inprocess",
            "worker": worker,
            # The effective floor (default included), for the dashboard's GPU panel.
            "floor_memory_mib": (
                self.config.gpu_worker.floor_memory_mib if self._worker_backend else None
            ),
            "clips_rejected": dict(self.clips_rejected),
            "pending_clips": pending,
            "oldest_pending_age_seconds": round(queue_age, 3),
            "model_variant": self.config.model_variant,
            "started_at": self.started_at,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "events_processed": self.events_processed,
            "detections_emitted": self.detections_emitted,
            "errors_count": self.errors_count + (worker["failures"] if worker else 0),
            "last_error": self.last_error or (worker["last_error"] if worker else None),
            # Whether the event-sourcing shadow is actually recording (off by default;
            # a silent self-disable on mqtt / stream_ensure error is otherwise invisible).
            "event_sourcing_shadow": self._shadow_publish,
            # Resolved torch device (additive; None when the model was injected).
            "device": self._resolved_device,
            # Clips submitted but not yet finished (running + queued) — queue
            # depth visibility for the bounded executor.
            "inflight_clips": len(self._inflight),
            "last_inference_at": self.last_inference_at,
            "inference_latency_ms": {
                "samples": len(self._inference_latencies_ms),
                "p50": round(self._percentile(self._inference_latencies_ms, 0.5), 1),
                "p95": round(self._percentile(self._inference_latencies_ms, 0.95), 1),
                "max": round(
                    max(self._inference_latencies_ms) if self._inference_latencies_ms else 0.0,
                    1,
                ),
            },
        }
        # A blocked callback (full GPU queue) backs events up in the bus's bounded
        # dispatch queue, which drops the oldest; this is where that shows.
        stats_fn = getattr(self.bus, "dispatch_stats", None)
        if callable(stats_fn):
            try:
                stats = stats_fn()
            except Exception:  # health must never fail on a stats read
                stats = None
            if isinstance(stats, dict):
                payload["bus_dispatch"] = stats
        return payload

    # ------------------------------------------------------------------
    # Actor hooks
    # ------------------------------------------------------------------
    def enabled(self) -> bool:
        return self.config.enabled

    async def on_setup(self) -> None:
        """Load the SED model + AudioSet labels + the detection DB."""
        logger.info("Starting Audio Events Detection Agent")

        # Load model (skip if injected by tests).
        if self.model is None and self._worker_backend:
            if self.config.model_variant != "cnn14_sed":
                raise ValueError("GPU worker supports only cnn14_sed")
            # No parent torch import or CUDA probe; readiness belongs to the child.
            self.model = WorkerSEDModel(Path(self.config.model_path), self.config.gpu_worker)
            self._resolved_device = "cuda"
        if self.model is None:
            # Resolve "auto" → cuda-if-available-else-cpu (survivable); an
            # explicit device="cuda" with no GPU fails loud here with a clear
            # message instead of crashing deep inside the model constructor.
            # Kept on self so health surfaces a silent CPU fallback.
            resolved_device = select_torch_device(self.config.device)
            self._resolved_device = resolved_device
            logger.info(
                "Loading SED model",
                variant=self.config.model_variant,
                model_path=self.config.model_path,
                device=resolved_device,
            )
            try:
                self.model = build_model(
                    variant=self.config.model_variant,
                    checkpoint_path=Path(self.config.model_path),
                    device=resolved_device,
                )
                logger.info("SED model loaded successfully")
            except FileNotFoundError:
                logger.error(  # noqa: TRY400
                    "SED model file not found",
                    path=self.config.model_path,
                )
                logger.info("Run 'make download-models' or update config")
                raise

        # Load AudioSet labels (skip if injected).
        if self.labels is None:
            try:
                self.labels = audioset_ontology.load_labels()
                logger.info("AudioSet labels loaded", count=len(self.labels))
            except FileNotFoundError:
                logger.exception("AudioSet labels CSV missing")
                raise

        # Initialise DetectionDB.
        if self.detection_db is None:
            self.detection_db = DetectionDB()
            logger.info("DetectionDB initialized")

        self.started_at = datetime.now(timezone.utc).isoformat()

    async def on_started(self) -> None:
        """Post-connect: ensure the bounded durable domain stream once (off by
        default; no-op on mqtt). Returns whether to shadow-publish each emitted
        detection to it. The bus is connected by now (the base runs this after
        connect); the DB stays the source of truth."""
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
        return [(self.config.input_topic, self._on_audio_motion_event)]

    def health_payload(self, phase: str) -> dict[str, Any]:
        # startup + heartbeat carry the full payload (incl. model_loaded + latency
        # stats); shutdown is the offline subset. Shapes preserved exactly.
        if phase == "shutdown":
            return {
                "status": "offline",
                "events_processed": self.events_processed,
                "detections_emitted": self.detections_emitted,
                "errors_count": self.errors_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        return self._build_health_payload()

    async def on_stopping(self) -> None:
        with self._submission_lock:
            self._accepting = False
        with self._stats_lock:
            pending = list(self._inflight)
        if self._worker_backend and pending:
            loop = asyncio.get_running_loop()
            _, unfinished = await loop.run_in_executor(
                None,
                lambda: wait(
                    pending, timeout=self.config.gpu_worker.shutdown_drain_timeout_seconds
                ),
            )
            if unfinished:
                # A permanent worker outage cannot hold Actor.shutdown forever.
                # Signal waiting jobs, stop the child to interrupt any active IPC,
                # then let the executor account for cancelled/unserviceable work.
                self._force_shutdown.set()
                logger.error(
                    "GPU worker drain timed out; accepted clips remain unclassified",
                    pending_clips=len(unfinished),
                    drain_timeout_seconds=self.config.gpu_worker.shutdown_drain_timeout_seconds,
                )
                if isinstance(self.model, WorkerSEDModel):
                    await loop.run_in_executor(None, self.model.close)
                await loop.run_in_executor(
                    None, lambda: self._executor.shutdown(wait=True, cancel_futures=True)
                )
                return
        if not self._worker_backend and pending:
            loop = asyncio.get_running_loop()
            _, unfinished = await loop.run_in_executor(
                None,
                lambda: wait(pending, timeout=self.config.shutdown_drain_timeout_seconds),
            )
            if unfinished:
                # Bounded like the GPU path: queued clips are cancelled and counted
                # (clips_rejected.shutdown); a clip already running finishes.
                logger.error(
                    "Audio-events drain timed out; queued clips remain unclassified",
                    pending_clips=len(unfinished),
                    drain_timeout_seconds=self.config.shutdown_drain_timeout_seconds,
                )
                await loop.run_in_executor(
                    None, lambda: self._executor.shutdown(wait=True, cancel_futures=True)
                )
                return
        # The worker remains available throughout a successful drain so accepted
        # clips publish before Actor disconnects the bus.
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._executor.shutdown(wait=True, cancel_futures=False)
        )
        if isinstance(self.model, WorkerSEDModel):
            await asyncio.get_running_loop().run_in_executor(None, self.model.close)

    async def on_shutdown(self) -> None:
        logger.info(
            "Agent shutdown complete",
            events_processed=self.events_processed,
            detections_emitted=self.detections_emitted,
            clips_rejected=dict(self.clips_rejected),
        )

    # ------------------------------------------------------------------
    # MQTT handler
    # ------------------------------------------------------------------
    def _on_audio_motion_event(self, _topic: str, payload: Any) -> None:
        """Handle an audio.motion event from MQTT."""
        self.events_processed += 1

        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = json.loads(bytes(payload).decode("utf-8"))
            except Exception:
                logger.exception("Failed to decode MQTT payload")
                return

        try:
            source_detection: Detection | None = None
            try:
                source_detection = Detection.model_validate(payload)
            except ValidationError:
                logger.debug("Payload did not validate against Detection schema; skipping")
                return

            event_id = source_detection.event_id
            audio_clip_path = source_detection.audio_clip_path
            if not audio_clip_path:
                logger.warning("audio.motion event missing audio_clip_path", event_id=event_id)
                return

            audio_path = Path(audio_clip_path)
            if not audio_path.exists():
                logger.error("Audio file not found", path=str(audio_path), event_id=event_id)
                return

            self._submit_processing(audio_path, source_detection)

        except Exception as exc:  # pylint: disable=broad-except
            self._record_error(exc)
            logger.error(
                "Error processing audio.motion event",
                error=str(exc),
                exc_info=True,
            )

    def _record_error(self, exc: Exception) -> None:
        """Bump the error counters under the lock (callable from worker threads)."""
        with self._stats_lock:
            self.errors_count += 1
            self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"

    def _submit_processing(self, audio_path: Path, source: Detection) -> None:
        """Submit work, applying blocking admission backpressure to the GPU path."""
        if self._admission is None:
            with self._submission_lock:
                if not self._accepting:
                    self._reject_clip("shutdown")
                    return
                self._submit_accepted_clip(audio_path, source)
            return

        while True:
            with self._submission_lock:
                if not self._accepting:
                    self._reject_clip("shutdown")
                    return
                if self._admission.acquire(blocking=False):
                    self._submit_accepted_clip(audio_path, source)
                    return
            # Do not hold the lifecycle lock while waiting: shutdown must be able
            # to stop admission and release blocked bus callbacks.
            if self._admission.acquire(timeout=0.1):
                with self._submission_lock:
                    if not self._accepting:
                        self._admission.release()
                        self._reject_clip("shutdown")
                        return
                    self._submit_accepted_clip(audio_path, source)
                    return

    def _submit_accepted_clip(self, audio_path: Path, source: Detection) -> None:
        if self._worker_backend:
            deadline = self._clip_deadline(source)
            ticket = object()
            with self._stats_lock:
                self._queued_at[ticket] = time.monotonic()
            try:
                future = self._executor.submit(
                    self._process_worker_clip, audio_path, source, deadline, ticket
                )
            except RuntimeError:
                self._forget_pending(ticket)
                self._admission.release()
                self._reject_clip("shutdown")
                return
            future.add_done_callback(lambda _future: self._forget_pending(ticket))
            future.add_done_callback(lambda _future: self._admission.release())
        else:
            future = self._executor.submit(self._process_safely, audio_path, source)
        with self._stats_lock:
            self._inflight.add(future)
        future.add_done_callback(self._on_processing_done)

    def _reject_clip(self, reason: str) -> None:
        with self._stats_lock:
            self.clips_rejected[reason] += 1

    def _forget_pending(self, ticket: object) -> None:
        with self._stats_lock:
            self._queued_at.pop(ticket, None)

    def _clip_deadline(self, source: Detection) -> float | None:
        ttl = self.config.gpu_worker.clip_ttl_seconds
        if ttl is None:
            return None
        # Motion timestamp marks clip start. Measure the age from recording end.
        duration = float((source.metadata or {}).get("duration_seconds", 0.0))
        if (
            not math.isfinite(duration)
            or not 0 <= duration <= self.config.gpu_worker.max_clip_seconds
        ):
            return time.monotonic()
        age = max(0.0, (datetime.now(timezone.utc) - source.timestamp).total_seconds() - duration)
        return time.monotonic() + ttl - age

    def _worker_admissible(self) -> bool:
        if not isinstance(self.model, WorkerSEDModel):
            return False
        return bool(self.model.health()["ready"])

    def _wait_for_worker(self, deadline: float | None) -> str | None:
        """Wait for supervised recovery, or return an explicit stop/TTL reason."""
        while True:
            if self._force_shutdown.is_set():
                return "shutdown"
            if deadline is not None and time.monotonic() >= deadline:
                return "expired"
            if self._worker_admissible():
                return None
            time.sleep(0.1)

    def _process_worker_clip(
        self, path: Path, source: Detection, deadline: float | None, ticket: object
    ) -> None:
        """Wait for worker recovery, then process this accepted clip in FIFO order."""
        self._forget_pending(ticket)
        try:
            reason = (
                "shutdown"
                if self._force_shutdown.is_set()
                else self._wait_for_worker(deadline)
            )
            if reason is None:
                # Read only the audio header before allocating decoded/resampled arrays.
                info = sf.info(path)
                if info.duration > self.config.gpu_worker.max_clip_seconds:
                    reason = "too_long"
            if reason is None:
                reason = self._classify_with_recovery(path, source, deadline)
            if reason is not None:
                self._reject_clip(reason)
        except Exception as exc:
            if self._force_shutdown.is_set():
                self._reject_clip("shutdown")
                return
            if deadline is not None and time.monotonic() >= deadline:
                self._reject_clip("expired")
                return
            self._record_error(exc)
            logger.exception("GPU clip failed", error=str(exc), clip=str(path))

    def _classify_with_recovery(
        self, path: Path, source: Detection, deadline: float | None
    ) -> str | None:
        """Classify one accepted clip, waiting through worker recovery.

        Returns None once classified, or the clips_rejected reason it ends with.
        """
        exchange_failures = 0
        while True:
            if self._force_shutdown.is_set():
                return "shutdown"
            failures_before = self.model.health()["failures"]
            try:
                self._process_audio_file(path, source, deadline=deadline)
            except Exception as exc:
                # WorkerClient marks itself unready before raising an IPC or
                # child failure. No Detection has been emitted yet (inference
                # precedes post-processing/publication), so retrying this clip
                # after supervised recovery cannot duplicate domain output.
                health = self.model.health()
                if health["ready"] and health["failures"] == failures_before:
                    raise
                if health["failures"] != failures_before:
                    exchange_failures += 1
                if exchange_failures >= _WORKER_ATTEMPTS_PER_CLIP:
                    # The exchange failed on a worker that had just been
                    # restarted after this clip's previous failure, so the clip,
                    # not the worker, is the cause. Retrying it again would only
                    # reload the model forever.
                    self._record_error(exc)
                    logger.exception(
                        "PANNs could not classify this clip on a freshly started "
                        "worker; giving up on it",
                        event_id=source.event_id,
                        clip=str(path),
                        attempts=exchange_failures,
                    )
                    return "worker_error"
                logger.warning(
                    "PANNs exchange failed; retaining clip until worker recovery",
                    event_id=source.event_id,
                    error=str(exc),
                )
                reason = self._wait_for_worker(deadline)
                if reason is not None:
                    return reason
            else:
                return None

    def _process_safely(self, audio_path: Path, source: Detection) -> None:
        """Worker-thread wrapper: run the pipeline, capturing errors as stats so a
        single bad clip can't kill the pool's worker thread."""
        try:
            self._process_audio_file(audio_path, source)
        except Exception as exc:  # pylint: disable=broad-except
            self._record_error(exc)
            logger.error(
                "Error processing audio clip",
                clip=str(audio_path),
                error=str(exc),
                exc_info=True,
            )

    def _on_processing_done(self, future: Future) -> None:
        """Drop the finished future from the in-flight set (done-callback thread)."""
        if future.cancelled():
            self._reject_clip("shutdown")
        with self._stats_lock:
            self._inflight.discard(future)

    def wait_inflight(self, timeout: float | None = None) -> None:
        """Block until all in-flight clip processing completes. Used by the shutdown
        drain and by tests that submit a clip then assert on its emitted detections."""
        with self._stats_lock:
            pending = list(self._inflight)
        for future in pending:
            future.result(timeout=timeout)

    # ------------------------------------------------------------------
    # Inference pipeline
    # ------------------------------------------------------------------
    def _process_audio_file(
        self, audio_path: Path, source: Detection, *, deadline: float | None = None
    ) -> None:
        """Run SED on a clip and emit one Detection per surviving class."""
        if self.model is None or self.labels is None:
            logger.error("Agent not fully initialised — model or labels missing")
            return

        start_time = time.monotonic()
        audio = self._load_and_preprocess(audio_path)
        if audio is None:
            return

        if deadline is not None and isinstance(self.model, WorkerSEDModel):
            if time.monotonic() >= deadline:
                self._reject_clip("expired")
                return
            framewise_output = self.model.predict_before(audio, deadline)
            if time.monotonic() >= deadline:
                self._reject_clip("expired")
                return
        else:
            framewise_output = self.model.predict(audio)
        classified_clips = post_process(
            framewise_output,
            frame_duration_seconds=self.model.frame_duration_seconds,
            clip_threshold=self.config.clip_threshold,
            frame_threshold=self.config.frame_threshold,
            bridge_ms=self.config.bridge_ms,
            min_interval_ms=self.config.min_interval_ms,
            max_labels_per_clip=self.config.max_labels_per_clip,
            allowed_class_indices=list(self.labels.keys()),
        )
        inference_time_ms = int((time.monotonic() - start_time) * 1000)
        # Layer-3-adjacent health surface: record latency to the rolling
        # window so the health heartbeat can report p50/p95 stats.
        self._record_inference_latency(float(inference_time_ms))

        logger.info(
            "SED inference complete",
            event_id=source.event_id,
            clip=str(audio_path),
            inference_time_ms=inference_time_ms,
            num_labels=len(classified_clips),
        )

        if deadline is not None and time.monotonic() >= deadline:
            self._reject_clip("expired")
            return
        for clip in classified_clips:
            self._emit_detection(clip, audio_path, source, inference_time_ms)

    def _load_and_preprocess(self, audio_path: Path) -> np.ndarray | None:
        """Load audio, downmix to mono, resample to the model's SR."""
        if self.model is None:
            return None
        try:
            audio, sample_rate = sf.read(audio_path)
        except Exception:
            logger.exception("Failed to load audio file", path=str(audio_path))
            return None

        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        target_sr = self.model.sample_rate
        if sample_rate != target_sr:
            audio = librosa.resample(
                audio,
                orig_sr=sample_rate,
                target_sr=target_sr,
                res_type="kaiser_fast",
            )

        return audio.astype(np.float32, copy=False)

    def _emit_detection(
        self,
        clip: ClassifiedClip,
        audio_path: Path,
        source: Detection,
        inference_time_ms: int,
    ) -> None:
        """Construct and publish one Detection for a single (class, clip) result."""
        if self.labels is None or self.bus is None or self.detection_db is None:
            logger.error("Agent not fully initialised; cannot emit detection")
            return

        label = self.labels.get(clip.class_index)
        if label is None:  # pragma: no cover — defensive; allowed_class_indices filters first
            logger.debug(
                "Skipping class index without a label",
                class_index=clip.class_index,
            )
            return

        species_code = audioset_ontology.species_code_for(label.machine_id)
        intervals: list[TemporalInterval] = [
            TemporalInterval(
                start_seconds=iv.start_seconds,
                end_seconds=iv.end_seconds,
                confidence=iv.interval_score,
            )
            for iv in clip.intervals
        ]
        taxonomy = TaxonomyRef(
            namespace="audioset",
            id=label.machine_id,
            common_name=label.display_name,
        )

        detection = Detection(
            timestamp=datetime.now(timezone.utc),
            detection_type="audio.classified",
            channel=source.channel,
            species_code=species_code,
            species_common=label.display_name,
            confidence=clip.clip_score,
            audio_clip_path=str(audio_path),
            context=source.context,
            source_event_id=source.event_id,
            # Chain root: inherit from the source audio.motion if it has
            # one; otherwise the source IS the audio.motion (this agent
            # is one hop downstream). See cross-classifier-identity §1.1.
            root_event_id=Detection.derive_root_event_id(source),
            intervals=intervals,
            taxonomy=taxonomy,
            metadata={
                "model": self.config.model_variant,
                "class_index": clip.class_index,
                "clip_threshold": self.config.clip_threshold,
                "frame_threshold": self.config.frame_threshold,
                "inference_time_ms": inference_time_ms,
            },
        )

        self.bus.publish(
            self.config.output_topic,
            detection.model_dump(mode="json"),
        )
        self.detection_db.save(detection)
        # §3 event-sourcing shadow: mirror to the durable domain stream keyed by
        # event_id, AFTER the DB save. Off by default; best-effort (never raises).
        if self._shadow_publish:
            shadow_publish(self.bus, self.config.output_topic, detection)
        with self._stats_lock:
            self.detections_emitted += 1


def main() -> None:
    """CLI entry point."""
    # Configure logging BEFORE the Actor's enabled() gate: a disabled agent never
    # runs on_setup, but its "disabled in configuration; not starting" warning
    # must still go through the configured handlers.
    setup_logging("orpheus-agent-audio-events", level="INFO")
    agent = AudioEventsAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
