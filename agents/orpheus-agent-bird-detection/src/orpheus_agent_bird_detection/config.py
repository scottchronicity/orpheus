"""Configuration management for bird detection agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from orpheus_common.config import OrpheusConfig
from orpheus_common.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BirdDetectionConfig:
    """Configuration for bird detection agent."""

    model_path: str
    confidence_threshold: float
    location_lat: Optional[float]
    location_lon: Optional[float]

    @classmethod
    def from_orpheus_config(cls, config: OrpheusConfig) -> BirdDetectionConfig:
        """Create BirdDetectionConfig from OrpheusConfig."""
        # Use _data for testability (mock configs in tests)
        # Robustly extract config dict for both prod and test
        bird_config = None
        for attr in ("_raw", "_data"):
            data = getattr(config, attr, None)
            if isinstance(data, dict):
                bird_config = data.get("bird_detection", {})
                if isinstance(bird_config, dict):
                    break
        if not isinstance(bird_config, dict):
            bird_config = {}

        # Always override model_path with ORPHEUS_DATA_ROOT if set
        data_root = os.environ.get("ORPHEUS_DATA_ROOT")
        yaml_model_path = bird_config.get("model_path", "/data/orpheus/models/birdnet.onnx")
        if data_root:
            model_path = f"{data_root}/models/birdnet.onnx"
            logger.debug(
                "model_path overridden by ORPHEUS_DATA_ROOT",
                model_path=model_path,
            )
        else:
            model_path = yaml_model_path
            logger.debug("model_path from YAML", model_path=model_path)

        # Use OrpheusConfig.site as fallback for location if not in bird_detection config
        site = getattr(config, "site", None)
        default_lat = site.lat if site is not None and site.lat is not None else 43.965542
        default_lon = site.lon if site is not None and site.lon is not None else -84.943588
        return cls(
            model_path=model_path,
            confidence_threshold=float(bird_config.get("confidence_threshold", 0.5)),
            location_lat=float(bird_config.get("location_lat", default_lat)),
            location_lon=float(bird_config.get("location_lon", default_lon)),
        )


def load_config(orpheus_config: OrpheusConfig) -> BirdDetectionConfig:
    """
    Load bird detection configuration.

    Args:
        orpheus_config: orpheus config from which to load bird detection config

    Returns:
        BirdDetectionConfig instance
    """
    return BirdDetectionConfig.from_orpheus_config(orpheus_config)
