"""SEDModel adapter; only inference infrastructure crosses the environment boundary."""

from __future__ import annotations

import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
from orpheus_inference.client import WorkerClient, WorkerOptions
from orpheus_inference.protocol import ProtocolError
from orpheus_inference.resources import mem_available_mib

from .config import GPUWorkerConfig
from .model import PANNsCnn14SED, SEDModel


def auto_worker_available(config: GPUWorkerConfig) -> bool:
    """Conservative selection before loading: a configured Jetson with host headroom.

    Runtime/handshake failures after selection are visible degraded recovery,
    never a second, implicit CPU load while driver allocations may remain.
    """
    available = mem_available_mib()
    return (
        platform.system() == "Linux"
        and platform.machine() == "aarch64"
        and Path(config.python).is_file()
        and os.access(config.python, os.X_OK)
        and available is not None
        and available >= config.start_memory_mib
    )


class WorkerSEDModel(SEDModel):
    """PANNs proxy with the same input/output contract as the in-process model."""

    sample_rate = PANNsCnn14SED.PANNS_SAMPLE_RATE
    num_classes = PANNsCnn14SED.PANNS_NUM_CLASSES
    frame_duration_seconds = PANNsCnn14SED.PANNS_FRAME_DURATION_SECONDS

    def __init__(self, checkpoint: Path, config: GPUWorkerConfig) -> None:
        self.config = config
        if not Path(config.python).is_file():
            raise FileNotFoundError("GPU worker Python missing; see the opt-in install guide")
        data_root = Path(os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus"))
        home = data_root / "gpu-workers" / "panns"
        labels = home / "panns_data" / "class_labels_indices.csv"
        labels.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).parent / "data" / "panns_class_labels_indices.csv", labels)
        env = dict(os.environ)
        for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            env.pop(name, None)
        env.update(
            HOME=str(home),
            PYTHONUNBUFFERED="1",
            OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
            MKL_NUM_THREADS="1",
            NUMBA_NUM_THREADS="1",
        )
        for name, subdir in (
            ("MPLCONFIGDIR", "matplotlib"),
            ("XDG_CACHE_HOME", "cache"),
            ("NUMBA_CACHE_DIR", "numba"),
            ("TMPDIR", "tmp"),
            ("CUDA_CACHE_PATH", "cuda"),
        ):
            directory = home / subdir
            directory.mkdir(parents=True, exist_ok=True)
            env[name] = str(directory)
        self.client = WorkerClient(
            [
                config.python,
                "-I",
                "-u",
                "-m",
                "orpheus_worker_panns",
                "--checkpoint",
                str(checkpoint.resolve()),
                "--floor-mib",
                str(config.floor_memory_mib),
                "--max-seconds",
                str(config.max_clip_seconds),
            ],
            env,
            WorkerOptions(
                startup_timeout=config.startup_timeout_seconds,
                request_timeout=config.request_timeout_seconds,
                start_memory_mib=config.start_memory_mib,
                floor_memory_mib=config.floor_memory_mib,
                restart_backoff=config.restart_backoff_seconds,
                max_starts=config.max_starts,
                restart_window=config.restart_window_seconds,
            ),
            expected_ready={
                "model_loaded": True,
                "device": "cuda",
                "sample_rate": 32000,
                "num_classes": 527,
                "frame_duration_seconds": 0.01,
            },
        )
        self.client.start()

    def health(self) -> dict[str, Any]:
        """Non-blocking cached worker readiness, failures and runtime provenance."""
        return self.client.snapshot()

    def predict(self, audio_mono: np.ndarray) -> np.ndarray:
        return self.predict_before(
            audio_mono, time.monotonic() + self.config.request_timeout_seconds
        )

    def predict_before(self, audio_mono: np.ndarray, deadline: float) -> np.ndarray:
        """Start before the clip expires and finish within the worker request timeout."""
        audio = np.ascontiguousarray(audio_mono, dtype="<f4")
        if (
            audio.ndim != 1
            or not 0 < audio.size <= self.sample_rate * self.config.max_clip_seconds
            or not np.isfinite(audio).all()
        ):
            raise ValueError("invalid worker audio shape, length or samples")

        def validate(header: dict, body: bytearray) -> None:
            shape = header.get("shape")
            if (
                header.get("type") != "result"
                or header.get("dtype") != "<f4"
                or not isinstance(shape, list)
                or len(shape) != 2
                or any(type(n) is not int for n in shape)
                or shape[1] != self.num_classes
                or shape[0] < 1
                or abs(shape[0] - (audio.size // 320 + 1)) > 2
                or len(body) != shape[0] * shape[1] * 4
            ):
                raise ProtocolError("invalid PANNs output shape/dtype/size")
            scores = np.frombuffer(body, dtype="<f4")
            if not np.isfinite(scores).all() or (scores < 0).any() or (scores > 1).any():
                raise ProtocolError("invalid PANNs probabilities")

        header, body = self.client.request(
            {"type": "infer", "dtype": "<f4", "shape": [int(audio.size)]},
            audio,
            start_deadline=deadline,
            validate=validate,
        )
        return np.frombuffer(body, dtype="<f4").reshape(header["shape"])

    def close(self) -> None:
        """Stop supervision and release the model process."""
        self.client.close()
