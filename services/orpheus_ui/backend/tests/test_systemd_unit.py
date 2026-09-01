"""The unit the UI actually runs under.

``install-service.sh`` used to regenerate the unit from a heredoc instead of
installing the checked-in file, so the two diverged with nothing to catch it:
the generated one never gained ``EnvironmentFile=``, and on a real box
``/opt/orpheus/config/.env`` — the per-host backbone URL and the seeded account
passwords — never reached the service.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SYSTEMD_DIR = REPO_ROOT / "services" / "orpheus_ui" / "systemd"
UNIT = SYSTEMD_DIR / "orpheus-ui.service"
INSTALLER = SYSTEMD_DIR / "install-service.sh"


@pytest.fixture(scope="module")
def unit() -> str:
    return UNIT.read_text()


@pytest.fixture(scope="module")
def installer() -> str:
    return INSTALLER.read_text()


def _directives(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]


class TestTheCheckedInUnitIsTheInstalledOne:
    def test_the_installer_copies_the_unit_rather_than_writing_one(self, installer):
        assert "orpheus-ui.service <<EOF" not in installer, (
            "a generated unit drifts from the checked-in one; copy the file instead"
        )
        assert 'UNIT_SRC="${SCRIPT_DIR}/orpheus-ui.service"' in installer

    def test_the_installed_copy_reaches_systemd(self, installer):
        assert "cp \"${UNIT_DST}\" /etc/systemd/system/" in installer


class TestUnitContents:
    def test_reads_the_shared_env_file(self, unit):
        """Optional (the leading -), so a box without one still starts."""
        assert "EnvironmentFile=-/opt/orpheus/config/.env" in _directives(unit)

    def test_does_not_pin_a_config_path(self, unit):
        """It outranks the search list, so pinning it made the UI read a
        different orpheus.yaml from every other component on the box."""
        assert not any(
            line.startswith("Environment=") and "ORPHEUS_CONFIG_PATH" in line
            for line in _directives(unit)
        )

    def test_uvicorn_access_logging_is_off(self, unit):
        """Media elements authenticate with the session JWT in the query string,
        and the unit sends stdout to the journal — the access log would file a
        24h-valid, unrevocable token there on every clip fetch."""
        exec_start = next(line for line in _directives(unit) if line.startswith("ExecStart="))
        assert "--no-access-log" in exec_start

    def test_still_serves_the_documented_port(self, unit):
        exec_start = next(line for line in _directives(unit) if line.startswith("ExecStart="))
        assert "--port 8082" in exec_start

    def test_the_venv_and_node_are_on_path(self, unit):
        path_line = next(line for line in _directives(unit) if "PATH=" in line)
        assert "/opt/orpheus/ui/venv/bin" in path_line
        assert "/opt/orpheus/ui/.node/bin" in path_line
