"""``audio_output`` configuration: output device, audio server, reconnect policy.

The section is owned by this component and read from the shared ``OrpheusConfig``
(environment > optional shared KV > local YAML), like every other component's
section. Contract::

    audio_output:
      enabled: true
      output:
        type: bluetooth
        bluetooth:
          address: "AA:BB:CC:DD:EE:FF"
      server:
        type: pulseaudio
        pulseaudio:
          user: orpheus
      reconnect:
        enabled: true
        initial_delay_seconds: 10
        max_delay_seconds: 60

Migration: the retired ``orpheus-bluetooth-autoconnect`` service kept its
settings in ``/etc/orpheus/bluetooth-autoconnect/config.env``. When that file
exists it supplies values the YAML does not set (it ranks just above the
component defaults), so an upgraded station keeps its speaker without editing
``orpheus.yaml``. Without an ``audio_output`` section the legacy file alone
enables the manager; with neither, the manager is disabled.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

LEGACY_CONFIG_PATH = Path("/etc/orpheus/bluetooth-autoconnect/config.env")

OUTPUT_TYPES = ("bluetooth",)
SERVER_TYPES = ("pulseaudio",)

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

_SECTION_KEYS = {"enabled", "output", "server", "reconnect"}
_OUTPUT_KEYS = {"type", *OUTPUT_TYPES}
_SERVER_KEYS = {"type", *SERVER_TYPES}
_RECONNECT_KEYS = {"enabled", "initial_delay_seconds", "max_delay_seconds"}


class AudioOutputConfigError(ValueError):
    """The ``audio_output`` section is invalid or selects an unsupported combination."""


@dataclass(frozen=True)
class BluetoothOutputConfig:
    address: str


@dataclass(frozen=True)
class OutputConfig:
    type: str
    bluetooth: Optional[BluetoothOutputConfig] = None


@dataclass(frozen=True)
class PulseAudioServerConfig:
    user: str


@dataclass(frozen=True)
class ServerConfig:
    type: str
    pulseaudio: Optional[PulseAudioServerConfig] = None


@dataclass(frozen=True)
class ReconnectConfig:
    enabled: bool = True
    initial_delay_seconds: float = 10.0
    max_delay_seconds: float = 60.0


@dataclass(frozen=True)
class AudioOutputConfig:
    enabled: bool
    output: OutputConfig
    server: ServerConfig
    reconnect: ReconnectConfig
    # Where the settings came from: "orpheus.yaml", "legacy" or "defaults".
    source: str = "defaults"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_legacy_env(path: Path = LEGACY_CONFIG_PATH) -> dict[str, str]:
    """Parse the retired service's ``KEY=value`` file (comments and blanks ignored)."""
    values: dict[str, str] = {}
    try:
        text = path.read_text()
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AudioOutputConfigError(f"{where} must be a mapping")
    return dict(value)


def _no_unknown(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise AudioOutputConfigError(
            f"unknown key(s) under {where}: {', '.join(unknown)} "
            f"(expected: {', '.join(sorted(allowed))})"
        )


def _bool(value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):  # an environment override's digits
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "yes", "on", "1"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "no", "off", "0"}:
        return False
    raise AudioOutputConfigError(f"{where} must be true or false, got {value!r}")


def _seconds(value: Any, where: str) -> float:
    if isinstance(value, bool):
        raise AudioOutputConfigError(f"{where} must be a number of seconds")
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise AudioOutputConfigError(f"{where} must be a number of seconds, got {value!r}")
    if not math.isfinite(seconds) or seconds <= 0:
        raise AudioOutputConfigError(f"{where} must be positive and finite, got {value!r}")
    return seconds


def parse_audio_output(
    section: Optional[Mapping[str, Any]],
    legacy: Optional[Mapping[str, str]] = None,
) -> AudioOutputConfig:
    """Validate the ``audio_output`` section, filling gaps from the legacy file."""
    legacy = dict(legacy or {})
    if section is None and not legacy:
        return AudioOutputConfig(
            enabled=False,
            output=OutputConfig(type="bluetooth"),
            server=ServerConfig(type="pulseaudio", pulseaudio=PulseAudioServerConfig("orpheus")),
            reconnect=ReconnectConfig(),
            source="defaults",
        )

    source = "orpheus.yaml" if section is not None else "legacy"
    data = _mapping(section, "audio_output")
    _no_unknown(data, _SECTION_KEYS, "audio_output")

    enabled = _bool(data.get("enabled", True), "audio_output.enabled")

    out = _mapping(data.get("output"), "audio_output.output")
    _no_unknown(out, _OUTPUT_KEYS, "audio_output.output")
    output_type = str(out.get("type", "bluetooth"))
    if output_type not in OUTPUT_TYPES:
        raise AudioOutputConfigError(
            f"audio_output.output.type {output_type!r} is not supported "
            f"(supported: {', '.join(OUTPUT_TYPES)})"
        )

    srv = _mapping(data.get("server"), "audio_output.server")
    _no_unknown(srv, _SERVER_KEYS, "audio_output.server")
    server_type = str(srv.get("type", "pulseaudio"))
    if server_type not in SERVER_TYPES:
        raise AudioOutputConfigError(
            f"audio_output.server.type {server_type!r} is not supported "
            f"(supported: {', '.join(SERVER_TYPES)})"
        )

    bluetooth: Optional[BluetoothOutputConfig] = None
    if output_type == "bluetooth":
        bt = _mapping(out.get("bluetooth"), "audio_output.output.bluetooth")
        _no_unknown(bt, {"address"}, "audio_output.output.bluetooth")
        address = str(bt.get("address") or legacy.get("BLUETOOTH_SPEAKER_MAC") or "").strip()
        if enabled and not address:
            raise AudioOutputConfigError(
                "audio_output.output.bluetooth.address is required for a Bluetooth output"
            )
        if address and not _MAC_RE.match(address):
            raise AudioOutputConfigError(
                f"audio_output.output.bluetooth.address {address!r} is not a "
                "Bluetooth address (XX:XX:XX:XX:XX:XX)"
            )
        bluetooth = BluetoothOutputConfig(address=address.upper())

    pulseaudio: Optional[PulseAudioServerConfig] = None
    if server_type == "pulseaudio":
        pa = _mapping(srv.get("pulseaudio"), "audio_output.server.pulseaudio")
        _no_unknown(pa, {"user"}, "audio_output.server.pulseaudio")
        user = str(pa.get("user") or legacy.get("AUDIO_USER") or "orpheus").strip()
        if not _USER_RE.match(user):
            raise AudioOutputConfigError(
                f"audio_output.server.pulseaudio.user {user!r} is not a valid user name"
            )
        pulseaudio = PulseAudioServerConfig(user=user)

    rc = _mapping(data.get("reconnect"), "audio_output.reconnect")
    _no_unknown(rc, _RECONNECT_KEYS, "audio_output.reconnect")
    initial = _seconds(
        rc.get("initial_delay_seconds", legacy.get("RECONNECT_DELAY", 10)),
        "audio_output.reconnect.initial_delay_seconds",
    )
    maximum = _seconds(
        rc.get("max_delay_seconds", legacy.get("MAX_RECONNECT_DELAY", 60)),
        "audio_output.reconnect.max_delay_seconds",
    )
    if maximum < initial:
        raise AudioOutputConfigError(
            "audio_output.reconnect.max_delay_seconds must be at least initial_delay_seconds"
        )
    reconnect = ReconnectConfig(
        enabled=_bool(rc.get("enabled", True), "audio_output.reconnect.enabled"),
        initial_delay_seconds=initial,
        max_delay_seconds=maximum,
    )

    return AudioOutputConfig(
        enabled=enabled,
        output=OutputConfig(type=output_type, bluetooth=bluetooth),
        server=ServerConfig(type=server_type, pulseaudio=pulseaudio),
        reconnect=reconnect,
        source=source,
    )


def load_audio_output_config(
    orpheus_config: Any, legacy_path: Path = LEGACY_CONFIG_PATH
) -> AudioOutputConfig:
    """Resolve the section from an ``OrpheusConfig`` (env/KV/YAML already applied)."""
    raw = getattr(orpheus_config, "_raw", {}) or {}
    return parse_audio_output(raw.get("audio_output"), read_legacy_env(legacy_path))
