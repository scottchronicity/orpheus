"""Orpheus UI - Modern React/FastAPI Wildlife Monitoring Interface."""

# Version SSoT: the VERSION file, surfaced via installed package metadata.
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("orpheus-ui")
except (ImportError, PackageNotFoundError):  # pragma: no cover - source tree
    __version__ = "0.0.0+unknown"
