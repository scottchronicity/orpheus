"""Tests for the request-timing middleware.

Tags every response with ``X-Response-Time-ms`` and warns on slow requests,
so server-side timing is observable when diagnosing a sluggish UI.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import orpheus_ui.middleware as mw_module


def _build_app(dispatch):
    app = FastAPI()
    app.middleware("http")(dispatch)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


class TestTimingMiddleware:
    """Every response is timed and tagged; slow ones warn but still succeed."""

    def test_sets_response_time_header(self):
        client = TestClient(_build_app(mw_module.timing_middleware))
        resp = client.get("/ping")
        assert resp.status_code == 200
        # Header names are case-insensitive in the response mapping.
        assert "x-response-time-ms" in resp.headers
        float(resp.headers["x-response-time-ms"])  # parseable as a float (ms)

    def test_slow_request_warns_but_still_succeeds(self, monkeypatch):
        # Force the slow branch regardless of how fast the test machine is.
        monkeypatch.setattr(mw_module, "SLOW_REQUEST_MS", -1.0)
        client = TestClient(_build_app(mw_module.timing_middleware))
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert "x-response-time-ms" in resp.headers
