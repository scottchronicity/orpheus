"""Fail-closed verification for the Simulacrum's host-published NATS broker.

The real-audio tests publish events and are mutating by design. Before running
them, verify that their loopback endpoint is the NATS instance owned by this
repository's isolated Docker Compose project, rather than trusting the hostname.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional
from urllib.request import urlopen

SIMULACRUM_PROJECT = "orpheus-simulacrum"
SIMULACRUM_URL = "nats://127.0.0.1:4222"


def _run(command: list[str], *, cwd: Optional[Path] = None) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Could not verify the Simulacrum NATS broker; refusing to run "
            "mutating end-to-end tests"
        ) from exc
    return completed.stdout.strip()


def verify_simulacrum_broker(url: str) -> None:
    """Verify test URL, Compose ownership, loopback binds and broker identity."""
    if url != SIMULACRUM_URL:
        raise RuntimeError(
            f"Simulacrum tests require {SIMULACRUM_URL}, got {url!r}; refusing tests"
        )

    repo_root = Path(__file__).resolve().parents[5]
    compose_file = repo_root / "docker-compose.dev.yml"
    if not compose_file.is_file():
        raise RuntimeError("Could not locate docker-compose.dev.yml; refusing tests")

    container_ids = _run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "ps",
            "--status",
            "running",
            "-q",
            "orpheus-backplane",
        ],
        cwd=repo_root,
    ).splitlines()
    if len(container_ids) != 1:
        raise RuntimeError(
            "Expected exactly one running Simulacrum orpheus-backplane container; "
            "refusing mutating tests"
        )

    container_id = container_ids[0]
    container_data = json.loads(_run(["docker", "inspect", container_id]))[0]
    labels = container_data.get("Config", {}).get("Labels", {})
    if labels.get("com.docker.compose.project") != SIMULACRUM_PROJECT or labels.get(
        "com.docker.compose.service"
    ) != "orpheus-backplane":
        raise RuntimeError("NATS container is not owned by the Simulacrum project")
    if container_data.get("Config", {}).get("Image") != "nats:2.10-alpine":
        raise RuntimeError("Unexpected Simulacrum broker image; refusing mutating tests")

    ports = container_data.get("NetworkSettings", {}).get("Ports", {})
    _require_loopback_binding(ports, "4222/tcp", "4222")
    _require_loopback_binding(ports, "8222/tcp", "8222")

    container_varz = json.loads(
        _run(
            [
                "docker",
                "exec",
                container_id,
                "wget",
                "-qO-",
                "http://127.0.0.1:8222/varz",
            ]
        )
    )
    try:
        with urlopen("http://127.0.0.1:8222/varz", timeout=3) as response:
            host_varz: dict[str, Any] = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001 - any ambiguity must fail closed
        raise RuntimeError(
            "Could not inspect the host-published Simulacrum broker; refusing tests"
        ) from exc

    expected_server_id = container_varz.get("server_id")
    if not expected_server_id or host_varz.get("server_id") != expected_server_id:
        raise RuntimeError(
            "Host NATS endpoint does not match the verified Simulacrum container; "
            "refusing mutating tests"
        )


def _require_loopback_binding(ports: dict, container_port: str, expected_port: str) -> None:
    bindings = ports.get(container_port) or []
    if len(bindings) != 1 or bindings[0].get("HostIp") != "127.0.0.1" or bindings[
        0
    ].get("HostPort") != expected_port:
        raise RuntimeError(
            f"Simulacrum {container_port} must bind only to 127.0.0.1:{expected_port}"
        )


def main() -> None:
    """CLI entry point used as a Make prerequisite to the mutating test suite."""
    url = os.environ.get("ORPHEUS_TEST_NATS_URL", "")
    verify_simulacrum_broker(url)
    print("Verified isolated Simulacrum NATS broker; mutating tests may proceed.")


if __name__ == "__main__":
    main()
