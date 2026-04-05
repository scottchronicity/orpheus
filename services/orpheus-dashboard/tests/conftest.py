"""Pytest fixtures and compatibility helpers for Orpheus Dashboard tests."""

from __future__ import annotations

import inspect
import os
import pathlib
import sys
from typing import Any, Callable

import httpx

# Add the project root to sys.path so that 'src' can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Point to the shared test config so OrpheusConfig.get_instance() succeeds at
# module-import time (main.py calls it at module level before any mock runs).
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_TEST_CONFIG = _REPO_ROOT / "config" / "orpheus.test.yaml"
os.environ["ORPHEUS_CONFIG_PATH"] = str(_TEST_CONFIG)


def _add_app_kwarg_compat(clz: type[httpx.Client]) -> None:
    """Patch httpx client classes to ignore the deprecated 'app' kw arg."""
    init: Callable[..., Any] = clz.__init__  # type: ignore[assignment]
    sig = inspect.signature(init)
    if "app" in sig.parameters:
        return

    def _patched_init(self, *args: Any, app: Any = None, **kwargs: Any) -> None:
        init(self, *args, **kwargs)

    clz.__init__ = _patched_init  # type: ignore[assignment]


_add_app_kwarg_compat(httpx.Client)
_add_app_kwarg_compat(httpx.AsyncClient)
