"""PANNs-only loading and array validation, derived from the verified prototype."""

import hashlib
import math
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from orpheus_inference.protocol import MAX_PAYLOAD

TORCH_VERSION = "2.1.0a0+41361538.nv23.06"
CHECKPOINT_SHA256 = "dd3b4043a87d4ec13df8082c0fcfee3fb5084151808e47e060987a95eabdd142"


def no_shell(command: str) -> None:
    """PANNs must never wget over a missing/undersized checkpoint."""
    raise RuntimeError("shell downloads disabled in PANNs worker: %s" % command[:120])


class PannsRuntime:
    """Load only the validated Python/framework/checkpoint combination."""

    def __init__(self, checkpoint: str, max_seconds: float) -> None:
        # Matches Cnn14's 32 kHz input, 10 ms frames and 527 output classes.
        # Keep the two-frame tolerance used by the parent result validator.
        if not math.isfinite(max_seconds) or max_seconds <= 0:
            raise ValueError("max-seconds must be positive and finite")
        input_seconds = (MAX_PAYLOAD // 4) / 32000
        output_seconds = (MAX_PAYLOAD // (527 * 4) - 3) * 0.01
        if max_seconds > min(input_seconds, output_seconds):
            raise ValueError("max-seconds exceeds IPC payload capacity")
        self.checkpoint = Path(checkpoint)
        self.max_seconds = max_seconds
        self.sed = None

    def load(self) -> Dict[str, Any]:
        """Validate runtime/assets, load once and warm up before readiness."""
        if sys.version_info[:2] != (3, 8) or platform.machine() != "aarch64":
            raise RuntimeError("PANNs GPU worker requires Python 3.8 on Jetson aarch64")
        labels = Path(os.environ["HOME"]) / "panns_data" / "class_labels_indices.csv"
        if not labels.is_file() or not self.checkpoint.is_file():
            raise FileNotFoundError("PANNs checkpoint or staged labels missing")
        digest = hashlib.sha256()
        with self.checkpoint.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != CHECKPOINT_SHA256:
            raise ValueError("PANNs checkpoint differs from the validated Cnn14 checkpoint")
        os.system = no_shell
        import numpy as np
        import torch

        if torch.__version__ != TORCH_VERSION or np.__version__ != "1.24.4":
            raise RuntimeError("worker runtime differs from pinned Torch/numpy versions")
        if not torch.cuda.is_available() or not str(torch.version.cuda).startswith("11.4"):
            raise RuntimeError("validated CUDA 11.4 GPU runtime unavailable")
        torch.set_num_threads(1)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        from panns_inference import SoundEventDetection

        self.sed = SoundEventDetection(checkpoint_path=str(self.checkpoint), device="cuda")
        if str(self.sed.device) != "cuda":
            raise RuntimeError("PANNs did not select CUDA")
        # The archived baseline warmed on 35 s; cover configured maximum too.
        self.sed.inference(np.zeros((1, int(32000 * max(35, self.max_seconds))), dtype=np.float32))
        torch.cuda.synchronize()
        return {
            "model_loaded": True,
            "device": "cuda",
            "sample_rate": 32000,
            "num_classes": 527,
            "frame_duration_seconds": 0.01,
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "cuda_allocated_mib": torch.cuda.memory_allocated() // 1048576,
            "cuda_reserved_mib": torch.cuda.memory_reserved() // 1048576,
        }

    def infer(self, header: dict, body: bytearray) -> Tuple[dict, Any]:
        """Return little-endian float32 framewise scores, preserving model semantics."""
        import numpy as np

        shape = header.get("shape")
        if (
            header.get("dtype") != "<f4"
            or not isinstance(shape, list)
            or len(shape) != 1
            or type(shape[0]) is not int
            or not 1 <= shape[0] <= 32000 * self.max_seconds
        ):
            raise ValueError("invalid audio dtype/shape/length")
        if len(body) != shape[0] * 4:
            raise ValueError("audio byte length does not match shape")
        audio = np.frombuffer(body, dtype="<f4")
        if not np.isfinite(audio).all():
            raise ValueError("non-finite audio")
        start = time.monotonic()
        out = np.ascontiguousarray(self.sed.inference(audio[None, :])[0], dtype="<f4")
        if out.ndim != 2 or out.shape[1] != 527 or not np.isfinite(out).all():
            raise RuntimeError("invalid PANNs result")
        return {
            "dtype": "<f4",
            "shape": list(out.shape),
            "inference_ms": (time.monotonic() - start) * 1000,
        }, out
