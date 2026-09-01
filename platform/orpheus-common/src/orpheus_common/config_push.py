"""``orpheus-config push`` — seed/update the backplane config KV from a canonical
YAML (ADR 0018). The single WRITE authority: ONE host runs this, MANY hosts read
the distributed config off the JetStream KV via ``JetStreamKvConfigBackend`` (so
hosts don't copy identical YAML).

Writes go through ``ConfigStore.set`` → the KV backend (versioned + change-notify),
one dotted key per config leaf. Do NOT run this from every host on install
(competing writers = lost updates, the exact problem this solves) — only the
authority install profile pushes.

SECURITY: this pushes the *whole* canonical config (which may include camera/RTSP
credentials) to the backplane KV. The KV must be access-controlled — the
distributed-install gate already refuses a broker bound to 0.0.0.0 without auth.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

from orpheus_common.config_backend import MISSING, JetStreamKvConfigBackend
from orpheus_common.config_store import ConfigStore
from orpheus_common.logging import get_logger

logger = get_logger(__name__)

_PUSH_AUTHOR = "orpheus-config-push"

# Sections that are bootstrap-LOCAL and must never round-trip through the KV: each
# host needs its own transport (event_bus.nats_url) and its own decision to read KV
# (config_service.enabled). Distributing them would let one authority pin the flag
# on fleet-wide / make it un-disableable from a host's local YAML.
_BOOTSTRAP_LOCAL_SECTIONS = ("event_bus", "config_service")


def flatten_config(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested config dict to dotted leaf keys (``audio.gain``). Lists and
    scalars are leaves (stored as-is — ConfigStore values are arbitrary JSON)."""
    out: dict[str, Any] = {}
    for key, value in (data or {}).items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(flatten_config(value, dotted))
        else:
            out[dotted] = value
    return out


def strip_bootstrap_local(flat: dict[str, Any]) -> dict[str, Any]:
    """Drop bootstrap-local keys (``event_bus.*``, ``config_service.*``) — those are
    per-host and must not be distributed via the KV layer (see
    ``_BOOTSTRAP_LOCAL_SECTIONS``)."""
    return {
        key: value
        for key, value in flat.items()
        if key.split(".", 1)[0] not in _BOOTSTRAP_LOCAL_SECTIONS
    }


def push_config(flat: dict[str, Any], store: ConfigStore, *, author: str = _PUSH_AUTHOR) -> int:
    """Write each ``dotted-key -> value`` into ``store`` (its KV backend). Returns
    the number of keys written. Single-writer authority — see module docstring."""
    count = 0
    for key, value in flat.items():
        store.set(key, value, author=author)
        count += 1
    return count


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    return data


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orpheus-config-push",
        description="Push a canonical config YAML to the backplane KV (the single "
        "write authority; many hosts read). ADR 0018.",
    )
    parser.add_argument(
        "yaml_path",
        nargs="?",
        default=None,
        help="config YAML to push (default: the loaded OrpheusConfig source)",
    )
    parser.add_argument("--author", default=_PUSH_AUTHOR, help="audit-trail author")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the keys that would be pushed, write nothing",
    )
    args = parser.parse_args(argv)

    # The config source: an explicit YAML needs neither the singleton nor a bus
    # (so --dry-run <file> works offline); otherwise read the loaded config.
    if args.yaml_path:
        data = _load_yaml(Path(args.yaml_path))
    else:
        from orpheus_common.config import OrpheusConfig

        data = OrpheusConfig.get_instance().to_dict()
    flat = strip_bootstrap_local(flatten_config(data))

    if args.dry_run:
        for key in sorted(flat):
            print(f"  {key}")
        print(f"[dry-run] {len(flat)} keys would be pushed")
        return 0

    # The bus reads connection (nats_url) from the loaded config.
    from orpheus_common.config import OrpheusConfig
    from orpheus_common.event_bus import create_event_bus

    bus = create_event_bus(OrpheusConfig.get_instance(), client_id="orpheus-config-push")
    bus.connect()
    try:
        store = ConfigStore(
            backend=JetStreamKvConfigBackend(bus),
            yaml_getter=lambda _key: MISSING,
            bus=bus,
        )
        count = push_config(flat, store, author=args.author)
    finally:
        bus.disconnect()
    logger.info("Pushed config to backplane KV", keys=count, author=args.author)
    print(f"Pushed {count} config keys to the backplane KV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
