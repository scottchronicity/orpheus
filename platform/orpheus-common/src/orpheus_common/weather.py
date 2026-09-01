"""Weather ingestion: pull ambient conditions into the state space.

[FEATURE] Ecowitt Weather Station Integration (Epic 5; depends on the entity-
type taxonomy). Lets agents correlate wildlife activity with weather — "do crows
visit before a storm?", "does coyote activity rise on cold nights?" — by feeding
``WeatherReading``s into the same SQLite DB as detections (so they join on time)
and onto MQTT for live consumers.

Shape mirrors the established orpheus-common patterns: a ``WeatherProvider`` ABC
(like the EventBus ABC), an ``orpheus-weather`` console-script + ``WeatherIngestor``
loop (like ``orpheus-replay``/``ReplayEngine``), and ``create_event_bus`` for the
bus. Everything here is internal contract the repo owns and is fully testable
with synthetic readings.

The ONE external contract — the Ecowitt local-API field names and units — is a
deliberate, flagged seam (``EcowittProvider._parse``). It is NOT mapped here:
the keys and units are vendor/firmware-specific and must be captured from the
real gateway, not guessed (AGENTS.md rule #7). Until grounded, the parse raises
``NotImplementedError`` with instructions; the ingestor degrades gracefully.
"""

from __future__ import annotations

import argparse
import signal
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Optional

from orpheus_common.detection.database import open_connection
from orpheus_common.event_bus import EventBus, create_event_bus
from orpheus_common.events import WeatherReading
from orpheus_common.logging import get_logger
from orpheus_common.storage import get_data_root
from orpheus_common.utils.time import interruptible_sleep as _interruptible_sleep
from orpheus_common.utils.time import utc_now_iso

logger = get_logger(__name__)

# Additive MQTT: a new "latest conditions" state topic. Retained, so a late-
# joining consumer immediately gets the current weather (like a location topic).
WEATHER_TOPIC = "orpheus/environment/weather"

_DEFAULT_POLL_INTERVAL_SECONDS = 300.0
_DEFAULT_TIMEOUT_SECONDS = 10.0



class WeatherProvider(ABC):
    """Source of ``WeatherReading``s. ``fetch`` pulls a fresh reading (returning
    ``None`` on a transient failure so the caller degrades gracefully rather than
    crashing); ``get_latest`` returns the most recent reading this provider has
    seen (or ``None``)."""

    @abstractmethod
    def fetch(self) -> Optional[WeatherReading]:
        ...

    @abstractmethod
    def get_latest(self) -> Optional[WeatherReading]:
        ...


class EcowittProvider(WeatherProvider):
    """Polls an Ecowitt gateway's local HTTP API.

    ``url`` is the COMPLETE endpoint to GET (operator-provided — the path varies
    by firmware, so nothing is guessed here). Transport is injectable as
    ``fetch_raw`` for testing without a real station.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        fetch_raw: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._url = url
        self._timeout = timeout_seconds
        self._fetch_raw = fetch_raw or self._default_fetch_raw
        self._latest: Optional[WeatherReading] = None

    def fetch(self) -> Optional[WeatherReading]:
        try:
            raw = self._fetch_raw()
        except Exception as e:  # network down / timeout / bad HTTP — degrade
            logger.warning(
                "Ecowitt station unreachable; continuing with no weather",
                url=self._url,
                error=str(e),
            )
            return None
        # _parse may raise NotImplementedError (the ungrounded seam) — that is a
        # loud, actionable signal, NOT a transient failure, so it propagates.
        reading = self._parse(raw)
        self._latest = reading
        return reading

    def get_latest(self) -> Optional[WeatherReading]:
        return self._latest

    def _default_fetch_raw(self) -> Any:
        import requests  # lazy: keep orpheus_common import cheap

        response = requests.get(self._url, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def _parse(self, raw: Any) -> WeatherReading:
        """Map a raw Ecowitt local-API response to a (SI-unit) WeatherReading.

        UNGROUNDED SEAM (AGENTS.md rule #7): the Ecowitt JSON keys AND their units
        are vendor/firmware-specific and are not captured in this repo. Filling
        this in by guessing is exactly the failure mode rule #7 exists for.
        """
        raise NotImplementedError(
            "EcowittProvider._parse is an ungrounded seam. The Ecowitt local-API "
            "field names and units are vendor/firmware-specific and not yet "
            "captured. Capture one real response (e.g. `curl " + self._url + "`), "
            "then map its keys to WeatherReading here, converting Ecowitt's "
            "imperial units (degF, inHg, mph, in) to the SI WeatherReading "
            "contract (degC, hPa, m/s, mm). Do not guess the mapping."
        )


class WeatherDB:
    """Persists ``WeatherReading``s into a ``weather_readings`` table in the SAME
    SQLite file as detections — so weather joins detections on time (the whole
    point: "what was the weather when this crow showed up?"). Additive table; an
    old binary never references it, so the previous release reads the DB
    untouched."""

    def __init__(self, db_path: Optional[Path] = None, *, read_only: bool = False) -> None:
        # Default to the detections DB file, NOT a separate file, for joins.
        self.db_path = Path(db_path) if db_path else (get_data_root() / "detections" / "orpheus.db")
        # read_only serves replicas/mirrors: no mkdir, no schema writes, and
        # every read opens mode=ro so a consumer can never create or mutate
        # the file it is only meant to observe.
        self.read_only = read_only
        if not read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = open_connection(self.db_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS weather_readings ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "temperature_c REAL, humidity_pct REAL, pressure_hpa REAL, "
                "wind_speed_mps REAL, wind_direction_deg INTEGER, rainfall_mm REAL, "
                "timestamp TEXT, recorded_at TEXT NOT NULL)"
            )
            conn.commit()
        finally:
            conn.close()

    def save(self, reading: WeatherReading) -> None:
        conn = open_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO weather_readings "
                "(temperature_c, humidity_pct, pressure_hpa, wind_speed_mps, "
                "wind_direction_deg, rainfall_mm, timestamp, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    reading.temperature_c,
                    reading.humidity_pct,
                    reading.pressure_hpa,
                    reading.wind_speed_mps,
                    reading.wind_direction_deg,
                    reading.rainfall_mm,
                    reading.timestamp,
                    utc_now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_latest(self) -> Optional[WeatherReading]:
        latest = self.latest_row()
        return latest[0] if latest is not None else None

    def latest_row(self) -> Optional[tuple[WeatherReading, str]]:
        """Newest reading plus its ``recorded_at`` stamp (freshness gating)."""
        conn = open_connection(self.db_path, read_only=self.read_only)
        try:
            cur = conn.execute(
                "SELECT temperature_c, humidity_pct, pressure_hpa, wind_speed_mps, "
                "wind_direction_deg, rainfall_mm, timestamp, recorded_at "
                "FROM weather_readings ORDER BY recorded_at DESC, id DESC LIMIT 1"
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        reading = WeatherReading(
            temperature_c=row[0],
            humidity_pct=row[1],
            pressure_hpa=row[2],
            wind_speed_mps=row[3],
            wind_direction_deg=row[4],
            rainfall_mm=row[5],
            timestamp=row[6] or "",
        )
        return reading, row[7] or ""


class WeatherIngestor:
    """Polls a ``WeatherProvider`` and fans each reading out to storage + bus.

    ``sleep`` is injectable so tests run instantly. The loop is synchronous (the
    process is standalone, so an asyncio loop buys nothing) and resilient — one
    bad cycle is logged and the loop continues."""

    def __init__(
        self,
        provider: WeatherProvider,
        db: WeatherDB,
        bus: EventBus,
        *,
        topic: str = WEATHER_TOPIC,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._provider = provider
        self._db = db
        self._bus = bus
        self._topic = topic
        self._sleep = sleep

    def poll_once(self) -> Optional[WeatherReading]:
        """One fetch → persist + publish. Returns the reading, or ``None`` when
        the provider had nothing (e.g. station unreachable)."""
        reading = self._provider.fetch()
        if reading is None:
            return None
        self._db.save(reading)
        # Retained: a consumer that connects later still sees current conditions.
        self._bus.publish(self._topic, reading.model_dump(mode="json"), retain=True)
        return reading

    def run(
        self,
        *,
        interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        stop: Optional[Callable[[], bool]] = None,
        max_cycles: Optional[int] = None,
    ) -> int:
        """Poll every ``interval_seconds`` until ``stop()`` is true (or
        ``max_cycles`` reached, for tests). Returns the number of cycles run."""
        should_stop = stop or (lambda: False)
        cycles = 0
        while not should_stop():
            try:
                self.poll_once()
            except NotImplementedError:
                # The ungrounded Ecowitt seam (rule #7) — a permanent, actionable
                # failure designed to be loud. Absorbing it as a transient cycle
                # error would leave the service "running" while ingesting nothing.
                raise
            except Exception:
                logger.exception("Weather poll cycle failed; continuing")
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            if should_stop():
                break
            _interruptible_sleep(interval_seconds, self._sleep, should_stop)
        return cycles


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orpheus-weather",
        description="Poll a weather station and ingest readings onto the event bus + DB.",
    )
    parser.add_argument("--url", help="Full weather-station endpoint URL (overrides config).")
    parser.add_argument(
        "--interval", type=float, help="Seconds between polls (overrides config)."
    )
    parser.add_argument("--once", action="store_true", help="Poll once and exit.")
    args = parser.parse_args(argv)

    from .config import OrpheusConfig  # lazy: avoid loading config at import

    config = OrpheusConfig.get_instance()
    wcfg = config.weather
    url = args.url or wcfg.url
    interval = args.interval if args.interval is not None else wcfg.poll_interval_seconds
    if not url:
        logger.error("No weather station URL configured (set weather.url or pass --url).")
        return 2
    if not wcfg.enabled:
        logger.warning(
            "weather.enabled is false — running on-demand (the flag only gates the "
            "long-running service, not a manual run)."
        )

    provider = EcowittProvider(url)
    db = WeatherDB()
    bus = create_event_bus(config, client_id="orpheus-weather")

    stop_flag = {"stop": False}

    def _request_stop(*_: Any) -> None:
        stop_flag["stop"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _request_stop)

    exit_code = 0
    bus.connect()
    try:
        ingestor = WeatherIngestor(provider, db, bus)
        if args.once:
            # Nonzero when a one-shot poll produced nothing (unreachable / no
            # data), so a cron/health check can distinguish it from a real ingest.
            if ingestor.poll_once() is None:
                exit_code = 1
        else:
            ingestor.run(interval_seconds=interval, stop=lambda: stop_flag["stop"])
    finally:
        bus.disconnect()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
