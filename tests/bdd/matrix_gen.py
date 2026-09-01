"""Generate the agent-failure matrix from one declarative contract oracle.

The matrix is GENERATED, not hand-curated (the owner's criterion): enumerate the
full powerset of cascade classifiers down, and compute the expected DB outcome
compositionally from the contract — expected entity evidence = the UNION of the
surviving classifiers' output types. Adding a classifier to ``CONTRACT`` extends
coverage automatically; no hand-written rows. See docs/designs/sim-test-matrix.md.

This module is the single source of truth for the cascade contract + the synthetic
detection shape, shared by the generated pytest matrix (`test_matrix_generated.py`).
The hand-written `@ci` behave rows (`agent_failure.feature`) cover the same frontier
for the fast/readable surface.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations

# type -> its bus contract. The corvid taxonomy each classifier really emits
# (bird=ioc, audio-events=audioset cross-taxonomy, crow.analyzed=none) so fusion is
# genuinely exercised. One source of truth.
CONTRACT: dict[str, dict] = {
    "bird-detection": {
        "topic": "orpheus/detection/bird/events",
        "detection_type": "species.detected",
        "taxonomy": {"namespace": "ioc", "id": "Corvus brachyrhynchos"},
    },
    "crow-detection": {
        "topic": "orpheus/detection/crow/events",
        "detection_type": "crow.analyzed",
        "taxonomy": None,
    },
    "audio-events": {
        "topic": "orpheus/detection/audio/events",
        "detection_type": "audio.classified",
        "taxonomy": {"namespace": "audioset", "id": "/m/04s8yn", "common_name": "Crow"},
    },
}

CASCADE_CLASSIFIERS = tuple(CONTRACT)
_ROOT = "root-matrix"


@dataclass(frozen=True)
class MatrixRow:
    """One generated configuration of the failure axis."""

    down: tuple[str, ...]  # classifiers removed
    surviving: tuple[str, ...]  # classifiers present
    expected_evidence: frozenset  # ∪ of surviving output detection_types
    expected_entities: int  # 1 if any survivor fuses, else 0
    tag: str  # "ci" (behaviorally-distinct frontier) | "matrix-derived" (oracle-tautology)


def generate_rows(classifiers: tuple[str, ...] = CASCADE_CLASSIFIERS) -> list[MatrixRow]:
    """The full powerset of agents-down, with the compositionally-derived expected
    outcome. Frontier (`@ci`) = none-down + each single-down + all-down; the n−2…
    interior rows are oracle-tautologies (derivable from the single-down rows),
    emitted for completeness but tagged ``matrix-derived``."""
    n = len(classifiers)
    rows: list[MatrixRow] = []
    for k in range(n + 1):
        for down in combinations(classifiers, k):
            surviving = tuple(c for c in classifiers if c not in down)
            evidence = frozenset(CONTRACT[c]["detection_type"] for c in surviving)
            tag = "ci" if k in (0, 1, n) else "matrix-derived"
            rows.append(MatrixRow(down, surviving, evidence, 1 if surviving else 0, tag))
    return rows


def synth_detection(clf: str) -> dict:
    """A contract-shaped corvid detection for ``clf`` on the shared root, so the
    surviving classifiers fuse into one entity."""
    spec = CONTRACT[clf]
    return {
        "event_id": f"det-{clf}-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "detection_type": spec["detection_type"],
        "species_code": "corvus",
        "species_common": "American Crow",
        "taxonomy": spec["taxonomy"],
        "context": {"sensor_id": "mic-1", "lat": 47.6, "lon": -122.3},
        "root_event_id": _ROOT,
        "source_event_id": _ROOT,
        "confidence": 0.9,
    }
