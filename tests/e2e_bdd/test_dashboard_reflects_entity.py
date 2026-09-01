"""Dashboard layer of the e2e — the UI backend reflects the cascade's entity.

After the real-audio cascade produces a corvid EntityEvent (which the correlator
persists to the shared DetectionDB), the UI backend that the dashboards render
from must serve it. We drive the cascade, then query the UI's `GET /api/entities`
as a signed-in viewer and assert the corvid entity is there. Asserting the
backend API/DB (not a browser) is the practical "the dashboard reflects it"
check; the Playwright suite remains the UX gate.

The session comes from `POST /auth/guest-login`, the same read-only sign-in the
dashboard itself offers — account creation is a superuser operation, so a test
that registers its own user is testing a door that production keeps shut.

Gated like the cascade test (needs the fleet up, incl. the orpheus-ui service).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
from fleet_helpers import (
    CROW_CLIP,
    ENTITY_TOPIC,
    MOTION_TOPIC,
    audio_motion,
    entity_roots,
    is_corvid_entity,
)
from orpheus_common.testing import Observer, publish

pytestmark = pytest.mark.real_audio

UI = "http://127.0.0.1:8082"


def _guest_token() -> str:
    """Sign in through the dashboard's own read-only guest entry point."""
    req = urllib.request.Request(f"{UI}/auth/guest-login", data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)["access_token"]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise AssertionError(
            f"guest sign-in failed ({e.code}): {body}. The fleet's UI seeds a "
            "viewer account on first start and ui.guest_quick_login defaults on; "
            "a 403 here means one of those is not true in the sim config."
        ) from e


def _get(path: str, token: str):
    req = urllib.request.Request(f"{UI}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def test_dashboard_api_reflects_the_cascade_entity(nats_url):
    """Drive the cascade, then assert the corvid entity is served by the UI's
    /api/entities — i.e. the dashboards would show it."""
    # 1. Drive the cascade so the correlator persists a corvid entity to the DB
    #    the UI reads from, and hold on to the id of the entity OUR clip caused —
    #    a station with history always has corvids in the API, so matching on the
    #    species alone would pass with the classifiers switched off.
    stimulus = audio_motion(CROW_CLIP)
    root_id = stimulus["event_id"]
    with Observer(nats_url, ENTITY_TOPIC, client_id="e2e-dash") as obs:
        publish(nats_url, MOTION_TOPIC, stimulus)
        assert obs.wait_for_match(
            lambda e: is_corvid_entity(e) and root_id in entity_roots(e), timeout=120.0
        ), f"cascade produced no corvid entity for root {root_id}"
        ours = next(
            e
            for e in obs.payloads_on(ENTITY_TOPIC)
            if is_corvid_entity(e) and root_id in entity_roots(e)
        )

    # 2. Sign in the way a dashboard visitor does: a read-only viewer session.
    token = _guest_token()

    # 3. The dashboards' API serves THAT entity off the DB the correlator wrote.
    data = _get("/api/entities", token)
    served = {e.get("entity_id") for e in (data.get("entities") or [])}
    assert ours["entity_id"] in served, (
        f"dashboard /api/entities does not serve the entity the cascade just "
        f"produced ({ours['entity_id']}); got {sorted(served)!r}"
    )
