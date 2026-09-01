"""Tests for the read-only data-mirror snapshot primitive."""

import sqlite3
from pathlib import Path

import pytest

from orpheus_common.config import MirrorConfig, OrpheusConfig, UIConfig
from orpheus_common.detection.database import open_connection
from orpheus_common.mirror import (
    LocalDirTransport,
    MirrorTransport,
    SshRsyncTransport,
    build_transport,
    mirror_once,
    run_mirror,
    snapshot_db,
)


def _make_db(path: Path, rows: list[int]) -> None:
    conn = open_connection(path)
    try:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
        conn.commit()
    finally:
        conn.close()


def _read_rows(path: Path) -> list[int]:
    ro = open_connection(path, read_only=True)
    try:
        return [r[0] for r in ro.execute("SELECT x FROM t ORDER BY x")]
    finally:
        ro.close()


class TestSnapshotDb:
    def test_snapshot_copies_data(self, tmp_path: Path) -> None:
        src, dst = tmp_path / "live.db", tmp_path / "snap.db"
        _make_db(src, [1, 2, 3])
        out = snapshot_db(src, dst)
        assert out == dst
        assert _read_rows(dst) == [1, 2, 3]

    def test_snapshot_has_no_wal_sidecar_or_temp(self, tmp_path: Path) -> None:
        # A clean rollback-journal file is exactly what a read-only replica wants;
        # the staging temp must be gone after the atomic rename.
        src, dst = tmp_path / "live.db", tmp_path / "snap.db"
        _make_db(src, [1])
        snapshot_db(src, dst)
        assert not (tmp_path / "snap.db-wal").exists()
        assert not (tmp_path / "snap.db-shm").exists()
        assert not (tmp_path / ".snap.db.tmp").exists()

    def test_snapshot_leaves_source_writable(self, tmp_path: Path) -> None:
        # The mirror must never mutate or wedge the live DB — after a snapshot the
        # source still reads AND accepts new writes.
        src, dst = tmp_path / "live.db", tmp_path / "snap.db"
        _make_db(src, [5])
        snapshot_db(src, dst)
        w = open_connection(src)
        try:
            w.execute("INSERT INTO t VALUES (6)")
            w.commit()
            assert [r[0] for r in w.execute("SELECT x FROM t ORDER BY x")] == [5, 6]
        finally:
            w.close()

    def test_resnapshot_atomically_replaces(self, tmp_path: Path) -> None:
        src, dst = tmp_path / "live.db", tmp_path / "snap.db"
        _make_db(src, [1])
        snapshot_db(src, dst)
        w = open_connection(src)
        w.execute("INSERT INTO t VALUES (2)")
        w.commit()
        w.close()
        snapshot_db(src, dst)  # overwrite the existing replica
        assert _read_rows(dst) == [1, 2]

    def test_snapshot_is_read_only(self, tmp_path: Path) -> None:
        # Composition with N1: the replica rejects writes.
        src, dst = tmp_path / "live.db", tmp_path / "snap.db"
        _make_db(src, [1])
        snapshot_db(src, dst)
        ro = open_connection(dst, read_only=True)
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                ro.execute("INSERT INTO t VALUES (99)")
        finally:
            ro.close()


class TestTransports:
    def test_local_dir_transport_copies_file(self, tmp_path: Path) -> None:
        src = tmp_path / "snap.db"
        src.write_bytes(b"hello-replica")
        dest_dir = tmp_path / "served"
        LocalDirTransport(dest_dir).push(src)
        target = dest_dir / "snap.db"
        assert target.read_bytes() == b"hello-replica"
        # staging temp cleaned up by the atomic rename
        assert not (dest_dir / ".snap.db.tmp").exists()

    def test_ssh_rsync_command_is_push_only(self, tmp_path: Path) -> None:
        local = tmp_path / "snap.db"
        cmd = SshRsyncTransport("user@host:/srv/replica/").build_command(local)
        assert cmd[0] == "rsync"
        # push-only: never --delete (would let the Jetson wipe the read host)
        assert "--delete" not in cmd
        # source then dest, dest last
        assert cmd[-2] == str(local)
        assert cmd[-1] == "user@host:/srv/replica/"

    def test_ssh_rsync_partial_goes_to_partial_dir_not_final_name(
        self, tmp_path: Path
    ) -> None:
        # Bare --partial keeps an interrupted transfer's bytes under the FINAL
        # destination filename — a truncated orpheus.db served to readers until
        # the next cycle. --partial-dir stages resume data aside and preserves
        # rsync's atomic temp+rename finish.
        cmd = SshRsyncTransport("user@host:/srv/replica/").build_command(
            tmp_path / "snap.db"
        )
        assert "--partial" not in cmd
        assert "--partial-dir=.rsync-partial" in cmd

    def test_ssh_rsync_command_includes_ssh_options(self, tmp_path: Path) -> None:
        cmd = SshRsyncTransport(
            "user@host:/srv/", ssh_options="-p 2222"
        ).build_command(tmp_path / "snap.db")
        assert "-e" in cmd
        assert cmd[cmd.index("-e") + 1] == "ssh -p 2222"

    def test_build_transport_factory(self, tmp_path: Path) -> None:
        assert isinstance(build_transport("local", str(tmp_path)), LocalDirTransport)
        assert isinstance(
            build_transport("ssh", "user@host:/srv/"), SshRsyncTransport
        )
        with pytest.raises(ValueError, match="Unknown mirror transport"):
            build_transport("carrier-pigeon", "nowhere")

    def test_ssh_push_bounds_subprocess_with_timeout(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        transport = SshRsyncTransport("user@host:/srv/", push_timeout_seconds=42.0)
        with patch("orpheus_common.mirror.subprocess.run") as run:
            transport.push(tmp_path / "snap.db")
        assert run.call_args.kwargs["timeout"] == 42.0  # a hung rsync can't wedge the loop

    def test_build_transport_threads_push_timeout(self) -> None:
        t = build_transport("ssh", "user@host:/srv/", push_timeout_seconds=7.0)
        assert isinstance(t, SshRsyncTransport)
        assert t.push_timeout_seconds == 7.0


class TestMirrorConfig:
    def test_defaults_disabled(self) -> None:
        c = MirrorConfig.from_dict({})
        assert c.enabled is False
        assert c.transport == "local"
        assert c.interval_seconds == 900.0
        assert c.source_db == "" and c.dest == ""

    def test_from_dict_values(self) -> None:
        c = MirrorConfig.from_dict(
            {
                "enabled": True,
                "transport": "ssh",
                "dest": "user@host:/srv/",
                "ssh_options": "-p 2222",
                "interval_seconds": 300,
            }
        )
        assert c.enabled is True and c.transport == "ssh"
        assert c.dest == "user@host:/srv/" and c.ssh_options == "-p 2222"
        assert c.interval_seconds == 300.0

    def test_absent_section_yields_disabled(self) -> None:
        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}}, source="<test>"
        )
        assert cfg.mirror.enabled is False

    def test_to_dict_includes_mirror(self) -> None:
        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}, "mirror": {"enabled": True}},
            source="<test>",
        )
        assert cfg.to_dict()["mirror"]["enabled"] is True


class TestUIConfig:
    def test_default_reads_live(self) -> None:
        assert UIConfig.from_dict({}).read_from_replica is False
        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}}, source="<test>"
        )
        assert cfg.ui.read_from_replica is False

    def test_from_dict_and_to_dict(self) -> None:
        assert UIConfig.from_dict({"read_from_replica": True}).read_from_replica is True
        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}, "ui": {"read_from_replica": True}},
            source="<test>",
        )
        assert cfg.ui.read_from_replica is True
        assert cfg.to_dict()["ui"]["read_from_replica"] is True

    def test_health_source_defaults_to_bus(self) -> None:
        assert UIConfig.from_dict({}).health_source == "bus"
        cfg = OrpheusConfig.from_dict({"mqtt": {"broker_host": "localhost"}}, source="<test>")
        assert cfg.ui.health_source == "bus"

    def test_health_source_override(self) -> None:
        assert UIConfig.from_dict({"health_source": "kv"}).health_source == "kv"


class TestMirrorAgent:
    def test_mirror_once_snapshots_and_pushes(self, tmp_path: Path) -> None:
        src = tmp_path / "live.db"
        _make_db(src, [1, 2])
        served = tmp_path / "served"
        cfg = MirrorConfig(
            source_db=str(src),
            staging_path=str(tmp_path / "stage" / "orpheus.db"),
            transport="local",
            dest=str(served),
        )
        mirror_once(cfg)
        # the replica landed in the served dir and reads back read-only
        assert _read_rows(served / "orpheus.db") == [1, 2]

    def test_run_mirror_runs_n_cycles_and_sleeps_between(self, tmp_path: Path) -> None:
        src = tmp_path / "live.db"
        _make_db(src, [1])
        cfg = MirrorConfig(
            source_db=str(src),
            staging_path=str(tmp_path / "stage" / "orpheus.db"),
            transport="local",
            dest=str(tmp_path / "served"),
            interval_seconds=5.0,
        )
        sleeps: list[float] = []
        cycles = run_mirror(cfg, sleep=sleeps.append, max_cycles=3)
        assert cycles == 3
        # between cycles, not after the last — sliced into <=1s chunks so the
        # stop flag is polled during the wait (PEP 475: one long sleep resumes
        # straight through a handled SIGINT/SIGTERM)
        assert sum(sleeps) == 10.0
        assert all(s <= 1.0 for s in sleeps)

    def test_run_mirror_stop_interrupts_the_sleep(self, tmp_path: Path) -> None:
        # Request stop mid-sleep (as the SIGINT/SIGTERM handlers do): the sliced
        # sleep must notice within ~1s, not doze the full 900s interval.
        src = tmp_path / "live.db"
        _make_db(src, [1])
        cfg = MirrorConfig(
            source_db=str(src),
            staging_path=str(tmp_path / "stage" / "orpheus.db"),
            transport="local",
            dest=str(tmp_path / "served"),
            interval_seconds=900.0,
        )
        stop_flag = {"stop": False}
        sleeps: list[float] = []

        def _sleep(seconds: float) -> None:
            sleeps.append(seconds)
            stop_flag["stop"] = True  # signal arrives during the first slice

        cycles = run_mirror(cfg, sleep=_sleep, stop=lambda: stop_flag["stop"])
        assert cycles == 1
        assert sleeps == [1.0]  # one slice, then the stop flag was honoured

    def test_run_mirror_survives_push_failure(self, tmp_path: Path) -> None:
        src = tmp_path / "live.db"
        _make_db(src, [1])
        cfg = MirrorConfig(
            source_db=str(src),
            staging_path=str(tmp_path / "stage" / "orpheus.db"),
            transport="local",
            dest=str(tmp_path / "served"),
        )

        class _BoomTransport(MirrorTransport):
            def __init__(self) -> None:
                self.calls = 0

            def push(self, local_path: Path) -> None:
                self.calls += 1
                raise RuntimeError("boom")

        boom = _BoomTransport()
        cycles = run_mirror(cfg, transport=boom, sleep=lambda _s: None, max_cycles=2)
        assert cycles == 2 and boom.calls == 2  # failures logged, loop continued
