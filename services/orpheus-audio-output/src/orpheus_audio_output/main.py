"""orpheus-audio-output: keep the configured audio output ready for playback.

python -m orpheus_audio_output.main            # run the manager (systemd)
python -m orpheus_audio_output.main check      # validate config, print JSON
python -m orpheus_audio_output.main status     # print the last health snapshot
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from orpheus_common.config import ConfigError, OrpheusConfig
from orpheus_common.logging import get_logger, setup_logging

from .config import AudioOutputConfigError, load_audio_output_config
from .manager import OutputManager
from .outputs import build_output
from .servers import build_server

logger = get_logger(__name__)

TOPIC_HEALTH = "orpheus/audio/output/health"
HEALTH_FILE = Path(
    os.environ.get("ORPHEUS_AUDIO_OUTPUT_HEALTH_FILE", "/run/orpheus-audio-output/health.json")
)
HEALTH_PUBLISH_SECONDS = 30.0
EX_CONFIG = 78  # sysexits.h; the unit does not restart on it


class _Stop(Exception):  # noqa: N818 - a control-flow signal, not an error
    """Raised from the signal handler so a blocking step (connect, server
    start) is interrupted; subprocess.run kills its child on the way out."""


def _raise_stop(_signum: int, _frame: Any) -> None:
    raise _Stop()


def _write_health(path: Path, health: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".health-")
        with os.fdopen(fd, "w") as handle:
            json.dump(health, handle, indent=2, sort_keys=True)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("Could not write health file", path=str(path), error=str(exc))


def _load(config_path: Optional[Path]):
    orpheus = (
        OrpheusConfig.load(config_path=config_path) if config_path else OrpheusConfig.get_instance()
    )
    return orpheus, load_audio_output_config(orpheus)


def cmd_check(config_path: Optional[Path]) -> int:
    """Validate and print one JSON line on stdout (logs go to stderr)."""
    try:
        with contextlib.redirect_stdout(sys.stderr):
            orpheus, cfg = _load(config_path)
            if cfg.enabled:
                output = build_output(cfg)
                build_server(cfg, output.requires)
    except (AudioOutputConfigError, ConfigError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}))
        return EX_CONFIG
    print(json.dumps({"valid": True, "config": cfg.to_dict()}))
    return 0


def cmd_status() -> int:
    try:
        print(HEALTH_FILE.read_text())
    except OSError:
        print(json.dumps({"status": "unknown", "detail": f"no health file at {HEALTH_FILE}"}))
        return 1
    return 0


def _event_bus(orpheus: Any):
    """Best-effort health publishing; the manager never depends on the broker."""
    try:
        from orpheus_common import create_event_bus
        from orpheus_common.actor import (
            build_operational_health,
            health_on_bus_active,
            kv_publish_best_effort,
        )

        bus = create_event_bus(orpheus, client_id="orpheus-audio-output")
        bus.connect()
        op_health = build_operational_health(bus, orpheus)
        on_bus = health_on_bus_active(orpheus, op_health, agent="audio-output")

        def publish(health: dict) -> None:
            if on_bus:
                bus.publish(TOPIC_HEALTH, health, qos=0)
            kv_publish_best_effort(op_health, "audio-output", health)

        return bus, publish
    except Exception as exc:  # noqa: BLE001 - health transport must not stop audio
        logger.warning("Event bus unavailable; health goes to the local file only", error=str(exc))
        return None, lambda _health: None


def cmd_run(config_path: Optional[Path]) -> int:
    try:
        orpheus, cfg = _load(config_path)
    except (AudioOutputConfigError, ConfigError) as exc:
        logger.error("Invalid audio_output configuration", error=str(exc))
        return EX_CONFIG
    setup_logging("orpheus-audio-output", level=orpheus.logging.level, use_json=False)
    if not cfg.enabled:
        logger.info("audio_output is disabled; nothing to manage", config_source=cfg.source)
        _write_health(HEALTH_FILE, {"status": "disabled", "ready": False})
        return 0
    try:
        output = build_output(cfg)
        server = build_server(cfg, output.requires)
    except AudioOutputConfigError as exc:
        logger.error("Unsupported audio_output combination", error=str(exc))
        return EX_CONFIG
    if cfg.source == "legacy":
        logger.warning(
            "Using the retired bluetooth-autoconnect settings file; move them to "
            "audio_output in orpheus.yaml",
        )

    manager = OutputManager(cfg, output, server, logger)
    bus, publish = _event_bus(orpheus)
    signal.signal(signal.SIGTERM, _raise_stop)
    signal.signal(signal.SIGINT, _raise_stop)

    last_status: Optional[str] = None
    last_publish = 0.0
    try:
        manager.start()
        while True:
            wait = manager.tick()
            health = manager.health()
            _write_health(HEALTH_FILE, health)
            now = time.monotonic()
            if health["status"] != last_status or now - last_publish >= HEALTH_PUBLISH_SECONDS:
                try:
                    publish(health)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Health publish failed", error=str(exc))
                last_status, last_publish = health["status"], now
            time.sleep(wait)
    except _Stop:
        logger.info("Audio output manager stopping")
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        manager.stop()
        _write_health(HEALTH_FILE, {"status": "stopped", "ready": False})
        if bus is not None:
            try:
                bus.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Orpheus audio output manager")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "check", "status"])
    parser.add_argument("--config", type=Path, help="path to orpheus.yaml")
    args = parser.parse_args(argv)
    if args.command == "check":
        return cmd_check(args.config)
    if args.command == "status":
        return cmd_status()
    return cmd_run(args.config)


if __name__ == "__main__":
    sys.exit(main())
