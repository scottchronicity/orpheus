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
from orpheus_common.config_backend import ConfigBackend, SqliteConfigBackend
from orpheus_common.config_store import ConfigStore, ConfigVersion
from orpheus_common.detection import Detection, DetectionDB
from orpheus_common.diagnostics import AudioHealthMonitor
from orpheus_common.event_bus import EventBus, EventCallback, create_event_bus
from orpheus_common.events import WeatherReading
from orpheus_common.logging import setup_logging
from orpheus_common.replay import ReplayEngine
from orpheus_common.safety import BreakerStatus, CircuitBreaker
from orpheus_common.state_space import StateSpaceMemory, TemporalPattern, TimeWindow
from orpheus_common.telemetry import get_tracer, setup_tracing
from orpheus_common.weather import (
    EcowittProvider,
    WeatherDB,
    WeatherIngestor,
    WeatherProvider,
)

# __version__ resolves from the installed package metadata, which setuptools
# fills from the VERSION file (the single source of truth). Falls back when
# running from an uninstalled source tree.
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("orpheus-common")
except (ImportError, PackageNotFoundError):  # pragma: no cover - source tree
    __version__ = "0.0.0+unknown"
__author__ = "Orpheus Project"

# Version info
VERSION = __version__

# Public API - import commonly used classes at package level

__all__ = [
    "AudioHealthMonitor",
    "BreakerStatus",
    "CircuitBreaker",
    "Config",
    "ConfigError",
    "ConfigBackend",
    "ConfigStore",
    "ConfigVersion",
    "SqliteConfigBackend",
    "Detection",
    "DetectionDB",
    "EventBus",
    "EventCallback",
    "OrpheusConfig",
    "EcowittProvider",
    "ReplayEngine",
    "StateSpaceMemory",
    "TemporalPattern",
    "TimeWindow",
    "WeatherDB",
    "WeatherIngestor",
    "WeatherProvider",
    "WeatherReading",
    "create_event_bus",
    "get_tracer",
    "setup_logging",
    "setup_tracing",
    "VERSION",
]
