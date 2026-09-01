"""Authorization boundaries: who may create accounts, read secrets, and write.

These pin exposures that were reachable by anyone who could open the port:
self-service admin registration, an unauthenticated runtime-config dump, and
write endpoints that accepted any authenticated account.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from orpheus_ui.api import diagnostics, entities
from orpheus_ui.auth.backend import current_active_user, require_role
from orpheus_ui.auth.models import User, UserRole


def _user(role: str, is_superuser: bool = False) -> User:
    user = MagicMock(spec=User)
    user.role = role
    user.is_superuser = is_superuser
    return user


def _client(router, actor: User) -> TestClient:
    """A client whose authenticated identity is ``actor``.

    Only ``current_active_user`` is overridden — ``require_role`` runs for
    real, so the role check itself is under test.
    """
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_active_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


class TestRoleGateIsEnforced:
    """``require_role`` must actually refuse non-admins."""

    @pytest.mark.asyncio
    async def test_viewer_is_refused(self):
        dependency = require_role("admin")
        with pytest.raises(HTTPException) as exc:
            await dependency(user=_user(UserRole.VIEWER.value))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_passes(self):
        dependency = require_role("admin")
        actor = _user(UserRole.ADMIN.value)
        assert await dependency(user=actor) is actor

    @pytest.mark.asyncio
    async def test_superuser_passes_regardless_of_role(self):
        dependency = require_role("admin")
        actor = _user(UserRole.VIEWER.value, is_superuser=True)
        assert await dependency(user=actor) is actor


class TestWriteEndpointsRequireAdmin:
    """The seeded guest must not be able to change state."""

    WRITE_ROUTES = (
        ("/api/equivalences/accept", entities),
        ("/api/equivalences/reject", entities),
        ("/api/equivalences/scan", entities),
    )

    @pytest.mark.parametrize(("path", "module"), WRITE_ROUTES)
    def test_viewer_refused(self, path, module):
        client = _client(module.router, _user(UserRole.VIEWER.value))
        resp = client.post(path, json={})
        assert resp.status_code == 403

    def test_playback_refused_for_viewer(self):
        client = _client(diagnostics.router, _user(UserRole.VIEWER.value))
        resp = client.post(
            "/api/audio/playback/play", json={"sound_name": "test.wav"}
        )
        assert resp.status_code == 403

    @patch("orpheus_ui.api.entities.TaxonomyEquivalenceDB")
    def test_admin_reaches_the_handler(self, mock_eq_db):
        """An admin gets past the gate — 403 would mean the gate is too tight."""
        client = _client(entities.router, _user(UserRole.ADMIN.value))
        resp = client.post(
            "/api/equivalences/accept",
            json={
                "a": {"namespace": "ioc", "id": "Corvus brachyrhynchos"},
                "b": {"namespace": "audioset", "id": "/m/04s8yn"},
            },
        )
        assert resp.status_code != 403


class TestRoleIsNotSelfAssignable:
    """``PATCH /users/me`` shares this schema, so it must not carry a role."""

    def test_user_update_has_no_role_field(self):
        from orpheus_ui.auth.schemas import UserUpdate

        assert "role" not in UserUpdate.model_fields

    def test_role_in_payload_is_ignored(self):
        from orpheus_ui.auth.schemas import UserUpdate

        update = UserUpdate(display_name="Guest", role="admin")
        assert not hasattr(update, "role") or update.role != "admin"

    def test_role_is_still_settable_at_creation(self):
        """Superuser-gated account creation still grants roles."""
        from orpheus_ui.auth.schemas import UserCreate

        assert UserCreate(
            email="a@example.com", password="x" * 12, role="admin"
        ).role == "admin"


class TestPrivilegedRoutesAreGated:
    """Registration and the config dump are superuser-only at the app level."""

    def _app(self):
        import orpheus_ui.main as main

        return main.app

    def test_register_route_requires_a_dependency(self):
        from orpheus_ui.auth.backend import current_superuser

        route = next(
            r for r in self._app().routes if getattr(r, "path", "") == "/auth/register"
        )
        gated = any(
            getattr(d.call, "__wrapped__", d.call) is current_superuser
            or d.call is current_superuser
            for d in route.dependant.dependencies
        )
        assert gated, "POST /auth/register must be superuser-gated"

    def test_debug_config_is_superuser_gated(self):
        """Not merely "has a dependency" — that passes if the gate is downgraded
        to any signed-in viewer, which is the regression this exists to catch.
        docs/security.md promises admin yes / guest no for this route."""
        from orpheus_ui.auth.backend import current_superuser

        route = next(
            r
            for r in self._app().routes
            if getattr(r, "path", "") == "/api/debug/config"
        )
        gated = any(
            getattr(d.call, "__wrapped__", d.call) is current_superuser
            or d.call is current_superuser
            for d in route.dependant.dependencies
        )
        assert gated, "/api/debug/config must be superuser-gated"

    def test_public_config_stays_open(self):
        """The frontend bootstrap endpoint is deliberately public."""
        route = next(
            r for r in self._app().routes if getattr(r, "path", "") == "/api/config"
        )
        assert not route.dependant.dependencies
