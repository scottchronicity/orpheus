"""/api/services/status reports the configured inventory, from systemd.

Regression: after the NATS and audio-output upgrade the dashboard still listed
orpheus-mqtt as "running" (it survives only as an Alias= of orpheus-backplane)
and orpheus-bluetooth-autoconnect as "stopped" (no longer installed), and
nothing said either entry was stale.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from orpheus_ui.api import system
from orpheus_ui.api.system import get_services_status

# What `systemctl show <unit> --property=Id,LoadState,ActiveState,SubState`
# printed on the station for each kind of entry.
UNITS = {
    "orpheus-backplane.service": ("orpheus-backplane.service", "loaded", "active", "running"),
    "orpheus-mqtt.service": ("orpheus-backplane.service", "loaded", "active", "running"),
    "orpheus-bluetooth-autoconnect.service": (
        "orpheus-bluetooth-autoconnect.service", "not-found", "inactive", "dead"),
    "orpheus-audio-output.service": ("orpheus-audio-output.service", "loaded", "active", "running"),
    "orpheus-gps.service": ("orpheus-gps.service", "loaded", "failed", "failed"),
}


def _fake_systemctl(argv, **_kwargs):
    assert argv[1] == "show"
    unit_id, load, active, sub = UNITS[argv[2]]
    return subprocess.CompletedProcess(
        argv, 0,
        stdout=f"Id={unit_id}\nLoadState={load}\nActiveState={active}\nSubState={sub}\n",
        stderr="",
    )


@pytest.fixture(autouse=True)
def _fresh_stale_report():
    system._reported_stale_services.clear()  # noqa: SLF001
    yield
    system._reported_stale_services.clear()  # noqa: SLF001


def _status(services):
    config = MagicMock()
    config.dashboard_services.return_value = services
    with (
        patch("shutil.which", return_value="/bin/systemctl"),
        patch("subprocess.run", side_effect=_fake_systemctl),
        patch("orpheus_common.OrpheusConfig.get_instance", return_value=config),
    ):
        services = get_services_status(user=MagicMock()).services
    return {s.name: s for s in services}, [s.name for s in services]


def test_reports_exactly_the_configured_inventory_in_order():
    configured = ["orpheus-backplane", "orpheus-audio-output", "orpheus-gps"]
    _, names = _status(configured)
    assert names == configured


def test_real_units_report_their_state():
    by_name, _ = _status(["orpheus-backplane", "orpheus-audio-output"])
    assert by_name["orpheus-backplane"].status == "running"
    assert by_name["orpheus-backplane"].reason == ""
    assert by_name["orpheus-audio-output"].status == "running"


def test_alias_of_renamed_unit_is_flagged_not_silently_running():
    by_name, _ = _status(["orpheus-mqtt"])
    entry = by_name["orpheus-mqtt"]
    assert "alias of orpheus-backplane.service" in entry.reason
    assert "'orpheus-backplane'" in entry.reason


def test_retired_unit_is_reported_as_not_installed_not_stopped():
    by_name, _ = _status(["orpheus-bluetooth-autoconnect"])
    entry = by_name["orpheus-bluetooth-autoconnect"]
    assert entry.status == "unknown"
    assert "not installed" in entry.reason
    assert "dashboard.services" in entry.reason


def test_failed_unit_names_its_state():
    by_name, _ = _status(["orpheus-gps"])
    assert by_name["orpheus-gps"].status == "stopped"
    assert "failed" in by_name["orpheus-gps"].reason


def test_stale_entry_is_logged_once_not_on_every_poll():
    with patch.object(system.logger, "warning") as warn:
        _status(["orpheus-mqtt", "orpheus-bluetooth-autoconnect"])
        _status(["orpheus-mqtt", "orpheus-bluetooth-autoconnect"])
    assert warn.call_count == 2
