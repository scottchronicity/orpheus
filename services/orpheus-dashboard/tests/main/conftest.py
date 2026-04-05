"""Pytest configuration and shared fixtures for main tests."""

import sys
import pytest
from pathlib import Path

# Add src directory to path so we can import main
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module state between tests to avoid side effects."""
    # Clear main module from cache if it exists
    if "main" in sys.modules:
        del sys.modules["main"]

    yield

    # Clean up after test
    if "main" in sys.modules:
        del sys.modules["main"]


@pytest.fixture
def sample_camera_data():
    """Sample camera status data for testing."""
    return {
        "name": "test-camera",
        "host": "192.168.1.100",
        "model": "IP5M-B1186EW-AI",
        "type": "amcrest",
        "status": "healthy",
        "checks": {
            "network": {"ok": True, "latency_ms": 5.2},
            "http_api": {"ok": True, "response_time_ms": 120},
            "snapshot": {"ok": True, "cached_at": "2025-11-28T12:00:00Z"},
            "rtsp_stream": {"ok": True},
        },
        "system_info": {
            "firmware": "V2.622.00AC000.0.R",
            "serial": "ABC123",
        },
        "last_check": "2025-11-28T12:00:00Z",
    }


@pytest.fixture
def sample_service_list():
    """Sample service list for testing."""
    return [
        "orpheus-dashboard",
        "orpheus-mqtt",
        "orpheus-agent-audio-motion",
        "orpheus-agent-video-motion",
        "orpheus-bluetooth-autoconnect",
    ]


@pytest.fixture
def sample_health_data():
    """Sample system health data for testing."""
    return {
        "status": "ok",
        "cpu_percent": 45.2,
        "memory_percent": 62.8,
        "disk_percent": 35.1,
        "uptime_seconds": 3600,
    }


@pytest.fixture
def sample_storage_data():
    """Sample storage usage data for testing."""
    return {
        "path": "/mnt/data",
        "total_gb": 1000.0,
        "used_gb": 250.0,
        "free_gb": 750.0,
        "percent_used": 25.0,
    }


@pytest.fixture
def sample_storage_hardware():
    """Sample storage hardware data for testing."""
    return {
        "devices": [
            {
                "name": "/dev/sda1",
                "mount": "/mnt/data",
                "filesystem": "ext4",
                "status": "healthy",
                "smart_status": "passed",
            }
        ]
    }
