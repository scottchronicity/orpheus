"""Tests for orpheus_common.storage module - using ACTUAL API"""

from datetime import date
from pathlib import Path

from orpheus_common.storage import get_audio_path, get_video_path


def test_audio_path_raw_with_channel():
    """Test raw audio path with specific channel"""
    path = get_audio_path(category="raw", recording_date=date(2025, 11, 26), channel=1)

    assert isinstance(path, Path)
    path_str = str(path)
    assert "audio/raw/2025-11-26/channel_1" in path_str


def test_audio_path_defaults_to_today():
    """Test that raw audio defaults to today's date when not specified"""
    path = get_audio_path(category="raw", channel=1)

    path_str = str(path)
    assert "audio/raw/" in path_str
    assert "channel_1" in path_str
    # Should contain today's date
    assert date.today().isoformat() in path_str


def test_audio_path_without_channel():
    """Test audio path without channel specification"""
    path = get_audio_path(category="raw", recording_date=date(2025, 11, 26))

    path_str = str(path)
    assert "audio/raw/2025-11-26" in path_str
    assert "channel_" not in path_str


def test_video_path_raw_with_camera():
    """Test raw video path with camera"""
    path = get_video_path(category="raw", recording_date=date(2025, 11, 26), camera="north")

    assert isinstance(path, Path)
    path_str = str(path)
    assert "video/raw/2025-11-26/north" in path_str


def test_video_path_different_cameras():
    """Test that different cameras create different paths"""
    north = get_video_path(category="raw", recording_date=date(2025, 11, 26), camera="north")
    south = get_video_path(category="raw", recording_date=date(2025, 11, 26), camera="south")

    assert str(north) != str(south)
    assert "north" in str(north)
    assert "south" in str(south)


def test_audio_processed_category():
    """Test processed audio category"""
    path = get_audio_path(category="processed", recording_date=date(2025, 11, 26), channel=2)

    path_str = str(path)
    assert "audio/processed/2025-11-26/channel_2" in path_str


def test_different_dates():
    """Test that different dates create different paths"""
    nov_26 = get_audio_path(category="raw", recording_date=date(2025, 11, 26), channel=1)
    nov_27 = get_audio_path(category="raw", recording_date=date(2025, 11, 27), channel=1)

    assert "2025-11-26" in str(nov_26)
    assert "2025-11-27" in str(nov_27)
    assert str(nov_26) != str(nov_27)
