"""Sanity tests for video timelapser agent."""

import sys


def test_import_agent():
    """Test that agent module can be imported."""
    import orpheus_agent_video_timelapser

    assert orpheus_agent_video_timelapser is not None


def test_import_config():
    """Test that config module can be imported."""
    from orpheus_agent_video_timelapser import config

    assert config is not None


def test_import_main():
    """Test that main module can be imported."""
    from orpheus_agent_video_timelapser import main

    assert main is not None


def test_python_version():
    """Verify Python version is compatible."""
    assert sys.version_info.major == 3, "Python 3.x required"
    assert sys.version_info.minor == 9, "Python 3.9.x required for Jetson compatibility"
