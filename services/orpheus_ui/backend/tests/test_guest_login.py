"""Guest quick-login: server-side credential, operator-controlled, read-only.

These pin the replacement for a login page that printed working credentials
and shipped the guest password in the browser bundle.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from orpheus_ui.auth.models import User, UserRole

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _config_path(monkeypatch):
    """``orpheus_ui.main`` resolves config at import; point it at the example."""
    monkeypatch.setenv(
        "ORPHEUS_CONFIG_PATH", str(REPO_ROOT / "config" / "orpheus.example.yaml")
    )


def _guest(is_active: bool = True) -> User:
    user = MagicMock(spec=User)
    user.is_active = is_active
    user.role = UserRole.VIEWER.value
    user.is_superuser = False
    return user


class TestGuestLoginEndpoint:
    def test_returns_a_token_when_enabled(self):
        from orpheus_ui import main

        guest = _guest()
        manager = MagicMock()
        manager.get_by_email = AsyncMock(return_value=guest)

        strategy = MagicMock()
        strategy.write_token = AsyncMock(return_value="a-jwt")

        with (
            patch.object(main, "_guest_quick_login_enabled", return_value=True),
            patch.object(main, "get_jwt_strategy", return_value=strategy),
        ):
            result = _run(main.guest_login(user_manager=manager))

        assert result == {"access_token": "a-jwt", "token_type": "bearer"}

    def test_refused_when_knob_is_off(self):
        from orpheus_ui import main

        manager = MagicMock()
        manager.get_by_email = AsyncMock(return_value=_guest())

        with patch.object(main, "_guest_quick_login_enabled", return_value=False):
            with pytest.raises(HTTPException) as exc:
                _run(main.guest_login(user_manager=manager))

        assert exc.value.status_code == 403
        # The account is never looked up when the feature is off.
        manager.get_by_email.assert_not_called()

    def test_refused_when_guest_account_is_missing(self):
        from orpheus_ui import main

        manager = MagicMock()
        manager.get_by_email = AsyncMock(return_value=None)

        with patch.object(main, "_guest_quick_login_enabled", return_value=True):
            with pytest.raises(HTTPException) as exc:
                _run(main.guest_login(user_manager=manager))

        assert exc.value.status_code == 403

    def test_refused_when_guest_account_is_inactive(self):
        from orpheus_ui import main

        manager = MagicMock()
        manager.get_by_email = AsyncMock(return_value=_guest(is_active=False))

        with patch.object(main, "_guest_quick_login_enabled", return_value=True):
            with pytest.raises(HTTPException) as exc:
                _run(main.guest_login(user_manager=manager))

        assert exc.value.status_code == 403

    def test_response_carries_no_password(self):
        """The whole point: the credential stays on the server."""
        from orpheus_ui import main

        strategy = MagicMock()
        strategy.write_token = AsyncMock(return_value="a-jwt")
        manager = MagicMock()
        manager.get_by_email = AsyncMock(return_value=_guest())

        with (
            patch.object(main, "_guest_quick_login_enabled", return_value=True),
            patch.object(main, "get_jwt_strategy", return_value=strategy),
        ):
            result = _run(main.guest_login(user_manager=manager))

        assert "guest" not in str(result.values()).lower().replace("guest-login", "")
        assert "password" not in result

    def test_guest_token_is_issued_for_a_viewer_not_an_admin(self):
        """Quick login must not be an elevation path."""
        from orpheus_ui import main

        guest = _guest()
        captured = {}

        async def _write_token(user):
            captured["user"] = user
            return "a-jwt"

        strategy = MagicMock()
        strategy.write_token = _write_token
        manager = MagicMock()
        manager.get_by_email = AsyncMock(return_value=guest)

        with (
            patch.object(main, "_guest_quick_login_enabled", return_value=True),
            patch.object(main, "get_jwt_strategy", return_value=strategy),
        ):
            _run(main.guest_login(user_manager=manager))

        assert captured["user"].role == UserRole.VIEWER.value
        assert captured["user"].is_superuser is False

    @pytest.mark.parametrize(
        "promote",
        [
            pytest.param({"is_superuser": True}, id="promoted-to-superuser"),
            pytest.param({"role": UserRole.ADMIN.value}, id="promoted-to-admin-role"),
            pytest.param(
                {"is_superuser": True, "role": UserRole.ADMIN.value}, id="repointed-at-an-admin"
            ),
        ],
    )
    def test_refused_when_the_guest_account_is_privileged(self, promote):
        """The account behind ORPHEUS_UI_GUEST_EMAIL can be promoted (PATCH
        /users/{id} sets is_superuser) or repointed at a real one. Either way
        this unauthenticated endpoint must not hand out its token."""
        from orpheus_ui import main

        user = _guest()
        for attr, value in promote.items():
            setattr(user, attr, value)

        strategy = MagicMock()
        strategy.write_token = AsyncMock(return_value="a-jwt")
        manager = MagicMock()
        manager.get_by_email = AsyncMock(return_value=user)

        with (
            patch.object(main, "_guest_quick_login_enabled", return_value=True),
            patch.object(main, "get_jwt_strategy", return_value=strategy),
        ):
            with pytest.raises(HTTPException) as exc:
                _run(main.guest_login(user_manager=manager))

        assert exc.value.status_code == 403
        strategy.write_token.assert_not_called()


class TestGuestQuickLoginKnob:
    def test_defaults_on_for_a_config_without_the_key(self):
        from orpheus_common.config import UIConfig

        assert UIConfig.from_dict({}).guest_quick_login is True
        assert UIConfig().guest_quick_login is True

    def test_reads_false_from_config(self):
        from orpheus_common.config import UIConfig

        assert UIConfig.from_dict({"guest_quick_login": False}).guest_quick_login is False

    def test_missing_ui_section_leaves_quick_login_on(self):
        """An older config must keep today's behavior."""
        from orpheus_ui import main

        with patch.object(main, "config", MagicMock(ui=None)):
            assert main._guest_quick_login_enabled() is True


class TestPublicConfigEndpoint:
    def test_serves_the_login_flags(self):
        from orpheus_ui import main

        cfg = MagicMock()
        cfg.dashboard_poll_interval.return_value = 5000
        cfg.ui.guest_quick_login = False

        with (
            patch.object(main, "config", cfg),
            patch.object(main, "_default_credentials_in_use", True),
        ):
            payload = main.get_config()

        assert payload["guest_quick_login"] is False
        assert payload["default_credentials_in_use"] is True
        assert payload["poll_interval"] == 5000

    def test_never_serves_a_credential(self):
        from orpheus_ui import main

        cfg = MagicMock()
        cfg.dashboard_poll_interval.return_value = 5000
        cfg.ui.guest_quick_login = True

        with (
            patch.object(main, "config", cfg),
            patch.object(main, "_default_credentials_in_use", True),
        ):
            payload = main.get_config()

        serialized = str(payload).lower()
        assert "changeme" not in serialized
        assert "password" not in serialized


class TestSeededDefaultsDetection:
    """The rotation prompt is driven by the stored hashes, not the environment."""

    @staticmethod
    def _session_yielding(users):
        """A stubbed ``async_session_maker`` whose queries return ``users`` in order."""
        results = []
        for user in users:
            result = MagicMock()
            result.scalar_one_or_none.return_value = user
            results.append(result)

        session = MagicMock()
        session.execute = AsyncMock(side_effect=results)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return MagicMock(return_value=ctx)

    def test_true_while_a_default_password_still_verifies(self):
        from fastapi_users.password import PasswordHelper

        from orpheus_ui.auth import seed

        admin = MagicMock()
        admin.hashed_password = PasswordHelper().hash(seed.SHIPPED_ADMIN_PASSWORD)

        with patch.object(seed, "async_session_maker", self._session_yielding([admin])):
            assert _run(seed.seeded_defaults_in_use()) is True

    def test_true_even_after_the_environment_is_set_on_a_seeded_box(self, monkeypatch):
        """The vulnerable install: the operator set the variables AFTER the first
        start, so seeding (guarded on an empty user table) never re-ran and
        ``changeme`` still logs in. Comparing the environment value against the
        stored hash clears the warning on exactly this box."""
        from fastapi_users.password import PasswordHelper

        from orpheus_ui.auth import seed

        monkeypatch.setattr(seed, "DEFAULT_ADMIN_PASSWORD", "a-long-random-password")
        monkeypatch.setattr(seed, "DEFAULT_GUEST_PASSWORD", "another-one")

        admin = MagicMock()
        admin.hashed_password = PasswordHelper().hash("changeme")

        with patch.object(seed, "async_session_maker", self._session_yielding([admin])):
            assert _run(seed.seeded_defaults_in_use()) is True

    def test_false_for_a_box_hardened_before_the_first_start(self, monkeypatch):
        """The other direction: the environment was set BEFORE seeding, so the
        stored hash is the operator's own password. No scare banner."""
        from fastapi_users.password import PasswordHelper

        from orpheus_ui.auth import seed

        monkeypatch.setattr(seed, "DEFAULT_ADMIN_PASSWORD", "a-long-random-password")
        monkeypatch.setattr(seed, "DEFAULT_GUEST_PASSWORD", "another-one")

        helper = PasswordHelper()
        admin = MagicMock()
        admin.hashed_password = helper.hash("a-long-random-password")
        guest = MagicMock()
        guest.hashed_password = helper.hash("another-one")

        with patch.object(seed, "async_session_maker", self._session_yielding([admin, guest])):
            assert _run(seed.seeded_defaults_in_use()) is False

    def test_the_shipped_constants_are_literals(self):
        """They are the credentials a copy of the repo already knows; an
        environment read here is what inverted the check."""
        from orpheus_ui.auth import seed

        assert seed.SHIPPED_ADMIN_PASSWORD == "changeme"
        assert seed.SHIPPED_GUEST_PASSWORD == "guest"

    def test_a_renamed_admin_is_still_checked_under_its_seeded_address(self, monkeypatch):
        """``ORPHEUS_UI_ADMIN_EMAIL`` set after the first start does not rename
        the seeded row, so both addresses get looked up."""
        from orpheus_ui.auth import seed

        monkeypatch.setattr(seed, "DEFAULT_ADMIN_EMAIL", "ops@example.com")

        emails = [email for email, _ in seed._accounts_to_check()]
        assert "ops@example.com" in emails
        assert seed.SHIPPED_ADMIN_EMAIL in emails

    def test_the_default_environment_costs_two_lookups(self):
        """De-duplicated, so the common case does not pay extra password hashes."""
        from orpheus_ui.auth import seed

        assert len(seed._accounts_to_check()) == 2

    def test_false_once_both_passwords_are_rotated(self):
        from fastapi_users.password import PasswordHelper

        from orpheus_ui.auth import seed

        helper = PasswordHelper()
        admin = MagicMock()
        admin.hashed_password = helper.hash("a-rotated-admin-password")
        guest = MagicMock()
        guest.hashed_password = helper.hash("a-rotated-guest-password")

        with patch.object(seed, "async_session_maker", self._session_yielding([admin, guest])):
            assert _run(seed.seeded_defaults_in_use()) is False

    def test_false_when_the_check_cannot_run(self):
        """A broken check must not paint a permanent warning."""
        from orpheus_ui.auth import seed

        broken = MagicMock(side_effect=RuntimeError("no database"))
        with patch.object(seed, "async_session_maker", broken):
            assert _run(seed.seeded_defaults_in_use()) is False


def _run(coro):
    """Drive a coroutine to completion without a live event loop."""
    import asyncio

    return asyncio.run(coro)
