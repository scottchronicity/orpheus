"""Fixtures for the real-audio cascade validation (the docker fleet substrate).

These tests drive the running docker-compose `fleet` profile: they inject a single
audio.motion event (with a real clip path resolvable inside the agent containers)
onto the backplane and assert the full cascade lands an EntityEvent. They are
host-side — they only need a broker + orpheus_common — and are gated behind
`ORPHEUS_E2E_REAL_AUDIO` so they never run accidentally (e.g. against the demo
profile, which has no detection agents). Drive via `make sim-fleet-up &&
make sim-validate`.
"""

from __future__ import annotations

import os

import pytest
from orpheus_common.testing import DEFAULT_NATS_URL, broker_reachable

NATS_URL = DEFAULT_NATS_URL


@pytest.fixture(scope="session")
def nats_url() -> str:
    if not os.environ.get("ORPHEUS_E2E_REAL_AUDIO"):
        pytest.skip(
            "real-audio e2e is gated: run `make sim-fleet-up && make sim-validate` "
            "(sets ORPHEUS_E2E_REAL_AUDIO with the detection fleet running)"
        )
    # Past the gate the caller has asserted the fleet is up, so an unreachable
    # broker is a failure, not a skip: `make sim-validate` is the command the
    # README offers as proof the system works, and a green run against nothing
    # is worse than no check at all.
    if not broker_reachable(NATS_URL):
        pytest.fail(
            f"no broker at {NATS_URL} — start the fleet first: "
            "`SIM_MODE=replay make sim-up && make sim-fleet-up`"
        )
    return NATS_URL
