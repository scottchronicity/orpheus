"""Sanity tests for the video motion agent."""


def test_import_main():
    """Test that main module can be imported."""
    from orpheus_agent_video_motion import main

    assert main is not None


def test_import_config():
    """Test that config module can be imported."""
    from orpheus_agent_video_motion import config

    assert config is not None


def test_import_detector_algorithm():
    """Test that detector_algorithm module can be imported."""
    from orpheus_agent_video_motion import detector_algorithm

    assert detector_algorithm is not None


def test_import_camera_processor():
    """Test that camera_processor module can be imported."""
    from orpheus_agent_video_motion import camera_processor

    assert camera_processor is not None


def test_import_clip_saver():
    """Test that clip_saver module can be imported."""
    from orpheus_agent_video_motion import clip_saver

    assert clip_saver is not None
