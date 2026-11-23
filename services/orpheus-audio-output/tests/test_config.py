"""The audio_output configuration contract, legacy migration and validation."""

from __future__ import annotations

import pytest
import yaml

from orpheus_audio_output.config import (
    AudioOutputConfigError,
    load_audio_output_config,
    parse_audio_output,
    read_legacy_env,
)
from orpheus_audio_output.outputs import build_output
from orpheus_audio_output.servers import build_server

CONTRACT = yaml.safe_load(
    """
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
"""
)


def test_contract_yaml_parses_to_independent_parts():
    cfg = parse_audio_output(CONTRACT["audio_output"])
    assert cfg.enabled is True
    assert cfg.output.type == "bluetooth"
    assert cfg.output.bluetooth.address == "AA:BB:CC:DD:EE:FF"
    assert cfg.server.type == "pulseaudio"
    assert cfg.server.pulseaudio.user == "orpheus"
    assert (
        cfg.reconnect.enabled,
        cfg.reconnect.initial_delay_seconds,
        cfg.reconnect.max_delay_seconds,
    ) == (
        True,
        10.0,
        60.0,
    )
    assert cfg.source == "orpheus.yaml"


def test_no_section_and_no_legacy_file_is_disabled():
    cfg = parse_audio_output(None, {})
    assert cfg.enabled is False
    assert cfg.source == "defaults"


def test_legacy_file_alone_keeps_an_upgraded_station_working(tmp_path):
    legacy = tmp_path / "config.env"
    legacy.write_text(
        "# Orpheus Bluetooth Auto-Connect Configuration\n"
        "BLUETOOTH_SPEAKER_MAC=aa:bb:cc:dd:ee:ff\n"
        "AUDIO_USER=orpheus\n"
    )
    cfg = parse_audio_output(None, read_legacy_env(legacy))
    assert cfg.enabled is True
    assert cfg.source == "legacy"
    assert cfg.output.bluetooth.address == "AA:BB:CC:DD:EE:FF"
    assert cfg.server.pulseaudio.user == "orpheus"


def test_yaml_wins_over_legacy_and_legacy_fills_gaps():
    section = {"server": {"pulseaudio": {"user": "birder"}}}
    legacy = {"BLUETOOTH_SPEAKER_MAC": "11:22:33:44:55:66", "AUDIO_USER": "orpheus"}
    cfg = parse_audio_output(section, legacy)
    assert cfg.server.pulseaudio.user == "birder"
    assert cfg.output.bluetooth.address == "11:22:33:44:55:66"
    assert cfg.source == "orpheus.yaml"


def test_disabled_section_needs_no_address():
    cfg = parse_audio_output({"enabled": False})
    assert cfg.enabled is False


@pytest.mark.parametrize(
    "section, message",
    [
        ({"output": {"type": "wired"}}, "output.type 'wired' is not supported"),
        ({"server": {"type": "pipewire"}}, "server.type 'pipewire' is not supported"),
        ({"output": {"bluetooth": {}}}, "address is required"),
        ({"output": {"bluetooth": {"address": "speaker"}}}, "is not a Bluetooth address"),
        (
            {"output": {"bluetooth": {"address": "AA:BB:CC:DD:EE:FF"}}, "volume": 3},
            "unknown key(s) under audio_output: volume",
        ),
        (
            {"output": {"bluetooth": {"address": "AA:BB:CC:DD:EE:FF", "mac": 1}}},
            "unknown key(s) under audio_output.output.bluetooth",
        ),
        (
            {
                "output": {"bluetooth": {"address": "AA:BB:CC:DD:EE:FF"}},
                "server": {"pulseaudio": {"user": "bad;user"}},
            },
            "not a valid user name",
        ),
        (
            {
                "output": {"bluetooth": {"address": "AA:BB:CC:DD:EE:FF"}},
                "reconnect": {"initial_delay_seconds": 0},
            },
            "positive and finite",
        ),
        (
            {
                "output": {"bluetooth": {"address": "AA:BB:CC:DD:EE:FF"}},
                "reconnect": {"initial_delay_seconds": 30, "max_delay_seconds": 10},
            },
            "at least initial_delay_seconds",
        ),
        (
            {
                "output": {"bluetooth": {"address": "AA:BB:CC:DD:EE:FF"}},
                "reconnect": {"enabled": "sometimes"},
            },
            "true or false",
        ),
    ],
)
def test_invalid_or_unsupported_selections_fail_clearly(section, message):
    with pytest.raises(
        AudioOutputConfigError, match=message.replace("(", r"\(").replace(")", r"\)")
    ):
        parse_audio_output(section)


def test_environment_overrides_go_through_orpheus_config(monkeypatch):
    from orpheus_common.config import OrpheusConfig

    monkeypatch.setenv("ORPHEUS_AUDIO_OUTPUT__OUTPUT__BLUETOOTH__ADDRESS", "11:22:33:44:55:66")
    monkeypatch.setenv("ORPHEUS_AUDIO_OUTPUT__RECONNECT__MAX_DELAY_SECONDS", "120")
    orpheus = OrpheusConfig(data=dict(CONTRACT), allow_missing=True)
    cfg = load_audio_output_config(orpheus, legacy_path=__import__("pathlib").Path("/nonexistent"))
    assert cfg.output.bluetooth.address == "11:22:33:44:55:66"
    assert cfg.reconnect.max_delay_seconds == 120.0


def test_supported_combination_builds_and_incompatible_needs_fail():
    cfg = parse_audio_output(CONTRACT["audio_output"])
    output = build_output(cfg)
    server = build_server(cfg, output.requires)
    assert output.type == "bluetooth" and server.type == "pulseaudio"
    with pytest.raises(AudioOutputConfigError, match="needs wired-jack, which"):
        build_server(cfg, frozenset({"wired-jack"}))
