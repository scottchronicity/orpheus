"""Cluster manager for temporal correlation of detection events."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable


class Observation:
    """A single observation extracted from a Detection event."""

    def __init__(
        self,
        species_code: str,
        common_name: str,
        confidence: float,
        event_id: str,
        source_event_id: str | None,
        sensor_id: str,
        clip_path: str | None,
        context: dict[str, Any] | None,
    ) -> None:
        self.species_code = species_code
        self.common_name = common_name
        self.confidence = confidence
        self.event_id = event_id
        self.source_event_id = source_event_id
        self.sensor_id = sensor_id
        self.clip_path = clip_path
        self.context = context
        self.timestamp = datetime.now(timezone.utc)


class TemporalCluster:
    """A cluster of observations for a single species within a time window."""

    def __init__(self, species_code: str, window_seconds: float = 3.0) -> None:
        self.species_code = species_code
        self.window_seconds = window_seconds
        self.observations: list[Observation] = []
        self.created_at = datetime.now(timezone.utc)
        self.last_updated = datetime.now(timezone.utc)
        self._timer_handle: asyncio.TimerHandle | None = None

    def add_observation(self, obs: Observation) -> None:
        """Add an observation and reset the expiration timer."""
        self.observations.append(obs)
        self.last_updated = datetime.now(timezone.utc)

    @property
    def max_confidence(self) -> float:
        """Return the maximum confidence from all observations."""
        if not self.observations:
            return 0.0
        return max(obs.confidence for obs in self.observations)

    @property
    def common_name(self) -> str:
        """Return the common name from the first observation."""
        if not self.observations:
            return ""
        return self.observations[0].common_name

    def build_entity_event(self) -> dict[str, Any]:
        """Build an EntityEvent from this cluster's observations."""
        # Average lat/lon from all observations that have context
        lats: list[float] = []
        lons: list[float] = []
        for obs in self.observations:
            if obs.context:
                lat = obs.context.get("lat")
                lon = obs.context.get("lon")
                if lat is not None:
                    lats.append(lat)
                if lon is not None:
                    lons.append(lon)

        context: dict[str, Any] = {}
        if lats:
            context["lat"] = sum(lats) / len(lats)
        if lons:
            context["lon"] = sum(lons) / len(lons)
        context["timestamp"] = datetime.now(timezone.utc).isoformat()

        evidence: list[dict[str, Any]] = []
        for obs in self.observations:
            evidence.append(
                {
                    "event_id": obs.event_id,
                    "source_event_id": obs.source_event_id,
                    "sensor_id": obs.sensor_id,
                    "clip_path": obs.clip_path,
                    "confidence": obs.confidence,
                }
            )

        return {
            "entity_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "species_code": self.species_code,
            "common_name": self.common_name,
            "confidence": self.max_confidence,
            "context": context,
            "evidence": evidence,
        }


class ClusterManager:
    """Manages temporal clusters of detection observations.

    Groups observations by species_code. When a cluster has not received
    any new observations within the window_seconds timeout, it is closed
    and an EntityEvent is emitted via the on_entity_ready callback.
    """

    def __init__(
        self,
        window_seconds: float = 3.0,
        on_entity_ready: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.window_seconds = window_seconds
        self.on_entity_ready = on_entity_ready
        self._clusters: dict[str, TemporalCluster] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop for scheduling timers."""
        self._loop = loop

    def process_observation(self, obs: Observation) -> None:
        """Add an observation to the appropriate cluster, creating one if needed."""
        species = obs.species_code

        if species in self._clusters:
            cluster = self._clusters[species]
            cluster.add_observation(obs)
        else:
            cluster = TemporalCluster(species, self.window_seconds)
            cluster.add_observation(obs)
            self._clusters[species] = cluster

        # Schedule expiration timer on the event loop thread (thread-safe)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._schedule_expiration, species)

    def _schedule_expiration(self, species_code: str) -> None:
        """Schedule or reschedule the expiration timer for a species cluster.

        Must run on the event loop thread. Called via ``call_soon_threadsafe``
        so that timer management is never executed from the MQTT thread.
        """
        cluster = self._clusters.get(species_code)
        if cluster is None:
            return

        # Cancel existing timer
        if cluster._timer_handle is not None:
            cluster._timer_handle.cancel()

        if self._loop is not None:
            cluster._timer_handle = self._loop.call_later(
                self.window_seconds,
                self._expire_cluster,
                species_code,
            )

    def _expire_cluster(self, species_code: str) -> None:
        """Close a cluster and emit the EntityEvent."""
        cluster = self._clusters.pop(species_code, None)
        if cluster is None:
            return

        entity_event = cluster.build_entity_event()

        if self.on_entity_ready is not None:
            self.on_entity_ready(entity_event)

    def flush_all(self) -> list[dict[str, Any]]:
        """Force-close all active clusters and return their EntityEvents.

        Useful for testing or graceful shutdown.
        """
        events: list[dict[str, Any]] = []
        for species_code in list(self._clusters.keys()):
            cluster = self._clusters.pop(species_code)
            if cluster._timer_handle is not None:
                cluster._timer_handle.cancel()
            events.append(cluster.build_entity_event())
        return events
