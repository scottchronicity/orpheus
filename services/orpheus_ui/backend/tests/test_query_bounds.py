"""Historical query values must not 422 (server-side clamping owns the bounds).

The history endpoints accepted any int for ``days``/``page``/``page_size`` long
before request-level validation existed: ``days=0`` fell through to the default
window, and ``paginate()`` clamps page/page_size server-side. Request-level
``ge``/``le`` bounds briefly turned those previously-valid calls into 422s;
these tests pin the restored acceptance.
"""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orpheus_ui.api import diagnostics
from orpheus_ui.auth.backend import current_active_user
from orpheus_ui.auth.models import User


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(diagnostics.router)
    app.dependency_overrides[current_active_user] = lambda: MagicMock(spec=User)
    return TestClient(app)


class TestHistoricalQueryValuesStillAccepted:
    @patch("orpheus_ui.api.diagnostics.get_detection_db")
    def test_days_zero_uses_default_window_not_422(self, mock_get_db):
        mock_get_db.return_value.query.return_value = []
        resp = _client().get("/api/data/birds/history", params={"days": 0})
        assert resp.status_code == 200

    @patch("orpheus_ui.api.diagnostics.get_detection_db")
    def test_days_over_365_accepted_not_422(self, mock_get_db):
        mock_get_db.return_value.query.return_value = []
        resp = _client().get("/api/data/birds/history", params={"days": 400})
        assert resp.status_code == 200

    @patch("orpheus_ui.api.diagnostics.get_detection_db")
    def test_page_size_above_cap_clamps_not_422(self, mock_get_db):
        mock_get_db.return_value.query.return_value = []
        resp = _client().get(
            "/api/data/birds/history", params={"page": 1, "page_size": 5000}
        )
        assert resp.status_code == 200
        assert resp.json()["page_size"] == 1000  # paginate() clamped it

    @patch("orpheus_ui.api.diagnostics.get_detection_db")
    def test_page_zero_clamps_to_first_page_not_422(self, mock_get_db):
        mock_get_db.return_value.query.return_value = []
        resp = _client().get(
            "/api/data/birds/history", params={"page": 0, "page_size": 10}
        )
        assert resp.status_code == 200
        assert resp.json()["page"] == 1  # paginate() floors page at 1

    @patch("orpheus_ui.api.diagnostics.get_detection_db")
    def test_audio_events_history_days_zero_accepted(self, mock_get_db):
        mock_get_db.return_value.query.return_value = []
        resp = _client().get("/api/data/audio-events/history", params={"days": 0})
        assert resp.status_code == 200
