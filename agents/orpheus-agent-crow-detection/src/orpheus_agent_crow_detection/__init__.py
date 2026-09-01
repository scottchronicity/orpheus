"""Crow detection agent for Orpheus platform."""

from .classifier import CrowClassifier, CrowDetectionResult
from .model import MultiTaskCrowNet

# Version SSoT: the VERSION file, surfaced via installed package metadata.
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("orpheus-agent-crow-detection")
except (ImportError, PackageNotFoundError):  # pragma: no cover - source tree
    __version__ = "0.0.0+unknown"

__all__ = ["CrowClassifier", "CrowDetectionResult", "MultiTaskCrowNet"]
