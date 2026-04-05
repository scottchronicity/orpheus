"""
Tests for CameraRegistry backward compatibility with legacy environment variables.

These tests validate that the dashboard's legacy environment variable pattern
continues to work correctly with the CameraRegistry.from_env() method.

Legacy Environment Variable Pattern:
- CAMERA_USER: Username for all cameras
- CAMERA_PASS: Password for all cameras
- CAMERA_N_TYPE: Camera type (e.g., "amcrest")
- CAMERA_N_NAME: Camera name (e.g., "north")
- CAMERA_N_HOST: Camera hostname or IP
- CAMERA_N_MODEL: Camera model number (optional)

Where N is 1-10.
"""

import os
from unittest.mock import patch

from orpheus_common.hardware.registry import CameraRegistry


class TestCameraRegistryLegacyEnv:
    """Test suite for legacy environment variable support."""

    def test_from_env_loads_single_camera(self):
        """Test loading a single camera from legacy environment variables."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
            "CAMERA_1_MODEL": "IP5M-B1186EW-AI-V3",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()

            assert len(registry) == 1
            camera = registry.get("north")
            assert camera is not None
            assert camera.name == "north"
            assert camera.host == "192.168.1.100"
            assert camera.model == "IP5M-B1186EW-AI-V3"
            assert camera.username == "admin"
            assert camera.password == "password123"

    def test_from_env_loads_multiple_cameras(self):
        """Test loading multiple cameras from legacy environment variables."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
            "CAMERA_2_TYPE": "amcrest",
            "CAMERA_2_NAME": "south",
            "CAMERA_2_HOST": "192.168.1.101",
            "CAMERA_3_TYPE": "amcrest",
            "CAMERA_3_NAME": "east",
            "CAMERA_3_HOST": "192.168.1.102",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()

            assert len(registry) == 3
            assert registry.get("north") is not None
            assert registry.get("south") is not None
            assert registry.get("east") is not None

    def test_from_env_returns_empty_registry_without_credentials(self):
        """Test that missing credentials returns empty registry."""
        env_vars = {
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            assert len(registry) == 0

    def test_from_env_skips_camera_missing_name(self):
        """Test that cameras missing NAME are skipped."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_HOST": "192.168.1.100",
            # Missing CAMERA_1_NAME
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            assert len(registry) == 0

    def test_from_env_skips_camera_missing_host(self):
        """Test that cameras missing HOST are skipped."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            # Missing CAMERA_1_HOST
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            assert len(registry) == 0

    def test_from_env_skips_unknown_camera_type(self):
        """Test that unknown camera types are skipped."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "unknown_brand",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            assert len(registry) == 0

    def test_from_env_uses_default_model_when_not_specified(self):
        """Test that default model 'Unknown' is used when MODEL not specified."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
            # No CAMERA_1_MODEL
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            camera = registry.get("north")
            assert camera.model == "Unknown"

    def test_from_env_handles_non_contiguous_camera_numbers(self):
        """Test that non-contiguous camera numbers are handled (gaps are OK)."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
            # Gap: no CAMERA_2_*
            "CAMERA_3_TYPE": "amcrest",
            "CAMERA_3_NAME": "south",
            "CAMERA_3_HOST": "192.168.1.101",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            assert len(registry) == 2
            assert registry.get("north") is not None
            assert registry.get("south") is not None

    def test_from_env_case_insensitive_camera_type(self):
        """Test that camera type matching is case-insensitive."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "AMCREST",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
            "CAMERA_2_TYPE": "Amcrest",
            "CAMERA_2_NAME": "south",
            "CAMERA_2_HOST": "192.168.1.101",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            assert len(registry) == 2

    def test_from_env_supports_up_to_ten_cameras(self):
        """Test that up to 10 cameras can be loaded from environment."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
        }

        # Add cameras 1-10
        for i in range(1, 11):
            env_vars[f"CAMERA_{i}_TYPE"] = "amcrest"
            env_vars[f"CAMERA_{i}_NAME"] = f"camera{i}"
            env_vars[f"CAMERA_{i}_HOST"] = f"192.168.1.{100 + i}"

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            assert len(registry) == 10

    def test_load_from_env_legacy_method_returns_list(self):
        """Test that legacy load_from_env() method returns a list of cameras."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            cameras = CameraRegistry.load_from_env()
            assert isinstance(cameras, list)
            assert len(cameras) == 1
            assert cameras[0].name == "north"

    def test_registry_iteration(self):
        """Test that registry can be iterated over."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
            "CAMERA_2_TYPE": "amcrest",
            "CAMERA_2_NAME": "south",
            "CAMERA_2_HOST": "192.168.1.101",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            names = [cam.name for cam in registry]
            assert "north" in names
            assert "south" in names

    def test_registry_list_cameras(self):
        """Test list_cameras() method returns camera list."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            cameras = registry.list_cameras()
            assert len(cameras) == 1
            assert cameras[0].name == "north"

    def test_registry_get_camera_names(self):
        """Test get_camera_names() method returns list of names."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
            "CAMERA_2_TYPE": "amcrest",
            "CAMERA_2_NAME": "south",
            "CAMERA_2_HOST": "192.168.1.101",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            names = registry.get_camera_names()
            assert set(names) == {"north", "south"}

    def test_registry_get_nonexistent_camera_returns_none(self):
        """Test that getting a nonexistent camera returns None."""
        env_vars = {
            "CAMERA_USER": "admin",
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            assert registry.get("nonexistent") is None

    def test_from_env_with_only_password_missing(self):
        """Test that missing password returns empty registry."""
        env_vars = {
            "CAMERA_USER": "admin",
            # Missing CAMERA_PASS
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            assert len(registry) == 0

    def test_from_env_with_only_username_missing(self):
        """Test that missing username returns empty registry."""
        env_vars = {
            # Missing CAMERA_USER
            "CAMERA_PASS": "password123",
            "CAMERA_1_TYPE": "amcrest",
            "CAMERA_1_NAME": "north",
            "CAMERA_1_HOST": "192.168.1.100",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            registry = CameraRegistry.from_env()
            assert len(registry) == 0

    def test_from_env_empty_environment(self):
        """Test that empty environment returns empty registry."""
        with patch.dict(os.environ, {}, clear=True):
            registry = CameraRegistry.from_env()
            assert len(registry) == 0
