"""Crow-tools classifier for vocalization detection.

This module provides the CrowClassifier class which wraps the multi-task
crow vocalization model and provides a high-level interface for classifying
audio embeddings.

The classifier:
1. Loads the pre-trained mt_70.pt model
2. Processes AVES embeddings (768-dimensional)
3. Returns structured detection results with:
   - Quality score (is it a crow?)
   - Dominant call type/behavior
   - Behavioral attributes (probabilities for each behavior)
   - Age classification (adult/juvenile)
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import torch
from orpheus_common.logging import get_logger
from orpheus_common.utils import select_torch_device

from .model import MultiTaskCrowNet

if TYPE_CHECKING:
    import numpy.typing as npt

logger = get_logger(__name__)


@dataclass
class CrowDetectionResult:
    """Result of crow vocalization classification.

    Attributes:
        is_crow: Whether the audio is classified as crow vocalization
        quality_score: Confidence that this is a crow (0-1)
        species: Identified species ("crow" or "unknown")
        call_type: Dominant behavior/call type (e.g., "alert", "rattle")
        attributes: Dictionary of behavioral probabilities and metadata
            Keys: alert, begging, soft_song, rattle, mob, age
    """

    is_crow: bool
    quality_score: float
    species: str
    call_type: str | None
    attributes: dict[str, any]  # Behavioral attributes and age


class CrowClassifier:
    """Multi-task classifier for crow vocalizations."""

    def __init__(self, model_path: str | Path, device: str = "auto") -> None:
        self.model_path = Path(model_path)
        # "auto" is byte-identical to the previous no-arg call; an explicit "cuda"
        # on a GPU-less host fails loud via select_torch_device rather than silently.
        self.device = torch.device(select_torch_device(device))

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found at {self.model_path}")

        logger.info("Loading classifier model", model_path=self.model_path, device=self.device)

        # 1. Init Architecture
        self.model = MultiTaskCrowNet(input_dim=768, hidden_dim=237)
        self.model.to(self.device)

        # 2. Load Weights
        checkpoint = torch.load(self.model_path, map_location=self.device)
        state_dict = checkpoint.get("state_dict", checkpoint.get("model", checkpoint))

        # 3. Clean Keys
        new_state_dict = OrderedDict()
        for k, v in state_dict.items():
            name = k.replace("module.", "")
            new_state_dict[name] = v

        # 4. Load
        try:
            self.model.load_state_dict(new_state_dict, strict=True)
        except RuntimeError as e:
            logger.warning("Strict load failed, trying non-strict", error=str(e))
            self.model.load_state_dict(new_state_dict, strict=False)

        self.model.eval()
        logger.info("Classifier model loaded successfully")

    def classify(
        self, embedding: npt.NDArray[np.float32], quality_threshold: float = 0.5
    ) -> CrowDetectionResult:
        embedding_tensor = torch.from_numpy(embedding).float()
        if embedding_tensor.dim() == 1:
            embedding_tensor = embedding_tensor.unsqueeze(0)

        embedding_tensor = embedding_tensor.to(self.device)

        with torch.no_grad():
            outputs = self.model(embedding_tensor)

        # 1. Quality (Is it a crow?)
        # quality_head output is [Batch, 2]. Softmax to get probs.
        quality_probs = torch.softmax(outputs["quality"], dim=-1)
        quality_score = quality_probs[0, 1].item()  # Index 1 = "Crow"

        # 2. Call Type / Behavior
        # Check all binary heads
        behaviors = {
            "alert": torch.sigmoid(outputs["alert"]).item(),
            "begging": torch.sigmoid(outputs["begging"]).item(),
            "soft_song": torch.sigmoid(outputs["softSong"]).item(),
            "rattle": torch.sigmoid(outputs["rattle"]).item(),
            "mob": torch.sigmoid(outputs["mob"]).item(),
        }

        # Find strongest behavior > 0.5
        best_behavior = None
        highest_score = 0.5
        for name, score in behaviors.items():
            if score > highest_score:
                highest_score = score
                best_behavior = name

        # 3. Species (Model doesn't support it, so we infer from quality)
        is_crow = quality_score >= quality_threshold
        species = "crow" if is_crow else "unknown"

        # 4. Attributes (Age/Count)
        age_probs = torch.softmax(outputs["age"], dim=-1)
        age_idx = torch.argmax(age_probs).item()
        age = "adult" if age_idx == 0 else "juvenile"  # Assumption on index mapping

        return CrowDetectionResult(
            is_crow=is_crow,
            quality_score=quality_score,
            species=species,
            call_type=best_behavior,
            attributes={"age": age, **behaviors},
        )
