"""Orpheus Audio Events Detection Agent.

General-purpose audio event classification using PANNs Sound Event Detection
on the AudioSet 527-class ontology. Subscribes to audio-motion-triggered
clips and emits ``audio.classified`` Detections with intra-clip frame-level
intervals.

See ``docs/designs/audio-events-agent.md`` and ADR 0011.
"""

# Version SSoT: the VERSION file, surfaced via installed package metadata.
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("orpheus-agent-audio-events")
except (ImportError, PackageNotFoundError):  # pragma: no cover - source tree
    __version__ = "0.0.0+unknown"
