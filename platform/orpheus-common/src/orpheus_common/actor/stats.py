"""ActorStats — the common agent counters surfaced in health payloads.

Every agent tracks the same trio (events processed, error count, last error) and
formats the last error identically (``"<Type>: <msg[:200]>"``) for the UI error
feed. This consolidates that; agent-specific counters (detections_found,
entities_emitted, …) stay on the agent, which composes them into its health
payload alongside ``ActorStats.as_dict()``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class ActorStats:
    """Mutable counters for an agent's lifecycle health."""

    def __init__(self) -> None:
        self.events_processed = 0
        self.errors_count = 0
        self.last_error: Optional[str] = None

    def record_processed(self, n: int = 1) -> None:
        self.events_processed += n

    def record_error(self, exc: BaseException) -> None:
        """Count an error and capture a bounded ``"<Type>: <msg>"`` string —
        the exact format the agents publish for the UI's cross-agent error feed."""
        self.errors_count += 1
        self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"

    def as_dict(self) -> Dict[str, Any]:
        """The common counters, for splicing into a health payload."""
        return {
            "events_processed": self.events_processed,
            "errors_count": self.errors_count,
            "last_error": self.last_error,
        }
