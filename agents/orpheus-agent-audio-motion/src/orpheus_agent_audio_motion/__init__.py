"""Audio Motion Detector agent package."""

from __future__ import annotations

__all__ = ["__version__", "__author__"]

# Version SSoT: the VERSION file, surfaced via installed package metadata.
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("orpheus-agent-audio-motion")
except (ImportError, PackageNotFoundError):  # pragma: no cover - source tree
    __version__ = "0.0.0+unknown"
__author__ = "Orpheus Project"
