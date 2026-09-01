"""Read-only data mirror — point-in-time snapshots of the live SQLite DB.

The Jetson's live DB is written continuously by ~7 agents while the UI runs heavy
reads. Sharing it with *more* readers — an LLM-facing observability surface, public
dashboards, a citizen-science export — risks starving the agents (the contention
the operator already observed). The mirror's answer is that those consumers never
touch the live DB at all: take a consistent snapshot, ship it to a separate host,
and serve every read-only consumer from the replica (opened with
``open_connection(..., read_only=True)``).

``snapshot_db`` is the snapshot primitive. It runs SQLite ``VACUUM INTO``, which
takes a single *read* transaction and writes a clean, defragmented copy to a new
file — the live DB is never write-locked (WAL lets the agents keep writing) and no
row is modified. The copy is a plain rollback-journal file with no ``-wal``/``-shm``
sidecars, which is exactly what a replica opened read-only wants. Requires
SQLite >= 3.27 (when ``VACUUM INTO`` was added; the deployed runtime ships 3.50).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from orpheus_common.detection.database import open_connection
from orpheus_common.logging import get_logger
from orpheus_common.utils.time import interruptible_sleep as _interruptible_sleep

if TYPE_CHECKING:
    from orpheus_common.config import MirrorConfig

logger = get_logger(__name__)

_DEFAULT_INTERVAL_SECONDS = 900.0



def snapshot_db(source_path: Path, dest_path: Path) -> Path:
    """Write a consistent point-in-time snapshot of ``source_path`` to ``dest_path``.

    Uses ``VACUUM INTO`` via a normal connection — the robust way to read a live
    WAL database with active writers (a read-only handle against a live WAL+shm is
    fraught). ``VACUUM INTO`` only *reads* the source under a read transaction, so
    no data is modified and writers are never blocked. The snapshot is staged to a
    temp sibling on the same filesystem and ``os.replace``-d into place, so a
    consumer reading ``dest_path`` never sees a half-written file. Returns
    ``dest_path``.
    """
    source_path = Path(source_path)
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    # VACUUM INTO refuses to overwrite an existing target, so stage to a temp
    # sibling then atomically rename — readers never observe a partial file.
    tmp_path = dest_path.with_name(f".{dest_path.name}.tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    conn = open_connection(source_path)
    try:
        conn.execute("VACUUM INTO ?", (str(tmp_path),))
    finally:
        conn.close()
    os.replace(tmp_path, dest_path)
    logger.info(
        "Wrote read-only DB snapshot",
        source=str(source_path),
        dest=str(dest_path),
        bytes=dest_path.stat().st_size,
    )
    return dest_path


class MirrorTransport(ABC):
    """Ships a snapshot to the read host. Push-only by contract — a transport
    never deletes or pulls, so the Jetson can only ever *write* the read host."""

    @abstractmethod
    def push(self, local_path: Path) -> None:
        """Publish the snapshot at ``local_path`` to the read host."""


class LocalDirTransport(MirrorTransport):
    """Publish the snapshot into a local directory (same-host serving + tests).
    Copies to a temp sibling then atomically renames, so a reader on the
    destination never observes a half-copied file."""

    def __init__(self, dest_dir: Path) -> None:
        self.dest_dir = Path(dest_dir)

    def push(self, local_path: Path) -> None:
        local_path = Path(local_path)
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        target = self.dest_dir / local_path.name
        tmp = self.dest_dir / f".{local_path.name}.tmp"
        shutil.copyfile(local_path, tmp)
        os.replace(tmp, target)
        logger.info("Mirrored snapshot to local dir", dest=str(target))


class SshRsyncTransport(MirrorTransport):
    """Push the snapshot to a remote read host via rsync-over-ssh. Push-only:
    NO ``--delete`` — the remote is only ever written, never told to mirror
    deletions, so the Jetson can't be used to wipe the read host.

    Atomicity: resume data goes to ``--partial-dir=.rsync-partial`` (never bare
    ``--partial``, which would leave a truncated DB under the FINAL destination
    filename on an interrupted/timed-out push). With a partial-dir, rsync keeps
    its normal stage-to-temp + atomic-rename finish, so a reader on the dest
    never observes a half-transferred replica. ``-a`` preserves mode/mtime."""

    def __init__(
        self, dest: str, *, ssh_options: str = "", push_timeout_seconds: float = 300.0
    ) -> None:
        self.dest = dest
        self.ssh_options = ssh_options
        self.push_timeout_seconds = push_timeout_seconds

    def build_command(self, local_path: Path) -> list[str]:
        """The rsync argv (no shell). Exposed so it can be asserted in tests
        without executing rsync."""
        cmd = ["rsync", "-a", "--partial-dir=.rsync-partial"]
        if self.ssh_options:
            cmd += ["-e", f"ssh {self.ssh_options}"]
        cmd += [str(local_path), self.dest]
        return cmd

    def push(self, local_path: Path) -> None:
        cmd = self.build_command(Path(local_path))
        logger.info("Pushing snapshot via rsync", dest=self.dest)
        # timeout so a half-open SSH raises TimeoutExpired (swallowed by run_mirror's
        # per-cycle log+continue) instead of hanging the loop past the next cycle / stop.
        subprocess.run(  # noqa: S603 - argv list, no shell
            cmd, check=True, timeout=self.push_timeout_seconds
        )


def build_transport(
    kind: str, dest: str, *, ssh_options: str = "", push_timeout_seconds: float = 300.0
) -> MirrorTransport:
    """Construct the transport named by ``kind`` (``MirrorConfig.transport``)."""
    if kind == "ssh":
        return SshRsyncTransport(
            dest, ssh_options=ssh_options, push_timeout_seconds=push_timeout_seconds
        )
    if kind == "local":
        return LocalDirTransport(Path(dest))
    raise ValueError(f"Unknown mirror transport: {kind!r}")


# --- the orpheus-mirror agent ------------------------------------------------ #


def _resolve_paths(config: MirrorConfig) -> tuple[Path, Path]:
    """Resolve (source live DB, local staging snapshot), defaulting empty config
    paths against the data root (resolved here, not in config, to avoid a cycle)."""
    from orpheus_common.storage import get_data_root  # lazy: keep config import-light

    root = get_data_root()
    source = (
        Path(config.source_db)
        if config.source_db
        else root / "detections" / "orpheus.db"
    )
    staging = (
        Path(config.staging_path)
        if config.staging_path
        else root / "mirror" / "orpheus.db"
    )
    return source, staging


def mirror_once(
    config: MirrorConfig, *, transport: Optional[MirrorTransport] = None
) -> Path:
    """One snapshot → push. Snapshots the live DB to the staging path, then ships
    the replica via the configured transport. ``transport`` is injectable for
    tests. Returns the staging path."""
    source, staging = _resolve_paths(config)
    snapshot_db(source, staging)
    transport = transport or build_transport(
        config.transport,
        config.dest,
        ssh_options=config.ssh_options,
        push_timeout_seconds=config.push_timeout_seconds,
    )
    transport.push(staging)
    return staging


def run_mirror(
    config: MirrorConfig,
    *,
    transport: Optional[MirrorTransport] = None,
    sleep: Callable[[float], None] = time.sleep,
    stop: Optional[Callable[[], bool]] = None,
    max_cycles: Optional[int] = None,
) -> int:
    """Snapshot+push every ``config.interval_seconds`` until ``stop()`` is true
    (or ``max_cycles`` reached, for tests). One bad cycle is logged and the loop
    continues — a transient snapshot/push failure must not take the mirror down.
    Returns the number of cycles run."""
    should_stop = stop or (lambda: False)
    interval = config.interval_seconds or _DEFAULT_INTERVAL_SECONDS
    cycles = 0
    while not should_stop():
        try:
            mirror_once(config, transport=transport)
        except Exception:
            logger.exception("Mirror cycle failed; continuing")
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        if should_stop():
            break
        _interruptible_sleep(interval, sleep, should_stop)
    return cycles


def main(argv: Optional[list[str]] = None) -> int:
    import argparse  # lazy

    parser = argparse.ArgumentParser(
        prog="orpheus-mirror",
        description="Snapshot the live DB and push a read-only replica to a read host.",
    )
    parser.add_argument(
        "--once", action="store_true", help="Snapshot + push once and exit."
    )
    parser.add_argument(
        "--interval", type=float, help="Seconds between cycles (overrides config)."
    )
    args = parser.parse_args(argv)

    from .config import OrpheusConfig  # lazy: avoid loading config at import

    config = OrpheusConfig.get_instance()
    mcfg = config.mirror
    if args.interval is not None:
        mcfg.interval_seconds = args.interval
    if not mcfg.dest:
        logger.error("No mirror destination configured (set mirror.dest).")
        return 2
    if not mcfg.enabled:
        logger.warning(
            "mirror.enabled is false — running on-demand (the flag only gates the "
            "long-running service, not a manual run)."
        )

    if args.once:
        mirror_once(mcfg)
        return 0

    stop_flag = {"stop": False}

    def _request_stop(*_: Any) -> None:
        stop_flag["stop"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _request_stop)

    run_mirror(mcfg, stop=lambda: stop_flag["stop"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
