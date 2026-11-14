"""Tests for orpheus-manifest-gen (deploy manifests from orpheus.yaml)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from orpheus_common.manifest_gen import (
    CATALOG,
    DockerComposeGenerator,
    SystemdGenerator,
    enabled_components,
    generate_manifest,
)


def _cfg(*, audio: bool, cameras: bool):
    return SimpleNamespace(
        get_enabled_audio_channels=lambda: (["ch"] if audio else []),
        get_enabled_cameras=lambda: (["cam"] if cameras else []),
    )


class TestEnabledComponents:
    def test_audio_only_excludes_video(self):
        names = {c.name for c in enabled_components(_cfg(audio=True, cameras=False))}
        assert {"audio-motion", "bird-detection", "crow-detection", "audio-events"} <= names
        assert "video-motion" not in names
        assert {"backplane", "event-correlator", "audio-playback", "ui"} <= names  # always

    def test_cameras_add_video(self):
        names = {c.name for c in enabled_components(_cfg(audio=False, cameras=True))}
        assert "video-motion" in names
        assert "audio-motion" not in names  # no audio channels

    def test_nothing_configured_still_has_core(self):
        names = {c.name for c in enabled_components(_cfg(audio=False, cameras=False))}
        # gps is core: it's in the unconditional `make install` set and ships a
        # real unit — omitting it made a generated orpheus.target never start it.
        assert names == {"backplane", "audio-playback", "event-correlator", "gps", "ui"}


    def test_audio_output_section_adds_the_output_manager(self):
        cfg = _cfg(audio=False, cameras=False)
        cfg._raw = {"audio_output": {"output": {"bluetooth": {"address": "FC:58:FA:02:AF:28"}}}}
        assert "audio-output" in {c.name for c in enabled_components(cfg)}
        cfg._raw = {"audio_output": {"enabled": False}}
        assert "audio-output" not in {c.name for c in enabled_components(cfg)}


class TestSystemd:
    def test_target_wants_enabled_units_sorted(self):
        out = SystemdGenerator().generate(_cfg(audio=True, cameras=False))
        assert "Description=Orpheus wildlife-sensing stack" in out
        assert "orpheus-agent-audio-motion.service" in out
        assert "orpheus-agent-video-motion.service" not in out  # no cameras
        assert "orpheus-backplane.service" in out and "orpheus-ui.service" in out
        assert "orpheus-gps.service" in out  # shipped unit, unconditional install set
        wants_line = next(ln for ln in out.splitlines() if ln.startswith("Wants="))
        units = wants_line[len("Wants="):].split()
        assert units == sorted(units)  # deterministic ordering

    def test_idempotent(self):
        cfg = _cfg(audio=True, cameras=True)
        assert SystemdGenerator().generate(cfg) == SystemdGenerator().generate(cfg)


class TestDockerCompose:
    def test_services_per_enabled_component_with_depends_on(self):
        out = DockerComposeGenerator().generate(_cfg(audio=True, cameras=True))
        import yaml

        # strip the leading comment lines before parsing
        doc = yaml.safe_load(out)
        services = doc["services"]
        assert "orpheus-agent-audio-motion" in services
        assert "orpheus-agent-video-motion" in services
        assert "orpheus-backplane" in services
        # backplane has no depends_on; agents depend on it
        assert "depends_on" not in services["orpheus-backplane"]
        assert services["orpheus-agent-audio-motion"]["depends_on"] == ["orpheus-backplane"]
        assert services["orpheus-agent-audio-motion"]["restart"] == "unless-stopped"
        assert services["orpheus-agent-audio-motion"]["image"].startswith("orpheus/audio-motion:")

    def test_idempotent(self):
        cfg = _cfg(audio=True, cameras=False)
        assert DockerComposeGenerator().generate(cfg) == DockerComposeGenerator().generate(cfg)


def test_unknown_target_raises():
    with pytest.raises(ValueError):
        generate_manifest(_cfg(audio=True, cameras=True), "k8s")


def test_catalog_covers_every_shipped_agent():
    """A new agent that isn't in CATALOG generates an orpheus.target that never starts
    it — the exact silent gap manifest-gen exists to close. Assert the catalog's agent
    entries cover every agents/orpheus-agent-* that ships a systemd unit."""
    repo = Path(__file__).resolve().parents[3]
    agents_dir = repo / "agents"
    if not agents_dir.is_dir():  # tolerate an unusual checkout layout
        pytest.skip("agents/ not found relative to the test")
    shipped = {
        p.name[len("orpheus-agent-"):]
        for p in agents_dir.glob("orpheus-agent-*")
        if p.is_dir() and list(p.glob("systemd/*.service"))
    }
    cataloged = {c.name for c in CATALOG if c.kind == "agent"}
    missing = shipped - cataloged
    assert not missing, f"agents shipped but absent from manifest CATALOG: {sorted(missing)}"


@pytest.mark.parametrize("count", [1, 8, 20])
def test_real_config_and_manifests_do_not_cap_sensor_counts(count):
    from orpheus_common.config import OrpheusConfig

    config = OrpheusConfig.from_dict({
        "audio": {"channels": [{"id": n, "name": f"mic{n}"} for n in range(count)]},
        "cameras": {
            "auth": {"username": "test", "password": "test"},
            **{f"cam{n}": {"type": "rtsp", "host": f"camera{n}"} for n in range(count)},
        },
    })
    assert len(config.get_enabled_audio_channels()) == count
    assert len(config.get_enabled_cameras()) == count
    for target in ("systemd", "docker-compose"):
        manifest = generate_manifest(config, target)
        assert "orpheus-agent-audio-events" in manifest
        assert "orpheus-agent-video-motion" in manifest
