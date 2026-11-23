"""AVES embedder for crow detection agent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import fairseq.checkpoint_utils
import numpy as np
import torch
from orpheus_common.logging import get_logger
from orpheus_common.utils import select_torch_device

if TYPE_CHECKING:
    import numpy.typing as npt

logger = get_logger(__name__)


class AVESEmbedder:
    """AVES audio embedder for crow detection."""

    def __init__(
        self, model_path: str | Path, sample_rate: int = 16000, device: str = "auto"
    ) -> None:
        """
        Initialize AVES embedder.

        Args:
            model_path: Path to AVES model file (e.g., aves-base-bio.pt)
            sample_rate: Expected audio sample rate (16kHz for AVES)
            device: Requested torch device ("auto"→cuda-if-available-else-cpu,
                "cpu", "cuda", …). Resolved via select_torch_device so a "cuda"
                on a GPU-less host fails loud rather than silently. Default
                "auto" is byte-identical to the previous no-arg behavior.
        """
        self.model_path = Path(model_path)
        self.sample_rate = sample_rate
        self.device = torch.device(select_torch_device(device))

        if not self.model_path.exists():
            msg = f"AVES model not found at {self.model_path}"
            raise FileNotFoundError(msg)

        logger.info("Loading AVES model", model_path=self.model_path, device=self.device)

        # Load the AVES model using fairseq utilities
        logger.info("Loading model using fairseq.checkpoint_utils...")
        models, _cfg, _task = fairseq.checkpoint_utils.load_model_ensemble_and_task(
            [str(self.model_path)]
        )
        self.model = models[0]
        self.model.to(self.device)
        self.model.eval()
        logger.info("AVES model loaded successfully")

    def generate_embedding(self, audio: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        """
        Generate embedding for audio segment.
        """
        # Convert numpy array to torch tensor
        audio_tensor = torch.from_numpy(audio).float()

        # Add batch dimension if needed
        if audio_tensor.dim() == 1:
            audio_tensor = audio_tensor.unsqueeze(0)

        # Move to device
        audio_tensor = audio_tensor.to(self.device)

        # Generate embedding
        with torch.no_grad():
            # 1. Disable masking (avoids the ~NoneType error)
            # 2. Request features_only (returns a dict with intermediate layers)
            outputs = self.model(audio_tensor, mask=False, features_only=True)

            # 3. Extract the feature sequence [Batch, Time, 768]
            features = outputs["x"]

            # 4. Mean Pool: Average across time (dim 1) to get [Batch, 768]
            embedding = features.mean(dim=1)

        # Convert back to numpy
        return embedding.cpu().numpy()

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimensionality."""
        # AVES-base-bio produces 768-dimensional embeddings
        return 768
