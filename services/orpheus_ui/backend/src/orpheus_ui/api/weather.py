"""Weather API endpoint — the UI tail of the Ecowitt weather-station integration.

Serves the latest ``WeatherReading`` ingested by ``orpheus-weather`` (see
``orpheus_common.weather``) so the Dashboard can show current conditions next to
the wildlife data. Most deploys have no weather station, so the endpoint is
feature-detected end to end: when ``weather.enabled`` is off, no reading exists
yet, or the config/DB can't be read, it returns ``{"available": false}`` (never
a 500) and the frontend hides the card entirely.
"""

import threading
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from orpheus_common.logging import get_logger
from orpheus_common.weather import WeatherDB

from orpheus_ui.auth.backend import current_active_user
from orpheus_ui.auth.models import User
from orpheus_ui.db import resolve_replica_path

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["weather"])

# Process-wide cached WeatherDB (mirrors db.get_detection_db): __init__ runs the
# CREATE TABLE IF NOT EXISTS schema check, so constructing one per poll would pay
# that write-lock cost on the shared SQLite file every HEALTH-tier request.
_weather_db: Optional[WeatherDB] = None
_weather_db_lock = threading.Lock()




def _get_weather_db() -> WeatherDB:
    """Return the process-wide ``WeatherDB``, constructing it once on first use.

    Honors the same replica routing as the detection reads (``ui.read_from_replica``
    + ``mirror.staging_path``): on a replica host the weather card reads the
    replica read-only instead of creating/locking a live ``orpheus.db`` there."""
    global _weather_db
    if _weather_db is None:
        with _weather_db_lock:
            if _weather_db is None:
                replica = resolve_replica_path()
                _weather_db = (
                    WeatherDB(db_path=replica, read_only=True)
                    if replica is not None
                    else WeatherDB()
                )
    return _weather_db


@router.get("/weather/latest")
def get_weather_latest(user: User = Depends(current_active_user)) -> Dict[str, Any]:
    """Latest weather reading for the Dashboard weather card.

    Returns ``{"available": false}`` when weather ingestion is disabled
    (``weather.enabled``, default off), when no reading has been ingested yet,
    or when the config/DB lookup fails — the frontend renders nothing in all of
    those cases. Otherwise ``{"available": true, ...reading fields...}``.
    """
    # Import config here to avoid circular imports (matches api/system.py).
    from orpheus_common import OrpheusConfig

    try:
        config = OrpheusConfig.get_instance()
        if not getattr(config.weather, "enabled", False):
            return {"available": False}
        reading = _get_weather_db().get_latest()
    except Exception as e:
        # Feature-detect, don't fail: a broken config or unreadable DB must
        # degrade to "no weather", never 500 the Dashboard poll.
        logger.warning("Weather lookup failed; reporting unavailable", error=str(e))
        return {"available": False}

    if reading is None:
        return {"available": False}
    return {"available": True, **reading.model_dump(mode="json")}
