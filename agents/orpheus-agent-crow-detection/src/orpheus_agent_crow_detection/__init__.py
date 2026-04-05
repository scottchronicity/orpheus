"""Crow detection agent for Orpheus platform."""

from .classifier import CrowClassifier, CrowDetectionResult
from .model import MultiTaskCrowNet

__version__ = "0.1.0"

__all__ = ["CrowClassifier", "CrowDetectionResult", "MultiTaskCrowNet"]
