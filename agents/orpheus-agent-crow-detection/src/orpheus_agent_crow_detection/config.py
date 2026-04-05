"""Configuration management for crow detection agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from orpheus_common.config import OrpheusConfig


@dataclass
class CrowDetectionConfig:
    """Configuration for crow detection agent."""

    enabled: bool
    quality_threshold: float
    embedder_model_path: str
    classifier_model_path: str
    embedder_sample_rate: int

    @classmethod
    def from_orpheus_config(cls, config: OrpheusConfig) -> CrowDetectionConfig:
        """Create CrowDetectionConfig from OrpheusConfig."""
        crow_config = config._raw.get("crow_detection", {})

        # Get data root from environment, fallback to /data/orpheus
        data_root = os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus")
        default_embedder_path = f"{data_root}/models/aves-base-bio.pt"
        default_classifier_path = f"{data_root}/models/mt_70.pt"

        return cls(
            enabled=crow_config.get("enabled", True),
            quality_threshold=crow_config.get("quality_threshold", 0.5),
            embedder_model_path=crow_config.get("embedder_model_path", default_embedder_path),
            classifier_model_path=crow_config.get("classifier_model_path", default_classifier_path),
            embedder_sample_rate=crow_config.get("embedder_sample_rate", 16000),
        )


def load_config(config_path: Path | None = None) -> CrowDetectionConfig:
    """
    Load crow detection configuration.

    Args:
        config_path: Optional path to config file

    Returns:
        CrowDetectionConfig instance
    """
    orpheus_config = OrpheusConfig.get_instance(config_path=config_path)
    return CrowDetectionConfig.from_orpheus_config(orpheus_config)
