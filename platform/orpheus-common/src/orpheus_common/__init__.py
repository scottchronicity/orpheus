"""
Orpheus Common Library

Shared platform infrastructure for Orpheus cross-species communication system.
Provides hardware abstractions, configuration management, MQTT communication,
storage utilities, system health monitoring, and audio diagnostics.

Example:
    from orpheus_common import OrpheusConfig
    from orpheus_common.mqtt import MQTTClient
    from orpheus_common.hardware.cameras import AmcrestCamera
    from orpheus_common.diagnostics import AudioHealthMonitor

    config = OrpheusConfig.load()
    client = MQTTClient(broker_host=config.mqtt.broker_host)
    monitor = AudioHealthMonitor()
"""

from orpheus_common.config import Config, ConfigError, OrpheusConfig
from orpheus_common.detection import Detection, DetectionDB
from orpheus_common.diagnostics import AudioHealthMonitor
from orpheus_common.logging import setup_logging

__version__ = "0.2.0"
__author__ = "Orpheus Project"

# Version info
VERSION = __version__

# Public API - import commonly used classes at package level

__all__ = [
    "AudioHealthMonitor",
    "Config",
    "ConfigError",
    "Detection",
    "DetectionDB",
    "OrpheusConfig",
    "setup_logging",
    "VERSION",
]
