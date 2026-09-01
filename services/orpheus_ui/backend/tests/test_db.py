"""The shared DetectionDB factory — live by default, read-only replica when configured."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from orpheus_common.detection import DetectionDB

import orpheus_ui.db as dbmod


def _fake_cfg(read_from_replica: bool, staging: str) -> SimpleNamespace:
    return SimpleNamespace(
        ui=SimpleNamespace(read_from_replica=read_from_replica),
        mirror=SimpleNamespace(staging_path=staging),
    )


def test_default_is_live_writable(monkeypatch, tmp_path):
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "orpheus_common.config.OrpheusConfig.get_instance",
        lambda: _fake_cfg(False, ""),
    )
    db = dbmod._build_detection_db()
    assert db.read_only is False


def test_reads_replica_read_only_when_configured(monkeypatch, tmp_path):
    replica = tmp_path / "replica.db"
    DetectionDB(db_path=replica)  # create + migrate the replica once (writer)
    monkeypatch.setattr(
        "orpheus_common.config.OrpheusConfig.get_instance",
        lambda: _fake_cfg(True, str(replica)),
    )
    db = dbmod._build_detection_db()
    assert db.read_only is True
    assert Path(db.db_path) == replica


def test_flag_without_replica_path_stays_live(monkeypatch, tmp_path):
    # read_from_replica on but no mirror.staging_path -> fall back to the live DB.
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "orpheus_common.config.OrpheusConfig.get_instance",
        lambda: _fake_cfg(True, ""),
    )
    db = dbmod._build_detection_db()
    assert db.read_only is False


def test_missing_replica_snapshot_falls_back_to_live(monkeypatch, tmp_path):
    # read_from_replica on + a staging_path that DOESN'T exist yet (mirror hasn't run)
    # -> fall back to the live DB instead of a read-only handle that 500s every read.
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
    missing = tmp_path / "not-produced-yet.db"
    monkeypatch.setattr(
        "orpheus_common.config.OrpheusConfig.get_instance",
        lambda: _fake_cfg(True, str(missing)),
    )
    db = dbmod._build_detection_db()
    assert db.read_only is False  # live DB, not a doomed read-only handle


def _guard_writer_construction(monkeypatch):
    """Make the WRITER DetectionDB construction raise (an unwritable data root
    makes __init__'s mkdir/schema-migration raise) while read-only construction
    still works — simulates the CI incident without OS-permission games (which
    are unreliable when tests run as root)."""
    real = dbmod.DetectionDB

    def guarded(*args, **kwargs):
        if not kwargs.get("read_only", False):
            raise PermissionError(13, "Permission denied")
        return real(*args, **kwargs)

    monkeypatch.setattr(dbmod, "DetectionDB", guarded)


def test_unwritable_root_with_existing_db_degrades_to_read_only(monkeypatch, tmp_path):
    # Real incident: CI's e2e backend ran with an unwritable data root and every
    # data endpoint 500'd "[Errno 13] Permission denied". With a readable DB
    # already present, the UI (a read surface) must degrade to a read-only
    # handle instead.
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
    live = tmp_path / "detections" / "orpheus.db"
    DetectionDB(db_path=live)  # produce a real, migrated DB file
    monkeypatch.setattr(
        "orpheus_common.config.OrpheusConfig.get_instance",
        lambda: _fake_cfg(False, ""),
    )
    _guard_writer_construction(monkeypatch)
    db = dbmod._build_detection_db()
    assert db.read_only is True
    assert Path(db.db_path) == live


def test_unwritable_root_with_no_db_stays_loud(monkeypatch, tmp_path):
    # No DB anywhere -> nothing to serve read-only; the error must stay loud
    # (degrading to an empty handle would mask a broken deploy).
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "orpheus_common.config.OrpheusConfig.get_instance",
        lambda: _fake_cfg(False, ""),
    )
    _guard_writer_construction(monkeypatch)
    with pytest.raises(PermissionError):
        dbmod._build_detection_db()


def test_locked_db_raises_for_retry_instead_of_degrading(monkeypatch, tmp_path):
    # "database is locked" is TRANSIENT (e.g. another process holds the writer
    # lock during a minutes-long index build at fleet startup). Degrading would
    # cache a read-only, un-migrated handle for the process lifetime; raising
    # leaves the cached handle unset so the next request retries after the
    # build commits.
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
    live = tmp_path / "detections" / "orpheus.db"
    DetectionDB(db_path=live)  # a real DB exists — degrade WOULD be possible
    monkeypatch.setattr(
        "orpheus_common.config.OrpheusConfig.get_instance",
        lambda: _fake_cfg(False, ""),
    )

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(dbmod, "DetectionDB", locked)
    with pytest.raises(sqlite3.OperationalError):
        dbmod._build_detection_db()
