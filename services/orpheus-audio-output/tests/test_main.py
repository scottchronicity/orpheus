"""Entry point: config check, disabled mode, run loop, health file and shutdown."""

from __future__ import annotations

import json
import os

import pytest

import orpheus_audio_output.main as main_mod

ADDRESS = "AA:BB:CC:DD:EE:FF"


def write_yaml(tmp_path, body: str):
    path = tmp_path / "orpheus.yaml"
    path.write_text("mqtt:\n  broker_host: localhost\n  broker_port: 1883\n" + body)
    return path


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    from orpheus_common.config import OrpheusConfig

    monkeypatch.setattr(main_mod, "HEALTH_FILE", tmp_path / "health.json")
    from orpheus_audio_output import config as cfgmod

    monkeypatch.setattr(
        main_mod,
        "load_audio_output_config",
        lambda orpheus: cfgmod.load_audio_output_config(orpheus, legacy_path=tmp_path / "none.env"),
    )
    for key in list(os.environ):
        if key.startswith("ORPHEUS_AUDIO_OUTPUT"):
            monkeypatch.delenv(key)
    OrpheusConfig._instance = None
    yield
    OrpheusConfig._instance = None


def test_check_prints_resolved_config(tmp_path, capsys):
    path = write_yaml(
        tmp_path,
        f"audio_output:\n  output:\n    bluetooth:\n      address: '{ADDRESS}'\n",
    )
    assert main_mod.main(["check", "--config", str(path)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["valid"] is True
    assert out["config"]["output"]["bluetooth"]["address"] == ADDRESS
    assert out["config"]["server"] == {"type": "pulseaudio", "pulseaudio": {"user": "orpheus"}}


def test_check_rejects_unsupported_selection_with_exit_78(tmp_path, capsys):
    path = write_yaml(tmp_path, "audio_output:\n  server:\n    type: pipewire\n")
    assert main_mod.main(["check", "--config", str(path)]) == 78
    assert "pipewire" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])["error"]


def test_disabled_exits_cleanly_and_says_so(tmp_path):
    path = write_yaml(tmp_path, "audio_output:\n  enabled: false\n")
    assert main_mod.main(["run", "--config", str(path)]) == 0
    assert json.loads((tmp_path / "health.json").read_text())["status"] == "disabled"


def test_run_loop_publishes_health_and_stops_the_server_on_sigterm(tmp_path, monkeypatch):
    path = write_yaml(
        tmp_path, f"audio_output:\n  output:\n    bluetooth:\n      address: '{ADDRESS}'\n"
    )
    from test_manager import FakeOutput, FakeServer

    server = FakeServer(up=False)
    monkeypatch.setattr(main_mod, "build_output", lambda cfg: FakeOutput())
    monkeypatch.setattr(main_mod, "build_server", lambda cfg, needs: server)
    published = []
    monkeypatch.setattr(main_mod, "_event_bus", lambda orpheus: (None, published.append))
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise main_mod._Stop()  # what the SIGTERM handler raises

    monkeypatch.setattr(main_mod.time, "sleep", fake_sleep)
    assert main_mod.main(["run", "--config", str(path)]) == 0
    assert server.stopped
    assert published and published[0]["status"] == "healthy"
    assert published[0]["routing"]["state"] == "routed"
    assert json.loads((tmp_path / "health.json").read_text())["status"] == "stopped"
    assert sleeps == [10.0, 10.0, 10.0]
