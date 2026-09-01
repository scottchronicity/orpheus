"""``orpheus-manifest-gen`` — generate deployment manifests from ``orpheus.yaml`` so
the deployment topology stays in sync with the config (which agents/services are
active), instead of hand-editing systemd/compose when an agent is added or a channel
toggled.

Design: ``orpheus.yaml`` is the source of truth for *which* components run — the
per-component catalog below maps each to its (real, existing) systemd unit + compose
service and a predicate over the loaded config. The generators emit:

- ``systemd``: an ``orpheus.target`` whose ``Wants=`` lists exactly the enabled units
  (reuses the shipped per-agent ``.service`` files — ``systemctl enable orpheus.target``
  brings up the configured topology).
- ``docker-compose``: one service per enabled component. The image tag is a
  documented CONVENTION (``orpheus/<component>:<tag>``), a seam the operator's build
  fills — not invented product content (#7).

Deterministic + idempotent (sorted). Python 3.9. Off to the side: generating a
manifest changes no running system.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


def _audio_on(cfg: Any) -> bool:
    getter = getattr(cfg, "get_enabled_audio_channels", None)
    return bool(getter()) if callable(getter) else False


def _cameras_on(cfg: Any) -> bool:
    getter = getattr(cfg, "get_enabled_cameras", None)
    return bool(getter()) if callable(getter) else False


def _always(_cfg: Any) -> bool:
    return True


@dataclass(frozen=True)
class Component:
    """One deployable unit + how to tell whether the config enables it."""

    name: str  # bare name, e.g. "audio-motion" or "backplane"
    kind: str  # "agent" | "service"
    enabled: Callable[[Any], bool]

    @property
    def unit(self) -> str:
        prefix = "orpheus-agent-" if self.kind == "agent" else "orpheus-"
        return f"{prefix}{self.name}.service"

    @property
    def service(self) -> str:
        return self.unit[: -len(".service")]

    @property
    def image(self) -> str:
        # CONVENTION (a documented seam, #7): the operator's build produces this tag.
        return f"orpheus/{self.name}:${{ORPHEUS_VERSION:-latest}}"


# The canonical catalog. Detection classifiers ride the audio pipeline; video motion +
# the capture agents (snapshotter, timelapser) ride cameras; the correlator + playback +
# backplane + UI + gps are always part of the stack (gps is in the unconditional
# `make install` set and ships services/orpheus-gps/systemd/orpheus-gps.service). Every
# ``agents/orpheus-agent-*`` that ships a systemd unit MUST appear here or a generated
# ``orpheus.target`` silently never starts it — ``check_manifest_catalog``
# (make guardrails) + a coverage test enforce that.
#
# Deliberately absent (named seams, not omissions):
# - bluetooth-autoconnect: host-opt-in by design (skipped in the Makefile's
#   install-host dev loop; not in `make install`) and there is no config knob to
#   gate it on — add it here with a real predicate if one lands.
# - weather / mirror: cfg.weather.enabled / cfg.mirror.enabled exist, but no
#   systemd unit ships for either yet; the catalog maps only to real, existing
#   units, so add them gated on those flags once units ship.
CATALOG: tuple[Component, ...] = (
    Component("backplane", "service", _always),
    Component("audio-motion", "agent", _audio_on),
    Component("bird-detection", "agent", _audio_on),
    Component("crow-detection", "agent", _audio_on),
    Component("audio-events", "agent", _audio_on),
    Component("video-motion", "agent", _cameras_on),
    Component("video-snapshotter", "agent", _cameras_on),
    Component("video-timelapser", "agent", _cameras_on),
    Component("audio-playback", "agent", _always),
    Component("event-correlator", "agent", _always),
    Component("gps", "service", _always),
    Component("ui", "service", _always),
)


def enabled_components(config: Any) -> List[Component]:
    """The catalog entries the config turns on, in catalog order (deterministic)."""
    return [c for c in CATALOG if c.enabled(config)]


class ManifestGenerator:
    """Base: ``generate`` renders a manifest string; ``validate`` returns errors."""

    target = "base"

    def generate(self, config: Any) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def validate(self, manifest: str) -> List[str]:  # pragma: no cover - optional
        return []


class SystemdGenerator(ManifestGenerator):
    """An ``orpheus.target`` that Wants exactly the enabled units."""

    target = "systemd"

    def generate(self, config: Any) -> str:
        units = sorted(c.unit for c in enabled_components(config))
        wants = " ".join(units)
        return (
            "# Generated from orpheus.yaml by orpheus-manifest-gen — DO NOT EDIT.\n"
            "# Regenerate after changing the config; `systemctl enable orpheus.target`\n"
            "# brings up exactly the configured topology.\n"
            "[Unit]\n"
            "Description=Orpheus wildlife-sensing stack\n"
            f"Wants={wants}\n"
            "After=network-online.target\n"
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )


class DockerComposeGenerator(ManifestGenerator):
    """A compose file with one service per enabled component."""

    target = "docker-compose"

    def generate(self, config: Any) -> str:
        import yaml  # lazy; config already depends on pyyaml

        comps = enabled_components(config)
        services: dict[str, Any] = {}
        for c in comps:
            svc: dict[str, Any] = {
                "image": c.image,
                "restart": "unless-stopped",
            }
            if c.name != "backplane":
                svc["depends_on"] = ["orpheus-backplane"]
            services[c.service] = svc
        body = yaml.safe_dump(
            {"services": dict(sorted(services.items()))}, sort_keys=True, default_flow_style=False
        )
        return (
            "# Generated from orpheus.yaml by orpheus-manifest-gen — DO NOT EDIT.\n"
            "# `image:` is a CONVENTION (orpheus/<component>:<tag>) your build produces.\n"
            + body
        )


_GENERATORS: dict[str, type[ManifestGenerator]] = {
    SystemdGenerator.target: SystemdGenerator,
    DockerComposeGenerator.target: DockerComposeGenerator,
}


def generate_manifest(config: Any, target: str) -> str:
    try:
        gen = _GENERATORS[target]()
    except KeyError:
        known = ", ".join(sorted(_GENERATORS))
        raise ValueError(f"unknown target {target!r}; known: {known}") from None
    return gen.generate(config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orpheus-manifest-gen",
        description="Generate deployment manifests from orpheus.yaml (topology in sync).",
    )
    parser.add_argument("--target", required=True, choices=sorted(_GENERATORS))
    parser.add_argument("--config", default=None, help="orpheus.yaml path (default: discovered)")
    parser.add_argument(
        "--output", default="-", help="output file, or '-' for stdout (default)"
    )
    args = parser.parse_args(argv)

    from orpheus_common.config import OrpheusConfig

    config = OrpheusConfig.get_instance(config_path=args.config) if args.config else (
        OrpheusConfig.get_instance()
    )
    manifest = generate_manifest(config, args.target)
    if args.output == "-":
        print(manifest, end="")
    else:
        Path(args.output).write_text(manifest, encoding="utf-8")
        logger.info("Wrote manifest", target=args.target, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
