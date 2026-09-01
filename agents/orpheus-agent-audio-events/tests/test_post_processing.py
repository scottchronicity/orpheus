"""Tests for ``post_processing.post_process``."""

from __future__ import annotations

import numpy as np
import pytest

from orpheus_agent_audio_events.post_processing import post_process


def _make_framewise(num_frames: int, num_classes: int) -> np.ndarray:
    """Convenience: zeroed framewise output of shape (T, num_classes)."""
    return np.zeros((num_frames, num_classes), dtype=np.float32)


class TestPostProcessBasics:
    """Boundary and validation tests."""

    def test_rejects_non_2d_input(self) -> None:
        with pytest.raises(ValueError, match="must be 2-D"):
            post_process(
                np.zeros(10, dtype=np.float32),
                frame_duration_seconds=0.032,
            )

    def test_rejects_nonpositive_frame_duration(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            post_process(
                _make_framewise(10, 5),
                frame_duration_seconds=0.0,
            )

    def test_empty_frames_returns_empty(self) -> None:
        result = post_process(
            _make_framewise(0, 5),
            frame_duration_seconds=0.032,
        )
        assert result == []

    def test_all_zero_input_returns_empty(self) -> None:
        result = post_process(
            _make_framewise(100, 10),
            frame_duration_seconds=0.032,
        )
        assert result == []


class TestPostProcessSingleClass:
    """Single-class behaviour: thresholds, runs, bridging, min duration."""

    def test_simple_contiguous_event_one_interval(self) -> None:
        # 100 frames at 32 ms/frame = 3.2 s clip. Class 2 fires from frame 30-60 (0.96-1.92 s).
        framewise = _make_framewise(100, 5)
        framewise[30:60, 2] = 0.9
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
            bridge_ms=100,
            min_interval_ms=100,
        )
        assert len(result) == 1
        clip = result[0]
        assert clip.class_index == 2
        assert clip.clip_score == pytest.approx(0.9)
        assert len(clip.intervals) == 1
        iv = clip.intervals[0]
        assert iv.start_seconds == pytest.approx(30 * 0.032)
        assert iv.end_seconds == pytest.approx(60 * 0.032)
        assert iv.interval_score == pytest.approx(0.9)

    def test_two_separate_events_become_two_intervals(self) -> None:
        # Class fires at frames 10-20 and 70-80 — gap of 50 frames (1.6 s) far
        # exceeds the bridging budget of 100 ms (~3 frames).
        framewise = _make_framewise(100, 5)
        framewise[10:20, 0] = 0.8
        framewise[70:80, 0] = 0.7
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
            bridge_ms=100,
            min_interval_ms=100,
        )
        assert len(result) == 1
        assert len(result[0].intervals) == 2

    def test_two_close_events_get_bridged(self) -> None:
        # Gap of 2 frames (~64 ms) is within the 100 ms bridge budget.
        framewise = _make_framewise(100, 5)
        framewise[10:20, 0] = 0.8
        framewise[22:30, 0] = 0.7
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
            bridge_ms=100,
            min_interval_ms=100,
        )
        assert len(result) == 1
        assert len(result[0].intervals) == 1
        iv = result[0].intervals[0]
        # Bridged run spans frames 10..30.
        assert iv.start_seconds == pytest.approx(10 * 0.032)
        assert iv.end_seconds == pytest.approx(30 * 0.032)

    def test_too_short_run_filtered_unless_fallback(self) -> None:
        """A single brief frame run is shorter than min_interval, so it gets
        the fallback interval treatment (centred on the peak)."""
        framewise = _make_framewise(100, 5)
        # Single high frame at frame 50 — too brief for the min_interval_ms.
        framewise[50, 0] = 0.9
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
            bridge_ms=100,
            min_interval_ms=200,
        )
        # Clip-level cleared the bar at 0.9 so we still emit, with a fallback
        # interval centred on the peak.
        assert len(result) == 1
        assert len(result[0].intervals) == 1

    def test_clip_threshold_filters_classes(self) -> None:
        framewise = _make_framewise(100, 5)
        framewise[30:60, 0] = 0.9   # passes
        framewise[30:60, 1] = 0.25  # below clip_threshold
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
        )
        assert len(result) == 1
        assert result[0].class_index == 0


class TestPostProcessMultiClass:
    """Multi-class behaviour: ranking, top-K, allow-listing."""

    def test_returns_sorted_by_descending_clip_score(self) -> None:
        framewise = _make_framewise(100, 5)
        framewise[10:90, 0] = 0.6
        framewise[10:90, 1] = 0.9
        framewise[10:90, 2] = 0.75
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
        )
        assert [r.class_index for r in result] == [1, 2, 0]
        scores = [r.clip_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_max_labels_per_clip_caps_results(self) -> None:
        framewise = _make_framewise(100, 5)
        for c in range(5):
            framewise[10:90, c] = 0.5 + 0.05 * c
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
            max_labels_per_clip=2,
        )
        assert len(result) == 2

    def test_allowed_class_indices_filters_out_others(self) -> None:
        framewise = _make_framewise(100, 5)
        framewise[10:90, 0] = 0.9   # class 0 is NOT in the allowed set
        framewise[10:90, 3] = 0.85  # class 3 IS allowed
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
            allowed_class_indices=[2, 3, 4],
        )
        assert len(result) == 1
        assert result[0].class_index == 3

    def test_empty_allow_list_drops_everything(self) -> None:
        framewise = _make_framewise(100, 5)
        framewise[:, 0] = 0.9
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
            allowed_class_indices=[],
        )
        assert result == []


class TestPostProcessEdgeCases:
    """Edge cases that might trip up the algorithm."""

    def test_run_at_start_of_clip(self) -> None:
        framewise = _make_framewise(100, 5)
        framewise[0:30, 0] = 0.9
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
            min_interval_ms=100,
        )
        assert len(result) == 1
        assert result[0].intervals[0].start_seconds == pytest.approx(0.0)

    def test_run_at_end_of_clip(self) -> None:
        framewise = _make_framewise(100, 5)
        framewise[70:100, 0] = 0.9
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
            min_interval_ms=100,
        )
        assert len(result) == 1
        assert result[0].intervals[0].end_seconds == pytest.approx(100 * 0.032)

    def test_score_exactly_at_threshold(self) -> None:
        """Boundary at exactly the threshold should be inclusive."""
        framewise = _make_framewise(100, 5)
        framewise[10:90, 0] = 0.3  # equals clip_threshold
        result = post_process(
            framewise,
            frame_duration_seconds=0.032,
            clip_threshold=0.3,
            frame_threshold=0.2,
        )
        assert len(result) == 1
