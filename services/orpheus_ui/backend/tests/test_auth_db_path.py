"""Where the accounts database lives.

The resolution has to satisfy two things at once: follow ``ORPHEUS_DATA_ROOT``
like every other persistent file, and never strand accounts that were already
seeded somewhere else.
"""

import os
from pathlib import Path

import pytest

from orpheus_ui.auth import db as auth_db


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("ORPHEUS_UI_DATABASE_URL", raising=False)
    monkeypatch.delenv("ORPHEUS_DATA_ROOT", raising=False)


def _no_legacy(monkeypatch, present=False):
    """Pretend the pre-data-root location does or does not hold a database."""
    monkeypatch.setattr(auth_db, "LEGACY_DB_PATH", Path("/nonexistent/orpheus/users.db"))
    if present:
        raise AssertionError("use _legacy_at for a present legacy file")


def _legacy_at(monkeypatch, path: Path):
    monkeypatch.setattr(auth_db, "LEGACY_DB_PATH", path)


class TestResolveDatabaseUrl:
    def test_explicit_env_override_wins(self, monkeypatch, tmp_path):
        """The systemd unit sets this, so a deployed station is never inferred."""
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        monkeypatch.setenv("ORPHEUS_UI_DATABASE_URL", "sqlite+aiosqlite:///explicit.db")

        assert auth_db.resolve_database_url() == "sqlite+aiosqlite:///explicit.db"

    def test_url_is_built_from_the_resolved_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        _no_legacy(monkeypatch)
        monkeypatch.setattr(auth_db, "DEV_DB_PATH", tmp_path / "dev-unused.db")

        url = auth_db.resolve_database_url()

        assert url == f"sqlite+aiosqlite:///{tmp_path / 'users.db'}"


class TestResolveDbPath:
    def test_uses_the_configured_data_root_for_a_fresh_install(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        _no_legacy(monkeypatch)
        monkeypatch.setattr(auth_db, "DEV_DB_PATH", tmp_path / "dev-unused.db")

        assert auth_db.resolve_db_path() == tmp_path / "users.db"

    def test_creates_the_data_root_when_it_is_missing(self, monkeypatch, tmp_path):
        root = tmp_path / "not-yet"
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(root))
        _no_legacy(monkeypatch)
        monkeypatch.setattr(auth_db, "DEV_DB_PATH", tmp_path / "dev-unused.db")

        assert auth_db.resolve_db_path() == root / "users.db"
        assert root.is_dir()

    def test_existing_database_at_the_data_root_is_used(self, monkeypatch, tmp_path):
        existing = tmp_path / "users.db"
        existing.write_text("")
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        # A legacy file also exists; the configured root still wins.
        legacy = tmp_path / "legacy" / "users.db"
        legacy.parent.mkdir()
        legacy.write_text("")
        _legacy_at(monkeypatch, legacy)

        assert auth_db.resolve_db_path() == existing

    def test_legacy_location_is_honored_when_it_holds_the_accounts(
        self, monkeypatch, tmp_path
    ):
        """A station seeded before this resolution existed keeps its accounts."""
        legacy = tmp_path / "legacy" / "users.db"
        legacy.parent.mkdir()
        legacy.write_text("")
        _legacy_at(monkeypatch, legacy)
        root = tmp_path / "new-root"
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(root))
        monkeypatch.setattr(auth_db, "DEV_DB_PATH", tmp_path / "dev-unused.db")

        assert auth_db.resolve_db_path() == legacy

    def test_a_stray_checkout_database_does_not_win(self, monkeypatch, tmp_path):
        """The defect this fix exists for: accounts living in the source tree."""
        dev = tmp_path / "checkout" / "users.db"
        dev.parent.mkdir()
        dev.write_text("")
        monkeypatch.setattr(auth_db, "DEV_DB_PATH", dev)
        _no_legacy(monkeypatch)
        root = tmp_path / "fresh-root"
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(root))

        assert auth_db.resolve_db_path() == root / "users.db"

    def test_falls_back_to_the_dev_path_when_the_root_is_unusable(
        self, monkeypatch, tmp_path
    ):
        unwritable = tmp_path / "readonly"
        unwritable.mkdir()
        unwritable.chmod(0o500)
        try:
            monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(unwritable))
            _no_legacy(monkeypatch)
            dev = tmp_path / "dev.db"
            monkeypatch.setattr(auth_db, "DEV_DB_PATH", dev)

            assert auth_db.resolve_db_path() == dev
        finally:
            unwritable.chmod(0o700)

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
    def test_falls_back_when_the_root_cannot_be_created(self, monkeypatch, tmp_path):
        parent = tmp_path / "locked"
        parent.mkdir()
        parent.chmod(0o500)
        try:
            monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(parent / "child"))
            _no_legacy(monkeypatch)
            dev = tmp_path / "dev.db"
            monkeypatch.setattr(auth_db, "DEV_DB_PATH", dev)

            assert auth_db.resolve_db_path() == dev
        finally:
            parent.chmod(0o700)

    def test_accounts_stay_at_the_data_root_top_level(self, monkeypatch, tmp_path):
        """Deployed installs have the file here; this fix must not move it."""
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        _no_legacy(monkeypatch)
        monkeypatch.setattr(auth_db, "DEV_DB_PATH", tmp_path / "dev-unused.db")

        resolved = auth_db.resolve_db_path()

        assert resolved.parent == tmp_path
        assert resolved.name == "users.db"
