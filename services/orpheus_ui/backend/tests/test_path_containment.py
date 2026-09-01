"""Path containment for the two routes that turn a URL into a file read.

The SPA catch-all is unauthenticated and the clip routes are reachable by any
signed-in account (guest quick-login included), so a traversal in either one
hands out ``/opt/orpheus/config/.env`` — the JWT secret and the seeded
passwords — and every role gate falls with it.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _config_path(monkeypatch):
    """``orpheus_ui.main`` resolves config at import; point it at the example."""
    monkeypatch.setenv("ORPHEUS_CONFIG_PATH", str(REPO_ROOT / "config" / "orpheus.example.yaml"))


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """A built-frontend layout with a secret sitting next to it, as on a Jetson."""
    from orpheus_ui import main

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html><title>Orpheus</title>")
    (static_dir / "assets" / "app.js").write_text("console.log('spa')")
    (tmp_path / "dot.env").write_text("ORPHEUS_UI_JWT_SECRET=super-secret")

    monkeypatch.setattr(main, "STATIC_DIR", str(static_dir))
    return static_dir


class TestSpaCatchAllContainment:
    """``GET /<anything>`` must never read outside the built bundle."""

    def _resolve(self, path):
        from orpheus_ui import main

        return Path(main.resolve_spa_path(path))

    def test_serves_a_file_inside_the_bundle(self, bundle):
        assert self._resolve("assets/app.js") == bundle / "assets" / "app.js"

    def test_unknown_route_falls_back_to_the_shell(self, bundle):
        assert self._resolve("dashboard/cameras") == bundle / "index.html"

    @pytest.mark.parametrize(
        "attack",
        [
            "../dot.env",
            "../../etc/passwd",
            "assets/../../dot.env",
            "..%2fdot.env",
            "/etc/passwd",
            "../" * 12 + "etc/passwd",
        ],
    )
    def test_traversal_serves_the_shell_not_a_file(self, bundle, attack):
        """Percent-encoding is decoded before the handler, so both forms land here."""
        assert self._resolve(attack) == bundle / "index.html"

    def test_a_symlink_out_of_the_bundle_is_refused(self, bundle):
        outside = bundle.parent / "dot.env"
        (bundle / "leak.txt").symlink_to(outside)

        assert self._resolve("leak.txt") == bundle / "index.html"

    @pytest.mark.parametrize("prefix", ["api/config", "auth/jwt/login", "users/me"])
    def test_api_prefixes_stay_404(self, bundle, prefix):
        with pytest.raises(HTTPException) as exc:
            self._resolve(prefix)

        assert exc.value.status_code == 404

    def test_the_route_delegates_to_the_resolver(self, bundle):
        """Guard against the containment being re-inlined and drifting."""
        from orpheus_ui import main

        route = next(
            (r for r in main.app.routes if getattr(r, "path", "") == "/{full_path:path}"), None
        )
        if route is None:
            pytest.skip("no built frontend in this checkout; the catch-all is not registered")

        import asyncio

        response = asyncio.run(route.endpoint(full_path="../dot.env"))
        assert Path(response.path) == bundle / "index.html"


class TestClipRouteContainment:
    """Clip filenames are attacker-controlled; the base directory must not be."""

    @pytest.fixture(autouse=True)
    def _storage(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "orpheus.yaml").write_text("mqtt:\n  password: broker-secret\n")
        return tmp_path

    def _audio(self, filename, channel_id="1"):
        from orpheus_ui.api import diagnostics

        return diagnostics.get_audio_clip(
            channel_id=channel_id, filename=filename, user=MagicMock()
        )

    def _video(self, filename, camera_id="orpheus-eye-1"):
        from orpheus_ui.api import diagnostics

        return diagnostics.get_video_clip(camera_id=camera_id, filename=filename, user=MagicMock())

    @pytest.mark.parametrize(
        "attack",
        [
            "../../../config/orpheus.yaml",
            "../" * 12 + "etc/passwd",
            "sub/../../../../config/orpheus.yaml",
        ],
    )
    def test_audio_traversal_is_refused(self, attack):
        with pytest.raises(HTTPException) as exc:
            self._audio(attack)

        assert exc.value.status_code == 400

    @pytest.mark.parametrize("attack", ["../../../config/orpheus.yaml", "../" * 12 + "etc/passwd"])
    def test_video_traversal_is_refused(self, attack):
        with pytest.raises(HTTPException) as exc:
            self._video(attack)

        assert exc.value.status_code == 400

    def test_a_real_audio_clip_still_serves(self, _storage):
        clip_dir = _storage / "audio" / "audio_motion" / "1"
        clip_dir.mkdir(parents=True)
        (clip_dir / "20260217T151656.flac").write_bytes(b"fLaC")

        response = self._audio("20260217T151656.flac")

        assert os.path.realpath(response.path) == os.path.realpath(
            clip_dir / "20260217T151656.flac"
        )
        assert response.media_type == "audio/flac"

    def test_a_missing_clip_is_a_404_not_a_400(self):
        """A contained-but-absent filename keeps its own error."""
        with pytest.raises(HTTPException) as exc:
            self._audio("never-recorded.flac")

        assert exc.value.status_code == 404

    def test_an_absolute_path_outside_the_data_root_is_refused(self):
        with pytest.raises(HTTPException) as exc:
            self._audio("/etc/passwd")

        assert exc.value.status_code == 400


class TestListingRouteContainment:
    """The routes that LIST files were never given the guard the serving routes have.

    They return metadata rather than bytes, so a traversal here leaks filenames,
    sizes, and timestamps from a directory the caller has no business seeing --
    not file contents. Narrower than the serving routes, and still not theirs to
    read, so the same guard applies.
    """

    @pytest.fixture(autouse=True)
    def _storage(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        return tmp_path

    @pytest.mark.parametrize(
        "attack",
        [
            "../XXXXXXX",  # length 10 with exactly two dots: passed the old format check
            "../../etc",
            "..",
            "2026.01.01/../../..",
        ],
    )
    def test_snapshot_listing_refuses_a_traversing_date(self, attack):
        from orpheus_ui.api import media

        with pytest.raises(HTTPException) as exc:
            media.get_camera_snapshots(camera_name="orpheus-eye-1", date=attack, user=MagicMock())

        assert exc.value.status_code == 400

    @pytest.mark.parametrize("attack", ["../XXXXXXX", "../../etc", "../" * 6])
    def test_timelapse_listing_refuses_a_traversing_date(self, attack):
        from orpheus_ui.api import media

        with pytest.raises(HTTPException) as exc:
            media.get_camera_timelapses(camera_name="orpheus-eye-1", date=attack, user=MagicMock())

        assert exc.value.status_code == 400

    @pytest.mark.parametrize("attack", ["../../..", "../orpheus-eye-2", "..", "/etc"])
    def test_video_clip_listing_refuses_an_unknown_camera(self, attack):
        from orpheus_ui.api import diagnostics

        with pytest.raises(HTTPException) as exc:
            diagnostics.get_video_clips(camera_id=attack, user=MagicMock())

        assert exc.value.status_code == 400

    def test_the_listing_and_serving_routes_share_one_camera_allowlist(self):
        """They drifted apart once; a shared constant is what stops it recurring."""
        from orpheus_ui.api import diagnostics

        assert "orpheus-eye-1" in diagnostics.VALID_CAMERAS
        assert "../../.." not in diagnostics.VALID_CAMERAS

    def test_a_legitimate_date_still_lists(self, _storage):
        from orpheus_ui.api import media

        result = media.get_camera_snapshots(
            camera_name="orpheus-eye-1", date="2026.01.01", user=MagicMock()
        )

        assert result["snapshots"] == []
        assert result["date"] == "2026.01.01"


class TestErrorResponsesAreOpaque:
    """An exception message in a response body hands out paths and internals."""

    def test_media_failure_does_not_return_the_exception_text(self, tmp_path, monkeypatch):
        from orpheus_ui.api import media

        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))

        def boom(*a, **k):
            raise RuntimeError("/opt/orpheus/config/.env is missing")

        monkeypatch.setattr(media.OrpheusConfig, "get_instance", boom)

        result = media.get_camera_snapshots(
            camera_name="orpheus-eye-1", date="2026.01.01", user=MagicMock()
        )

        assert "/opt/orpheus" not in result["error"]
        assert result["error"] == media.ERROR_OPAQUE
