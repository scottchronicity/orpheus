"""The destructive Simulacrum test gate verifies broker ownership and identity."""

import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from orpheus_common.testing import simulacrum


def _container_inspect(project="orpheus-simulacrum"):
    return json.dumps(
        [
            {
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": project,
                        "com.docker.compose.service": "orpheus-backplane",
                    },
                    "Image": "nats:2.10-alpine",
                },
                "NetworkSettings": {
                    "Ports": {
                        "4222/tcp": [{"HostIp": "127.0.0.1", "HostPort": "4222"}],
                        "8222/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8222"}],
                    }
                },
            }
        ]
    )


def test_verifies_compose_owner_loopback_binds_and_server_identity():
    varz = json.dumps({"server_id": "SIMULACRUM_SERVER"})
    with patch(
        "orpheus_common.testing.simulacrum.subprocess.run",
        side_effect=[
            SimpleNamespace(stdout="container-id"),
            SimpleNamespace(stdout=_container_inspect()),
            SimpleNamespace(stdout=varz),
        ],
    ) as run, patch(
        "orpheus_common.testing.simulacrum.urlopen",
        return_value=io.BytesIO(varz.encode()),
    ):
        simulacrum.verify_simulacrum_broker("nats://127.0.0.1:4222")

    assert run.call_count == 3


def test_rejects_loopback_without_verified_simulacrum_container():
    with patch(
        "orpheus_common.testing.simulacrum.subprocess.run",
        return_value=SimpleNamespace(stdout=""),
    ):
        with pytest.raises(RuntimeError, match="exactly one running Simulacrum"):
            simulacrum.verify_simulacrum_broker("nats://127.0.0.1:4222")


def test_rejects_host_endpoint_that_is_a_different_nats_server():
    varz = json.dumps({"server_id": "SIMULACRUM_SERVER"})
    with patch(
        "orpheus_common.testing.simulacrum.subprocess.run",
        side_effect=[
            SimpleNamespace(stdout="container-id"),
            SimpleNamespace(stdout=_container_inspect()),
            SimpleNamespace(stdout=varz),
        ],
    ), patch(
        "orpheus_common.testing.simulacrum.urlopen",
        return_value=io.BytesIO(json.dumps({"server_id": "PRODUCTION"}).encode()),
    ):
        with pytest.raises(RuntimeError, match="does not match"):
            simulacrum.verify_simulacrum_broker("nats://127.0.0.1:4222")


def test_rejects_non_loopback_simulacrum_url_without_docker_access():
    with patch("orpheus_common.testing.simulacrum.subprocess.run") as run:
        with pytest.raises(RuntimeError, match="require nats://127.0.0.1:4222"):
            simulacrum.verify_simulacrum_broker("nats://production-broker:4222")
    run.assert_not_called()
