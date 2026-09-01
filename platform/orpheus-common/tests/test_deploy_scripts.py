"""The installers and systemd units, as behaviour rather than as text.

These live next to orpheus_common because config resolution is its contract:
``config.py`` defines the search order every component is supposed to share,
and a unit that pins ``ORPHEUS_CONFIG_PATH`` opts out of it silently.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMON_INSTALL_SH = REPO_ROOT / "platform" / "orpheus-common" / "systemd" / "install.sh"
NATS_INSTALL_SH = REPO_ROOT / "services" / "orpheus-backplane" / "scripts" / "install-nats.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")


def _call(script: Path, snippet: str) -> subprocess.CompletedProcess:
    """Source an installer and run one snippet against its functions."""
    return subprocess.run(
        ["bash", "-c", f'source "{script}"\n{snippet}'],
        capture_output=True,
        text=True,
        check=False,
    )


class TestCommonInstallerConfigSeed:
    """Step 1 of the documented Jetson install is ``sudo ./systemd/install.sh``."""

    def _resolve(self, config_dir: Path) -> str:
        result = _call(COMMON_INSTALL_SH, f'resolve_repo_config "{config_dir}"')
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_a_fresh_clone_seeds_from_the_example(self, tmp_path):
        """The repo ships only orpheus.example.yaml, so requiring orpheus.yaml
        aborted the operator's very first command — and step 2 then told them to
        edit a file that was never created."""
        (tmp_path / "orpheus.example.yaml").write_text("mqtt: {}\n")

        assert self._resolve(tmp_path) == str(tmp_path / "orpheus.example.yaml")

    def test_a_real_config_still_wins(self, tmp_path):
        (tmp_path / "orpheus.example.yaml").write_text("mqtt: {}\n")
        (tmp_path / "orpheus.yaml").write_text("mqtt: {host: mine}\n")

        assert self._resolve(tmp_path) == str(tmp_path / "orpheus.yaml")

    def test_nothing_to_seed_from_resolves_empty(self, tmp_path):
        """An empty answer is what drives the installer's explicit error."""
        assert self._resolve(tmp_path) == ""

    def test_the_shipped_repo_has_something_to_seed_from(self):
        """The premise of the bug: a clean checkout has no config/orpheus.yaml."""
        config = REPO_ROOT / "config"
        assert (config / "orpheus.example.yaml").exists()
        assert self._resolve(config) != ""


class TestBrokerConfigIsSeededOnce:
    """``make install-backbone`` with no LISTEN= is documented as idempotent."""

    def _seed(self, src: Path, dst: Path) -> subprocess.CompletedProcess:
        result = _call(NATS_INSTALL_SH, f'seed_broker_config "{src}" "{dst}"')
        assert result.returncode == 0, result.stderr
        return result

    def test_seeds_the_loopback_default_on_a_fresh_host(self, tmp_path):
        src = tmp_path / "nats.conf"
        src.write_text("listen: 127.0.0.1:4222\n")
        dst = tmp_path / "etc" / "nats.conf"
        dst.parent.mkdir()

        self._seed(src, dst)

        assert dst.read_text() == "listen: 127.0.0.1:4222\n"

    def test_a_lan_opened_broker_survives_a_reinstall(self, tmp_path):
        """Overwriting here reverts the listener to loopback and cuts off every
        remote agent, from a step the rollout runbook calls idempotent."""
        src = tmp_path / "nats.conf"
        src.write_text("listen: 127.0.0.1:4222\n")
        dst = tmp_path / "etc" / "nats.conf"
        dst.parent.mkdir()
        dst.write_text('listen: 0.0.0.0:4222\ninclude "nats.auth"\n')

        self._seed(src, dst)

        assert dst.read_text() == 'listen: 0.0.0.0:4222\ninclude "nats.auth"\n'

    def test_sourcing_the_installer_installs_nothing(self):
        """The tests above rely on it; so does anyone who reads the file."""
        result = _call(NATS_INSTALL_SH, "true")
        assert result.returncode == 0, result.stderr
        assert "Installing Orpheus backplane broker" not in result.stdout


class TestTheSweepUnitHasAnInterpreter:
    """orpheus-storage-sweep shipped naming a python that no installer built.

    The platform was the one component deployed to /opt without a venv — fine
    while nothing ran it directly, and wrong the moment it started shipping a
    unit of its own. Nothing caught it: a dev tree has an editable install, so
    the ExecStart resolves there and only there.
    """

    UNIT = REPO_ROOT / "platform" / "orpheus-common" / "systemd" / "orpheus-storage-sweep.service"

    @staticmethod
    def _exec_start_python(unit: Path) -> str:
        for line in unit.read_text().splitlines():
            if line.startswith("ExecStart="):
                return line.split("=", 1)[1].split()[0]
        raise AssertionError(f"{unit} has no ExecStart")

    def _installer_var(self, name: str) -> str:
        result = _call(COMMON_INSTALL_SH, f'printf "%s" "${name}"')
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_the_installer_builds_the_venv_the_unit_runs(self):
        venv_dir = self._installer_var("VENV_DIR")
        assert venv_dir, "install.sh no longer defines VENV_DIR"
        assert self._exec_start_python(self.UNIT) == f"{venv_dir}/bin/orpheus-storage-sweep", (
            "the sweep's ExecStart and the venv install.sh builds have drifted apart; "
            "the timer would fire every 15 minutes onto a missing interpreter"
        )

    def test_the_unit_runs_the_console_script_not_dash_m(self):
        """`python -m orpheus_common.storage.sweep` warns on every single run.

        The package __init__ imports the sweep module, so running it as __main__
        imports it twice and runpy prints a RuntimeWarning. Harmless, except it
        lands in the journal every 15 minutes forever — in the component whose
        job is keeping the disk clear.
        """
        exec_start = next(
            line[len("ExecStart=") :]
            for line in self.UNIT.read_text().splitlines()
            if line.startswith("ExecStart=")
        )
        assert "-m orpheus_common" not in exec_start
        assert exec_start.endswith("/bin/orpheus-storage-sweep")

    def test_the_console_script_the_unit_names_is_declared(self):
        """The ExecStart is only real if pyproject actually ships that script."""
        pyproject = (REPO_ROOT / "platform" / "orpheus-common" / "pyproject.toml").read_text()
        assert 'orpheus-storage-sweep = "orpheus_common.storage.sweep:main"' in pyproject

    def test_the_installer_smoke_tests_the_units_own_exec_start(self):
        """It must read the binary out of the unit, not name it a second time.

        Naming it twice is how an installer ends up smoke-testing one thing and
        enabling another.
        """
        body = COMMON_INSTALL_SH.read_text()
        assert "sed -n 's/^ExecStart=//p'" in body
        assert "${exec_start} --help" in body

    def test_the_installer_actually_creates_it(self):
        """Naming the path is not building it — that was the whole bug."""
        body = COMMON_INSTALL_SH.read_text()
        assert '"${PYTHON_BIN}" -m venv "${VENV_DIR}"' in body
        assert '-m pip install --no-cache-dir "${INSTALL_ROOT}"' in body

    @staticmethod
    def _deploy_root(component: Path) -> str:
        """Where this component's source lands under /opt — the same mapping
        ``make verify-deploy`` uses. The UI is the one that is not its own
        directory name."""
        kind, name = component.parent.name, component.name
        if name == "orpheus_ui":
            return "/opt/orpheus/ui"
        if kind == "platform":
            return f"/opt/orpheus/platform/{name}"
        if kind == "services":
            return f"/opt/orpheus/services/{name}"
        return f"/opt/orpheus/agents/{name}"

    def test_no_unit_runs_an_interpreter_nothing_installs(self):
        """The general form, so the next unit to ship does not repeat it.

        A component's ExecStart may only name a binary in its own venv (its
        installer builds that) or a system path (the OS provides it). Borrowing
        another component's venv works until someone installs a host without
        that component.
        """
        offenders = []
        for unit in sorted(REPO_ROOT.glob("*/*/systemd/*.service")):
            binary = self._exec_start_python(unit)
            own_venv = f"{self._deploy_root(unit.parents[1])}/venv/"
            if binary.startswith("/opt/orpheus/") and not binary.startswith(own_venv):
                offenders.append(f"{unit.relative_to(REPO_ROOT)} -> {binary}")
        assert offenders == [], (
            "these units run an interpreter belonging to another component, which "
            f"is absent on any host that component is not installed on: {offenders}"
        )


class TestUnitsShareOneConfigSearchOrder:
    """``ORPHEUS_CONFIG_PATH`` outranks the search list in config.py, so a unit
    that pins it runs a different config from the rest of the box — and every
    runbook edits the copy the rest of the box reads."""

    def _units(self):
        units = sorted(REPO_ROOT.glob("*/*/systemd/*.service"))
        assert units, "no systemd units found; the glob is wrong"
        return units

    @staticmethod
    def _pins_a_config_path(unit: Path) -> bool:
        """Directives only — the units carry comments saying why it is absent."""
        return any(
            line.strip().startswith("Environment=") and "ORPHEUS_CONFIG_PATH" in line
            for line in unit.read_text().splitlines()
        )

    def test_no_unit_pins_a_config_path(self):
        offenders = [
            str(unit.relative_to(REPO_ROOT))
            for unit in self._units()
            if self._pins_a_config_path(unit)
        ]
        assert offenders == [], (
            "these units pin ORPHEUS_CONFIG_PATH and so read a different config "
            f"from every other component: {offenders}"
        )

    def test_no_installer_generates_a_pinned_config_path(self):
        """The UI's installer used to write its own unit with the pin inside."""
        scripts = sorted(REPO_ROOT.glob("*/*/systemd/*.sh")) + sorted(
            REPO_ROOT.glob("*/*/scripts/*.sh")
        )
        assert scripts, "no installer scripts found; the glob is wrong"
        offenders = [
            str(script.relative_to(REPO_ROOT))
            for script in scripts
            if 'Environment="ORPHEUS_CONFIG_PATH' in script.read_text()
        ]
        assert offenders == []
