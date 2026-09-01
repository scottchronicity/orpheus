"""Real-audio full-cascade validation — the flagship "test ALL of it together".

Inject ONE audio.motion event referencing the real crow clip into the running
docker fleet (bird + crow + audio-events + correlator, real models). The whole
collective self-activates over the backplane:

    audio.motion → bird species.detected + audio-events audio.classified
                 → crow crow.analyzed → correlator EntityEvent

and we assert a corvid EntityEvent lands on the entities topic, fusing evidence
from more than one classifier. Real models on the real clip across the real
collective — the truth oracle the fast stubbed contract oracles approximate.
Gated + skipped unless the fleet is up (see conftest); CPU inference is slow,
hence the generous timeout.
"""

from __future__ import annotations

import pytest
from fleet_helpers import (
    CROW_CLIP,
    ENTITY_TOPIC,
    MOTION_TOPIC,
    audio_motion,
    entity_roots as _roots,
    is_corvid_entity,
)
from orpheus_common.testing import Observer, publish

pytestmark = pytest.mark.real_audio


def test_real_crow_clip_drives_cascade_to_entity(nats_url):
    """One real crow clip → real models → a corvid EntityEvent that FUSES
    evidence from more than one classifier (BirdNET species.detected +
    audio-events audio.classified), proving the cross-modal cascade, not just a
    single agent firing."""
    stimulus = audio_motion(CROW_CLIP)
    root_id = stimulus["event_id"]
    with Observer(nats_url, ENTITY_TOPIC, client_id="e2e-cascade") as obs:
        publish(nats_url, MOTION_TOPIC, stimulus)
        # Real CPU inference across bird (+AVES in crow, ~1-5s) is slow. Wait for
        # OUR entity: other traffic on this topic must not end the wait early.
        assert obs.wait_for_match(
            lambda e: is_corvid_entity(e) and root_id in _roots(e), timeout=120.0
        ), f"no corvid entity tracing back to {root_id} in: {obs.payloads_on(ENTITY_TOPIC)!r}"

    entities = obs.payloads_on(ENTITY_TOPIC)
    corvid = next(
        (e for e in entities if is_corvid_entity(e) and root_id in _roots(e)), None
    )
    # Traced to the clip WE injected: an entity built from anything else in the
    # collective (a synthetic source, a previous run) carries a different root.
    assert corvid is not None, f"no corvid entity for root {root_id}: {entities!r}"
    # Cross-modal fusion: the corvid identity is backed by evidence from more than
    # one source on the shared root (BirdNET + audio-events), not a lone detection.
    assert len(corvid.get("evidence", [])) >= 2, (
        f"expected fused multi-source evidence, got {corvid.get('evidence')!r}"
    )
