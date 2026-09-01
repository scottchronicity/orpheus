"""Post-processing: turn PANNs SED framewise outputs into typed intervals.

The SED model emits ``framewise_output[T, num_classes]`` with sigmoid scores
in [0, 1]. This module converts that matrix into a list of
``ClassifiedInterval`` objects — one per (class, contiguous time range) —
applying the threshold/bridging/min-duration logic described in
``docs/designs/audio-events-agent.md`` §3.5.

The output is consumed by ``main.py`` to construct ``Detection`` events with
``intervals`` populated per ADR 0011.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ClassifiedInterval:
    """One contiguous time range where a single class was above threshold."""

    class_index: int
    start_seconds: float
    end_seconds: float
    interval_score: float  # max frame score within the interval


@dataclass(frozen=True)
class ClassifiedClip:
    """All intervals from one classification of a single audio clip,
    grouped by class.

    Each ``(class_index, clip_score)`` pair has a list of intervals — there
    may be more than one if the class fired in non-contiguous segments of
    the clip.
    """

    class_index: int
    clip_score: float  # max frame score over the whole clip for this class
    intervals: list[ClassifiedInterval]


def _runs_above(
    mask: np.ndarray,
    bridge_frames: int,
    min_run_frames: int,
) -> list[tuple[int, int]]:
    """Find contiguous True runs in a 1-D boolean mask, with bridging.

    Args:
        mask: 1-D boolean array of length T.
        bridge_frames: bridge a run-gap of up to this many frames (gap stays
            False but the surrounding runs are merged into one logical run).
        min_run_frames: drop any final run shorter than this.

    Returns:
        List of ``(start_idx, end_idx_exclusive)`` tuples in increasing order.
    """
    if mask.size == 0:
        return []

    # Find raw runs first.
    raw_runs: list[tuple[int, int]] = []
    in_run = False
    run_start = 0
    for i, value in enumerate(mask):
        if value and not in_run:
            in_run = True
            run_start = i
        elif not value and in_run:
            in_run = False
            raw_runs.append((run_start, i))
    if in_run:
        raw_runs.append((run_start, int(mask.size)))

    if not raw_runs:
        return []

    # Bridge: merge consecutive runs if the gap between them is small.
    bridged: list[tuple[int, int]] = [raw_runs[0]]
    for start, end in raw_runs[1:]:
        prev_start, prev_end = bridged[-1]
        if start - prev_end <= bridge_frames:
            bridged[-1] = (prev_start, end)
        else:
            bridged.append((start, end))

    # Drop runs shorter than min duration.
    return [(s, e) for s, e in bridged if (e - s) >= min_run_frames]


def post_process(
    framewise_output: np.ndarray,
    frame_duration_seconds: float,
    *,
    clip_threshold: float = 0.3,
    frame_threshold: float = 0.2,
    bridge_ms: int = 100,
    min_interval_ms: int = 150,
    max_labels_per_clip: int | None = None,
    allowed_class_indices: Sequence[int] | None = None,
) -> list[ClassifiedClip]:
    """Convert a SED framewise output matrix into ``ClassifiedClip`` entries.

    Args:
        framewise_output: Array of shape ``(T, num_classes)`` with per-frame
            sigmoid scores in [0, 1].
        frame_duration_seconds: Duration of one frame (e.g., ~0.032 for PANNs
            at 32 kHz).
        clip_threshold: Drop classes whose clip-level max score is below this.
        frame_threshold: Within a surviving class, identify frames whose
            score exceeds this. Must be ``<= clip_threshold`` in practice but
            we don't enforce it (lets callers experiment).
        bridge_ms: Bridge frame-mask gaps shorter than this many milliseconds.
        min_interval_ms: Drop intervals shorter than this many milliseconds.
        max_labels_per_clip: If set, keep only the top-K classes by clip score.
        allowed_class_indices: If set, drop classes outside this whitelist
            *before* thresholding. Used by the agent to ignore PANNs class
            indices we don't have a taxonomy label for.

    Returns:
        List of ``ClassifiedClip`` sorted by descending clip_score. Empty if
        no class survives.

    Raises:
        ValueError: If ``framewise_output`` is not 2-D or
            ``frame_duration_seconds`` is non-positive.
    """
    if framewise_output.ndim != 2:
        raise ValueError(
            f"framewise_output must be 2-D (T, num_classes); got shape "
            f"{framewise_output.shape}."
        )
    if frame_duration_seconds <= 0:
        raise ValueError(
            f"frame_duration_seconds must be positive; got {frame_duration_seconds}."
        )

    num_frames, num_classes = framewise_output.shape
    if num_frames == 0:
        return []

    bridge_frames = round((bridge_ms / 1000.0) / frame_duration_seconds)
    min_run_frames = max(1, round((min_interval_ms / 1000.0) / frame_duration_seconds))

    # Optionally restrict to whitelisted class indices.
    if allowed_class_indices is not None:
        allowed = {int(i) for i in allowed_class_indices}
        class_indices = [c for c in range(num_classes) if c in allowed]
    else:
        class_indices = list(range(num_classes))

    # Compute clip-level scores (max-pool) and skip classes below threshold.
    candidates: list[tuple[int, float]] = []
    for c in class_indices:
        clip_score = float(framewise_output[:, c].max())
        if clip_score >= clip_threshold:
            candidates.append((c, clip_score))

    if not candidates:
        return []

    # Sort by descending clip score, optionally cap at top-K.
    candidates.sort(key=lambda x: x[1], reverse=True)
    if max_labels_per_clip is not None:
        candidates = candidates[:max_labels_per_clip]

    # Build intervals for each surviving class.
    results: list[ClassifiedClip] = []
    for class_index, clip_score in candidates:
        column = framewise_output[:, class_index]
        mask = column >= frame_threshold
        runs = _runs_above(mask, bridge_frames=bridge_frames, min_run_frames=min_run_frames)
        if not runs:
            # Clip-level cleared the bar but no individual frame run was long
            # enough — emit one interval spanning the whole peak region as a
            # fallback so the consumer knows the label fired *somewhere*.
            peak_idx = int(np.argmax(column))
            half_width = max(1, min_run_frames // 2)
            start_idx = max(0, peak_idx - half_width)
            end_idx = min(num_frames, peak_idx + half_width + 1)
            runs = [(start_idx, end_idx)]

        intervals = [
            ClassifiedInterval(
                class_index=class_index,
                start_seconds=start_idx * frame_duration_seconds,
                end_seconds=end_idx * frame_duration_seconds,
                interval_score=float(column[start_idx:end_idx].max()),
            )
            for start_idx, end_idx in runs
        ]
        results.append(
            ClassifiedClip(
                class_index=class_index,
                clip_score=clip_score,
                intervals=intervals,
            )
        )

    return results
